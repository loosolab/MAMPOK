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

.. list-table::
   :header-rows: 0
   :widths: 28 72

   * - **Mamplan-based deployments**
     - Each project is described by a JSON file specifying the tool, data files,
       target cluster, and expiry date; Mampok derives all Kubernetes and S3
       operations from it.
   * - **Defined project lifecycle**
     - Projects cycle through *undeployed → running → stopped*; ``stop-expired``
       and ``list-expiring`` automate expiry handling based on a per-project
       lifetime date.
   * - **S3-backed storage**
     - Input files are uploaded to S3 at deploy time; a sync container writes
       runtime changes back continuously while the project runs.
   * - **Per-project authentication**
     - Projects can be placed behind JWT-based login via a Gatekeeper sidecar,
       with a configurable per-project user access list.
   * - **Batch operations**
     - ``deploy``, ``stop``, ``check-status``, and ``list-expiring`` accept a
       directory of Mamplans and operate on all projects at once.


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
