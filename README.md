<p align="center">
  <img width=400 src="https://raw.githubusercontent.com/loosolab/MAMPOK/main/docs/source/images/LOGO.png">
</p>

[![Release](https://img.shields.io/github/v/release/loosolab/MAMPOK)](https://github.com/loosolab/MAMPOK/releases)
[![PyPI](https://img.shields.io/pypi/v/mampok)](https://pypi.org/project/mampok/)
[![Documentation](https://img.shields.io/badge/documentation-online-blue)](https://loosolab.pages.gwdg.de/software/mampok_v2/)

**Mampok** (**Ma**naging **M**ultiple **P**rojects **O**n **K**ubernetes) deploys
containerized bioinformatics tools — Cellxgene, Jupyter, RStudio, IGV, and more — on a
Kubernetes cluster backed by S3-compatible object storage. You describe your project in a
JSON file (a *Mamplan*); Mampok handles S3 uploads, Kubernetes resource creation, pod
readiness checks, and lifecycle management.

For more information about Mampok, please see the [documentation](https://loosolab.pages.gwdg.de/software/mampok_v2/).

## How to install

### Via Python package

Mampok is published in the Python Package Index (PyPI) under the name [mampok](https://pypi.org/project/mampok/).
It can be installed with the following command:

```bash
pip install mampok
```

### Via repository

You can install Mampok directly from the repository with the following commands:

1. Clone the repository:

```bash
git clone https://github.com/loosolab/MAMPOK
```

2. Move to the new repository directory:

```bash
cd MAMPOK
```

3. Install:

```bash
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
