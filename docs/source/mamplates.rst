Mamplates
=========

A **Mamplate** (Mampok Template) is a JSON file that defines the container
blueprint for a specific tool. Admins create Mamplates; end users reference
them by tool name in their Mamplans.

.. seealso::

   :doc:`concepts` — how Mamplates relate to Mamplans and the config.

File Naming and Location
------------------------

Mamplate files follow this naming convention::

    {tool}-mamplate.json

Examples: ``cellxgene-mamplate.json``, ``jupyter-mamplate.json``.

The tool name (the part before ``-mamplate.json``) is what users write in
``project.tool`` of their Mamplan.

All Mamplate files live in a flat directory specified by ``mamplates_path``
in ``config.json``. Subdirectories are not scanned.

Annotated Example
-----------------

This is the complete ``cellxgene-mamplate.json`` from the examples directory:

.. code-block:: json

    {
      "tool": "cellxgene",
      "image": "ghcr.io/chanzuckerberg/cellxgene:1.2.0",
      "containertype": "maincontainer",
      "ports": 5005,
      "command": [
        "cellxgene",
        "launch",
        "/DOWNLOADS3/__project.files__",
        "--host", "0.0.0.0",
        "--port", "5005"
      ],
      "resources": {
        "limits": {
          "cpu": "4",
          "memory": "16Gi"
        },
        "requests": {
          "cpu": "1",
          "memory": "4Gi"
        }
      },
      "volume": {
        "name": "filedir",
        "mountPath": "/DOWNLOADS3"
      },
      "readinessProbe": {
        "tcpSocket": {
          "port": 5005
        },
        "initialDelaySeconds": 10,
        "periodSeconds": 10,
        "failureThreshold": 6
      }
    }

Key points:

* ``__project.files__`` in ``command`` is a **template token** — it is
  replaced at deploy time with the comma-joined file paths from the Mamplan's
  ``project.files``. See :ref:`template-tokens`.
* ``volume.mountPath`` (``/DOWNLOADS3``) is where the S3 init container
  downloads files. The main container then reads from this path.
* ``readinessProbe.tcpSocket`` tells Kubernetes to wait until port 5005
  accepts connections before marking the pod ready.

Field Reference
---------------

.. list-table::
   :header-rows: 1
   :widths: 22 12 12 45

   * - Field
     - Type
     - Required
     - Description
   * - ``tool``
     - string
     - yes
     - Unique tool identifier. Must match the filename prefix. Used in
       Mamplan ``project.tool``.
   * - ``toolDisplayname``
     - string
     - no
     - Human-readable display name (e.g. ``"CellXGene"``). Falls back to
       ``tool`` if not set. Used in the Python API ``project_info()`` output.
   * - ``image``
     - string
     - yes
     - Docker image URI (e.g. ``"ghcr.io/foo/bar:1.2.0"``).
   * - ``containertype``
     - string
     - yes
     - ``"maincontainer"`` for the main application container;
       ``"initcontainer"`` for init containers that run to completion before
       the main container starts.
   * - ``ports``
     - integer
     - yes (if maincontainer)
     - Port the container listens on for web traffic. Required for
       ``containertype: maincontainer``; not used for init containers.
   * - ``resources``
     - object
     - yes
     - CPU and memory resource requests and limits. See :ref:`resources`.
   * - ``command``
     - array of strings
     - no
     - Overrides the container entrypoint. Template tokens are expanded
       (see :ref:`template-tokens`).
   * - ``args``
     - array of strings
     - no
     - Arguments passed to the entrypoint. Template tokens are expanded.
   * - ``env``
     - array of objects
     - no
     - Environment variables: ``[{"name": "VAR", "value": "val"}]``.
       Template tokens are expanded in ``value``.
   * - ``volume``
     - object
     - no
     - Mounts an ``emptyDir`` volume into the container. Required fields:
       ``name`` (string) and ``mountPath`` (string).
   * - ``imagePullPolicy``
     - string
     - no
     - Kubernetes image pull policy: ``Always``, ``Never``, or
       ``IfNotPresent``.
   * - ``readinessProbe``
     - object
     - no
     - Kubernetes readiness probe. See :ref:`readiness-probes`.
   * - ``annotation``
     - object
     - no
     - Extra Kubernetes Ingress annotations applied to this tool's
       deployments. Merged with cluster-level ``annotations`` from config.
   * - ``container_data``
     - object
     - no
     - Sync specific container paths to S3 during runtime. See
       :ref:`s3-persistence`.
   * - ``full_bucket_overwrite``
     - string
     - no
     - Sync the entire container path bidirectionally with the S3 bucket
       root. Mutually exclusive with ``container_data``. See
       :ref:`s3-persistence`.

.. _resources:

Resources
---------

The ``resources`` field follows the Kubernetes conventions:

.. code-block:: json

    "resources": {
      "limits": {
        "cpu": "4",
        "memory": "16Gi"
      },
      "requests": {
        "cpu": "1",
        "memory": "4Gi"
      }
    }

* ``limits`` — maximum resources the container may use.
* ``requests`` — guaranteed resources for scheduling.
* CPU can be specified as an integer/float (``2``, ``0.5``) or in millicores
  (``"500m"``).
* Memory uses Kubernetes notation: ``"512Mi"``, ``"4Gi"``, ``"80Gi"``.

.. _template-tokens:

Template Substitution Tokens
-----------------------------

You can embed values from the Mamplan into ``command``, ``args``, and
``env[].value`` using the ``__section.key__`` syntax. Tokens are resolved at
deploy time after the Mamplan's ``container`` overrides are merged.

.. list-table::
   :header-rows: 1
   :widths: 35 50

   * - Token
     - Resolves to
   * - ``__project.files__``
     - Comma-joined list of file paths from ``project.files`` (e.g.
       ``"data.h5ad,markers.csv"``)
   * - ``__project.project_id__``
     - The project ID string
   * - ``__deployment.cluster__``
     - The cluster name from the Mamplan
   * - ``__service.owner__``
     - The owner username

Example — Cellxgene uses ``__project.files__`` to pass the data files as a
command-line argument::

    "command": [
      "cellxgene", "launch",
      "/DOWNLOADS3/__project.files__",
      "--host", "0.0.0.0"
    ]

At deploy time, if the Mamplan has ``"files": ["atlas.h5ad"]``, the command
becomes::

    cellxgene launch /DOWNLOADS3/atlas.h5ad --host 0.0.0.0

.. _readiness-probes:

Readiness Probes
----------------

Mampok waits for the readiness probe to pass before marking a deployment
complete. Two probe types are supported:

**TCP socket** (check that a port accepts connections):

.. code-block:: json

    "readinessProbe": {
      "tcpSocket": {"port": 5005},
      "initialDelaySeconds": 10,
      "periodSeconds": 10,
      "failureThreshold": 6
    }

**HTTP GET** (check that an HTTP endpoint returns a success status):

.. code-block:: json

    "readinessProbe": {
      "httpGet": {"path": "/health", "port": 8080},
      "initialDelaySeconds": 5,
      "periodSeconds": 5,
      "failureThreshold": 3,
      "timeoutSeconds": 2
    }

Probe fields:

.. list-table::
   :header-rows: 1
   :widths: 25 10 10 40

   * - Field
     - Type
     - Default
     - Description
   * - ``initialDelaySeconds``
     - integer
     - ``5``
     - Seconds to wait after container start before probing.
   * - ``periodSeconds``
     - integer
     - ``10``
     - How often (in seconds) to probe.
   * - ``failureThreshold``
     - integer
     - ``3``
     - Consecutive failures before marking not ready.
   * - ``timeoutSeconds``
     - integer
     - ``1``
     - Seconds per probe attempt before timing out.

.. _s3-persistence:

S3 Data Persistence
-------------------

Some tools generate output data during their runtime (e.g. Cellxgene
annotations, Jupyter notebooks, R scripts). Mampok provides two mechanisms
to persist this data to S3 so it survives stops and redeployments.

.. important::

   ``container_data`` and ``full_bucket_overwrite`` are **mutually
   exclusive** — you can use at most one per Mamplate.

``container_data`` (selective sync)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Syncs specific container paths to ``s3://bucket/container_data/`` using a
rclone sidecar container that runs during the pod's lifetime.

.. code-block:: json

    "container_data": {
      "paths": [
        "/home/user/.cellxgene/annotations/",
        "/home/user/outputs/"
      ],
      "restore_on_deploy": true,
      "sync_interval_seconds": 120,
      "sync_timeout_seconds": 3600
    }

.. list-table::
   :header-rows: 1
   :widths: 25 10 10 42

   * - Field
     - Type
     - Default
     - Description
   * - ``paths``
     - array of strings
     - required
     - Absolute container paths to sync. Must start with ``/``.
   * - ``restore_on_deploy``
     - boolean
     - ``false``
     - If ``true``, data from ``container_data/`` in S3 is downloaded back
       into the container at deploy time (useful for tools that save state
       across redeployments).
   * - ``sync_interval_seconds``
     - integer
     - ``60``
     - How often the sidecar syncs to S3 (minimum: 30 seconds).
   * - ``sync_timeout_seconds``
     - integer
     - ``3600``
     - Timeout Mampok waits for a final sync before deleting resources on
       stop. Deletion proceeds after the timeout even if sync is incomplete.

**Best for:** Tools with specific output directories (Cellxgene annotations,
pipeline outputs).

``full_bucket_overwrite`` (bidirectional sync)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Syncs an entire container directory bidirectionally with the S3 bucket root
using rclone bisync. No ``container_data/`` prefix — the entire bucket is
treated as the container directory.

.. code-block:: json

    "full_bucket_overwrite": "/home/user/workspace/"

The value is the absolute container path to sync. On pod start, the entire
S3 bucket is downloaded to this path. During runtime, rclone bisync keeps
them in sync in both directions.

**Best for:** Workspace-style tools where the entire working directory should
persist (RStudio, Jupyter).

Init Containers
---------------

Init containers run to completion before the main container starts. Mampok
automatically prepends an S3 download init container whenever the Mamplan has
non-empty ``project.files``. This init container downloads the listed files
to the volume mount path (e.g. ``/DOWNLOADS3``).

You can define additional custom init containers by setting
``containertype: initcontainer`` in a Mamplate and then referencing that
Mamplate's tool name in the Mamplan's ``project.init_container`` list.

Example init container Mamplate (``sleep-init-mamplate.json``):

.. code-block:: json

    {
      "tool": "sleep-init",
      "image": "busybox:1.36",
      "containertype": "initcontainer",
      "command": ["/bin/sh", "-c", "sleep 60"],
      "resources": {
        "limits": {"cpu": "100m", "memory": "64Mi"},
        "requests": {"cpu": "50m", "memory": "32Mi"}
      }
    }

To use it, add it to the Mamplan::

    "project": {
      "init_container": ["sleep-init"],
      ...
    }

Init container overrides from the Mamplan's ``container.init`` section are
applied in the same way as main container overrides.
