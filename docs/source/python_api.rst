Python API
==========

Mampok can be used as a Python library via the ``API`` class in
``mampok.interfaces.api``. This lets you integrate Mampok operations into
scripts, pipelines, or web applications without spawning a subprocess.

Unlike the CLI:

* No interactive prompts — all operations run without user input.
* ``deploy()`` and ``stop()`` are **generators** that yield progress dicts —
  you must iterate them to drive execution.
* Explicit edit methods (``edit_lifetime``, ``edit_sharing``) instead of
  string-token parsing.
* No error tolerance — exceptions propagate directly to the caller.

Setup
-----

.. code-block:: python

    from mampok.interfaces.api import API

    api = API("~/.mampok/config.json")

The ``API`` class takes the path to a Mampok config file. The config is
loaded fresh on each API call, so you can reuse the same ``API`` instance
across multiple operations.

Core Operations
---------------

deploy
~~~~~~

.. code-block:: python

    for event in api.deploy("my-project-mamplan.json", timeout=900):
        print(event)

    # After the loop, the Mamplan file has been updated in-place.

``deploy()`` yields progress dicts at each stage:

.. code-block:: python

    {"stage": "s3_bucket", "status": "created", ...}
    {"stage": "s3_upload", "status": "progress", "file": "...", "transferred_pct": 45}
    {"stage": "k8s_apply", "status": "applied", "resource": "Deployment/my-project"}
    {"stage": "k8s_ready", "status": "ready", "pod": "my-project-abc-123"}
    {"stage": "done", "status": "done", "selfservice": {"url": "https://..."}}

Parameters:

.. list-table::
   :header-rows: 1
   :widths: 18 10 12 45

   * - Parameter
     - Type
     - Default
     - Description
   * - ``mamplan_path``
     - Path
     - required
     - Path to a single Mamplan file.
   * - ``timeout``
     - int
     - ``900``
     - Seconds to wait for pod readiness.
   * - ``cleanup``
     - bool
     - ``True``
     - Delete Kubernetes resources automatically on failure.

stop
~~~~

.. code-block:: python

    for event in api.stop("my-project-mamplan.json"):
        print(event)

    # After the loop, deployment.status is false in the Mamplan file.

``stop()`` yields progress dicts from the S3 sync and Kubernetes deletion
steps. The S3 bucket is preserved.

redeploy
~~~~~~~~

.. code-block:: python

    for event in api.redeploy("my-project-mamplan.json"):
        print(event)

Stop and deploy in sequence. Yields stop events followed by deploy events.

list_expiring
~~~~~~~~~~~~~

.. code-block:: python

    expiring = api.list_expiring("/path/to/mamplans/", within_days=7)
    for entry in expiring:
        print(entry["project_id"], entry["days_remaining"])

Returns a list of dicts for active deployments expiring within ``within_days``
days::

    [
        {"project_id": "mouse-atlas", "lifetime": "2026-04-24T...", "days_remaining": 5},
        ...
    ]

Edit Methods
------------

edit_mamplan (generic)
~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    api.edit_mamplan(
        "my-project-mamplan.json",
        deployment__auth=True,
        service__owner="alice",
    )

Generic field editor using ``section__key`` notation. The Mamplan is
validated against the schema after editing and written to disk atomically
(rollback on validation failure).

edit_lifetime
~~~~~~~~~~~~~

.. code-block:: python

    api.edit_lifetime(
        "my-project-mamplan.json",
        lifetime="2027-01-01T00:00:00Z",
    )

Update the ``deployment.lifetime`` field. The ``lifetime`` value must be an
ISO 8601 UTC datetime string.

edit_sharing
~~~~~~~~~~~~

.. code-block:: python

    for event in api.edit_sharing(
        "my-project-mamplan.json",
        users=["alice", "bob"],
        organizations=["mpi-bn"],
    ):
        print(event)

Two-phase operation:

1. Updates ``service.user`` and/or ``service.organization`` and saves to disk.
2. If the deployment is active (``status=True``) and auth-protected
   (``auth=True``), regenerates the Kubernetes auth secret to reflect the
   new user list.

If the Kubernetes update fails, the Mamplan is rolled back to its original
state before the exception is re-raised.

Yields progress events:

.. code-block:: python

    {"stage": "edit_sharing", "status": "saved", "project_id": "..."}
    {"stage": "auth_secret", "status": "updated", "token_url": "https://..."}
    # On failure:
    {"stage": "auth_secret", "status": "failed", "reason": "..."}
    {"stage": "rollback", "status": "done"}

Creating Mamplans
-----------------

create_mamplan
~~~~~~~~~~~~~~

.. code-block:: python

    api.create_mamplan(
        output="/path/to/mamplans/",
        metadata_files=["project_metadata.yaml"],
        project={
            "project_id": "mouse-atlas",
            "tool": "cellxgene",
            "files": ["atlas.h5ad"],
            "creation_date": "2026-04-17T12:00:00Z",
        },
        deployment={
            "cluster": "BN",
            "auth": False,
            "bucket": "",
            "url": "",
        },
        service={
            "owner": "jdoe",
            "analyst": ["jdoe"],
            "datatype": ["scRNA-seq"],
            "download_allowed": False,
            "metadata": [],
            "organization": ["mpi-bn"],
            "user": [],
        },
    )

Creates and validates a new Mamplan JSON file. If ``output`` is a directory,
the filename is auto-generated as ``{project_id}-mamplan.json``.

The optional ``metadata_files`` list provides YAML metadata files whose
fields are merged into the ``service`` section. Explicit values in ``service``
take precedence for scalar fields; lists are merged.

create_sh_mamplan
~~~~~~~~~~~~~~~~~

.. code-block:: python

    project_id = api.create_sh_mamplan(
        output="/path/to/mamplans/",
        username="alice",
        tool="cellxgene",
        bucket="alice-cellxgene-bucket",
        cluster="BN",
        lifetime="2026-12-31T00:00:00Z",
    )
    print(project_id)  # "alice-cellxgene"

Creates a Software Hub Mamplan (``*-shmamplan.json``). Authentication is
always enabled. If ``cluster`` is ``None``, the ``default_cluster`` from
config is used. If ``lifetime`` is ``None``, it defaults to
``now + config.lifetime_days``.

Returns the normalized ``project_id`` string.

Project Info
------------

project_info
~~~~~~~~~~~~

.. code-block:: python

    info = api.project_info("my-project-mamplan.json")
    project = info["projects"]["my-cellxgene-project"]
    print(project["url"])
    print(project["status"])     # live Kubernetes state (bool)
    print(project["lifetime"])   # timezone-aware datetime object

Returns a dict with the full project metadata and live Kubernetes status.
Date fields (``creation_date``, ``lifetime``) are timezone-aware
``datetime`` objects.

Progress Events
---------------

Generator-based operations (``deploy``, ``stop``, ``redeploy``,
``edit_sharing``) yield progress dicts. You must iterate the generator to
drive execution:

.. code-block:: python

    # Correct — iterate to drive execution
    for event in api.deploy("my-project-mamplan.json"):
        stage = event.get("stage")
        status = event.get("status")
        if stage == "s3_upload" and status == "progress":
            pct = event.get("transferred_pct", 0)
            print(f"Uploading: {pct}%")
        elif stage == "done":
            url = event.get("selfservice", {}).get("url")
            print(f"Deployed: {url}")

    # Wrong — generator is never executed
    api.deploy("my-project-mamplan.json")   # ← nothing happens

Error Handling
--------------

All exceptions propagate directly — there is no error tolerance like the CLI.

Common exceptions:

.. list-table::
   :header-rows: 1
   :widths: 35 50

   * - Exception
     - When raised
   * - ``FileNotFoundError``
     - Mamplan or config file not found.
   * - ``IsADirectoryError``
     - A directory was passed where a file is expected.
   * - ``KeyError``
     - Tool has no matching Mamplate.
   * - ``ValueError``
     - Tool or cluster not found in config.
   * - ``jsonschema.ValidationError``
     - Mamplan/config data violates the schema.
   * - ``TimeoutError``
     - Pods not ready within the timeout.
