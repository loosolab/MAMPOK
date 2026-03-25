# Mampok v2

Kubernetes deployment manager for bioinformatics pipelines.

Mampok manages containerized bioinformatics tools on Kubernetes. It uses
**Mamplans** (deployment configurations per project) and **Mamplates**
(container templates per tool) to deploy, stop, and monitor workloads,
with S3 as a file storage backend.

---

## Requirements

- Python 3.11+
- Access to a Kubernetes cluster (kubeconfig file)
- S3-compatible storage (e.g. MinIO, Ceph)

---

## Installation

```bash
pip install mampok
```

Or from source:

```bash
git clone <repository-url>
pip install ./mampok_v2
```

After installation, the `mampok` command is available:

```bash
mampok --help
```

---

## Configuration

Mampok reads its configuration from a JSON file.
The default location is `~/.mampok/config.json`.
A different path can be passed to any command via `--config`.

### Minimal example

```json
{
  "cluster": {
    "BN": {
      "host": "bioinformatics-cluster.example.com",
      "namespace": "mampok",
      "kubeconfig_path": "/home/user/.kube/config-bn",
      "ingress_class": "nginx"
    }
  },
  "s3": {
    "endpoint": "https://s3.example.com",
    "access_key": "mampok-service",
    "secret_key": "changeme",
    "secretname": "s3-credentials",
    "prefix": "mampok"
  },
  "mamplan_repo": "/data/mamplans",
  "mamplates_path": "/data/mamplates",
  "lifetime_days": 30
}
```

### Config fields

| Field | Type | Description |
|-------|------|-------------|
| `cluster` | object | Named cluster profiles (at least one required) |
| `cluster.<name>.host` | string | Ingress host of the cluster |
| `cluster.<name>.namespace` | string | Kubernetes namespace for deployments |
| `cluster.<name>.kubeconfig_path` | string | Path to the kubeconfig file |
| `cluster.<name>.ingress_class` | string | Ingress class (e.g. `nginx`) |
| `cluster.<name>.annotations` | object | Extra Ingress annotations |
| `cluster.<name>.auth_proxy` | object | Gatekeeper proxy config (required when `auth: true` is used) |
| `s3.endpoint` | string | S3 endpoint URL |
| `s3.access_key` | string | S3 access key ID |
| `s3.secret_key` | string | S3 secret access key |
| `s3.secretname` | string | Name of the pre-existing Kubernetes Secret holding S3 credentials |
| `s3.prefix` | string | Optional prefix for auto-generated S3 bucket names |
| `mamplan_repo` | string | Path to the Mamplan repository directory |
| `mamplates_path` | string | Path to the Mamplates directory |
| `lifetime_days` | integer | Default deployment lifetime in days |

### Auth proxy (optional)

Required only when deploying projects with `"auth": true`:

```json
"auth_proxy": {
  "auth_proxy_image": "registry.example.com/auth-proxy:latest",
  "proxy_port": 8080,
  "auth_annotations": {
    "nginx.ingress.kubernetes.io/auth-type": "basic"
  },
  "image_pull_secrets": ["regcred"]
}
```

---

## Mamplans and Mamplates

A **Mamplate** describes a container tool (image, resources, ports, environment).
It lives in the `mamplates_path` directory and is named `<tool>-mamplate.json`.

A **Mamplan** describes a concrete project deployment (which tool, which cluster,
which files, expiry date, etc.).
It is named `<project-id>-mamplan.json` and lives in your `mamplan_repo`.

---

## CLI Commands

All commands accept `--config <path>` to override the default config location.

### deploy

Deploy a project (or all projects in a directory) to Kubernetes.

```bash
mampok deploy <path> [OPTIONS]
```

```
Arguments:
  path                   Mamplan file or directory (scanned recursively)

Options:
  --config PATH          Config file  [default: ~/.mampok/config.json]
  -s, --selection TEXT   Filter: section:key:value  (repeatable, AND-combined)
  -rs, --regex-select TEXT  Regex filter: section:key:pattern  (repeatable)
  --timeout INT          Wait-for-ready timeout in seconds  [default: 300]
  --dry-run              Print what would be deployed without applying
  --throw-error          Abort on first failure (disables error tolerance)
```

**Examples:**

```bash
# Deploy a single project
mampok deploy /data/mamplans/my-project-mamplan.json

# Deploy all projects in a directory
mampok deploy /data/mamplans/

# Deploy only projects for a specific tool
mampok deploy /data/mamplans/ -s project:tool:cellxgene

# Dry-run: show what would be deployed
mampok deploy /data/mamplans/ --dry-run

# Deploy with a longer timeout
mampok deploy /data/mamplans/my-project-mamplan.json --timeout 600
```

---

### stop

Stop a deployment. Removes Kubernetes resources; the S3 bucket and data are preserved.

```bash
mampok stop <path> [OPTIONS]
```

```
Arguments:
  path                   Mamplan file or directory

Options:
  --config PATH
  -s, --selection TEXT
  -rs, --regex-select TEXT
  --throw-error
```

**Example:**

```bash
mampok stop /data/mamplans/my-project-mamplan.json
```

---

### stop-expired

Stop all active deployments whose lifetime has expired.
Displays a list of affected projects and asks for confirmation before proceeding.

```bash
mampok stop-expired <repository> [OPTIONS]
```

```
Arguments:
  repository             Path to Mamplan repository directory

Options:
  --config PATH
  -Y, --yes              Skip confirmation prompt
  --throw-error
```

**Example:**

```bash
# Interactive confirmation
mampok stop-expired /data/mamplans/

# Skip confirmation (e.g. in cron jobs)
mampok stop-expired /data/mamplans/ -Y
```

---

### redeploy

Stop and redeploy a project in one step.

```bash
mampok redeploy <path> [OPTIONS]
```

```
Arguments:
  path                   Mamplan file or directory

Options:
  --config PATH
  -s, --selection TEXT
  -rs, --regex-select TEXT
  --timeout INT          [default: 300]
  --throw-error
```

**Example:**

```bash
mampok redeploy /data/mamplans/my-project-mamplan.json
```

---

### edit-mamplan

Edit fields in an existing Mamplan and optionally redeploy immediately.
Fields are specified as `section:key:value` tokens.

```bash
mampok edit-mamplan <path> [OPTIONS]
```

```
Arguments:
  path                   Path to a single Mamplan file

Options:
  -e, --edit TEXT        Field to edit: section:key:value  (repeatable)
  --redeploy             Redeploy after saving
  --timeout INT          [default: 300]
  --config PATH
  --throw-error
```

**Examples:**

```bash
# Extend the lifetime
mampok edit-mamplan /data/mamplans/my-project-mamplan.json \
  -e deployment:lifetime:2025-12-31T00:00:00Z

# Enable auth and redeploy
mampok edit-mamplan /data/mamplans/my-project-mamplan.json \
  -e deployment:auth:true \
  --redeploy

# Edit multiple fields at once
mampok edit-mamplan /data/mamplans/my-project-mamplan.json \
  -e deployment:cluster:BN_public \
  -e deployment:generate_url:false
```

---

### create-mamplan

Create a new Mamplan file. The `project_id` is automatically normalized
(lowercase, underscores replaced with hyphens).

```bash
mampok create-mamplan [OPTIONS]
```

```
Required options:
  --project-id TEXT      Unique project identifier
  --tool TEXT            Tool name (must match a mamplate)
  --cluster TEXT         Target cluster name (as defined in config)
  --lifetime TEXT        Expiry date in ISO 8601 format (e.g. 2025-12-31T00:00:00Z)
  --output PATH          Output path (file or directory)

Optional options:
  --files TEXT           File to upload (repeatable)
  --analyst TEXT         Analyst username (repeatable)
  --owner TEXT           Project owner username
  --organization TEXT    Organization name (repeatable); use 'public' for open access
  --user TEXT            Username with access (repeatable)
  --datatype TEXT        Data type label (repeatable)
  --metadata TEXT        Metadata ID (repeatable)
  --bucket TEXT          S3 bucket name (auto-generated if omitted)
  --auth / --no-auth     Enable login protection  [default: no-auth]
  --generate-url / --no-generate-url  [default: generate-url]
  --config PATH
```

**Example:**

```bash
mampok create-mamplan \
  --project-id my-scrna-project \
  --tool cellxgene \
  --cluster BN \
  --lifetime 2025-12-31T00:00:00Z \
  --output /data/mamplans/ \
  --files /data/project/matrix.h5ad \
  --owner jdoe \
  --analyst jdoe \
  --organization genomics \
  --datatype scRNA-seq
```

---

### check-status

Show a status table comparing the expected state (from each Mamplan) with the
actual state in Kubernetes.

```bash
mampok check-status <repository> [OPTIONS]
```

```
Arguments:
  repository             Path to Mamplan repository directory

Options:
  --config PATH
  -s, --selection TEXT
  -rs, --regex-select TEXT
  --throw-error
```

**Example output:**

```
Project ID          Expected  Actual    Healthy
----------------------------------------------------
my-scrna-project    active    active    ✓
other-project       active    missing   ✗
old-project         inactive  missing   ✓
```

**Example:**

```bash
mampok check-status /data/mamplans/

# Only check projects on a specific cluster
mampok check-status /data/mamplans/ -s deployment:cluster:BN
```

---

### update-auth

Regenerate the htpasswd-based authentication secret for a project.
The user list is derived from `service.organization` and `service.user` in the Mamplan.
If `organization` contains `public`, access is set to public (no password).

```bash
mampok update-auth <path> [OPTIONS]
```

```
Arguments:
  path                   Mamplan file or directory

Options:
  --config PATH
  --throw-error
```

**Example:**

```bash
mampok update-auth /data/mamplans/my-project-mamplan.json
```

---

### download

Download output files from the project's S3 bucket to a local directory.
Which files are downloaded is determined by the `downloadpaths` field in the Mamplate.

```bash
mampok download <path> <output> [OPTIONS]
```

```
Arguments:
  path                   Mamplan file or directory
  output                 Local output directory (created if it does not exist)

Options:
  --config PATH
  --throw-error
```

**Example:**

```bash
mampok download /data/mamplans/my-project-mamplan.json /tmp/results/
```

---

## Selection and Filtering

The `-s` and `-rs` flags filter Mamplans before any operation is performed.
Multiple filters are combined with AND — a Mamplan must match all of them.

**Exact match:**

```bash
# Only projects using cellxgene
mampok deploy /data/mamplans/ -s project:tool:cellxgene

# Only projects on a specific cluster
mampok stop /data/mamplans/ -s deployment:cluster:BN_public
```

**Regex match:**

```bash
# All projects whose ID starts with "mouse-"
mampok check-status /data/mamplans/ -rs project:project_id:^mouse-

# All projects with "rna" anywhere in the project ID
mampok deploy /data/mamplans/ -rs project:project_id:.*rna.*
```

**Combined (AND):**

```bash
# cellxgene projects on cluster BN only
mampok deploy /data/mamplans/ \
  -s project:tool:cellxgene \
  -s deployment:cluster:BN
```

---

## Error Tolerance

By default, Mampok processes all Mamplans even when individual ones fail.
Errors are collected and printed as a summary at the end.
The exit code is 1 if any errors occurred.

To abort immediately on the first failure, use `--throw-error`:

```bash
mampok deploy /data/mamplans/ --throw-error
```

---

## Global Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--config PATH` | `~/.mampok/config.json` | Path to config file |
| `-s, --selection TEXT` | — | Key-value filter (repeatable) |
| `-rs, --regex-select TEXT` | — | Regex filter (repeatable) |
| `--timeout INT` | `300` | Wait-for-ready timeout in seconds |
| `--throw-error` | off | Abort on first failure |
| `-Y, --yes` | off | Skip confirmation prompts |
| `--dry-run` | off | Print actions without executing (deploy only) |
