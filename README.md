# Mampok v2

Mampok deploys containerized bioinformatics tools (Cellxgene, Jupyter, RStudio, IGV) to
Kubernetes with S3 as a file storage backend.

It uses two JSON files to describe deployments:

- **Mamplate**: container blueprint for a tool (image, resources, ports) — created by admins
- **Mamplan**: project deployment configuration (which tool, which cluster, which files) — created per project

## Requirements

- Python 3.11+
- Access to a Kubernetes cluster (kubeconfig file)
- S3-compatible storage (e.g. MinIO, Ceph)

## Installation

```bash
git clone https://github.com/loosolab/MAMPOK
cd MAMPOK
pip install .
```

## Quick start

**1. Create a config file** (pass its path to every command via `--config`):

```json
{
  "cluster": {
    "MY_CLUSTER": {
      "host": "ingress.example.com",
      "namespace": "mampok",
      "kubeconfig_path": "/home/user/.kube/my-cluster-config"
    }
  },
  "s3": {
    "endpoint": "https://s3.example.com",
    "access_key": "my-access-key",
    "secret_key": "my-secret-key",
    "secretname": "s3-credentials",
    "prefix": "mampok"
  },
  "mamplates_path": "/path/to/mamplates/",
  "lifetime_days": 30,
  "mampok_version": ">=2.0.0,<3.0.0"
}
```

**2. Create a Mamplan:**

```bash
mampok create-mamplan \
  --project-id my-project \
  --tool cellxgene \
  --cluster MY_CLUSTER \
  --owner jdoe \
  --datatype scRNA-seq \
  --files data.h5ad \
  --output ~/mamplans/ \
  --config /path/to/config.json
```

**3. Deploy:**

```bash
mampok deploy ~/mamplans/my-project-mamplan.json --config /path/to/config.json
```

## Documentation

Full documentation including configuration reference, Mamplan/Mamplate format, all CLI
commands, and the Python API is available at:
https://loosolab.pages.gwdg.de/software/mampok/
