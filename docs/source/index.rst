.. figure:: images/LOGO.png
   :align: center
   :width: 40%

Mampok
======

**Mampok** (Managing Multiple Projects On Kubernetes) deploys containerized
bioinformatics tools — Cellxgene, Jupyter, RStudio, IGV, and more — on a
Kubernetes cluster backed by S3-compatible object storage. You describe your
project in a JSON file (a *Mamplan*); Mampok handles S3 uploads, Kubernetes
resource creation, pod readiness checks, and lifecycle management.

Key features:

* **Declarative project files** — define once, deploy anywhere your config allows
* **Lifecycle management** — deploy, stop, redeploy, and auto-expire projects
* **Flexible storage** — files uploaded to S3 at deploy time; runtime data synced back continuously
* **Optional authentication** — per-project login protection with a Gatekeeper sidecar
* **Batch operations** — manage entire repositories of projects with a single command


.. toctree::
   :maxdepth: 2
   :caption: Getting Started

   getting_started
   concepts
   configuration

.. toctree::
   :maxdepth: 2
   :caption: User Guide

   mamplans
   commands
   selection

.. toctree::
   :maxdepth: 2
   :caption: Admin Guide

   mamplates
   advanced

.. toctree::
   :maxdepth: 2
   :caption: Reference

   python_api
   api_reference
