Mamplans
========

A **Mamplan** (Mampok Project Plan) is a JSON file that describes one
project deployment. This page is the complete reference for the Mamplan
format.

.. seealso::

   :doc:`concepts` — conceptual overview of how Mamplans, Mamplates, and
   config.json interact.

File Naming and Location
------------------------

Mamplan files must follow this naming convention::

    {project_id}-mamplan.json

Rules for ``project_id``:

* All lowercase
* Hyphens ``-`` allowed, underscores ``_`` not allowed
* No uppercase letters
* ``mampok create-mamplan`` auto-normalizes the ID (converts underscores to
  hyphens, lowercases everything)

Mamplan files live in the ``mamplan_repo`` directory defined in your
:doc:`configuration`. Subdirectories are scanned recursively, so you can
organize projects into folders.

Creating a Mamplan
------------------

**Option 1: CLI command** (recommended)::

    mampok create-mamplan \
      --project-id my-cellxgene-project \
      --tool cellxgene \
      --cluster BN \
      --owner jdoe \
      --datatype scRNA-seq \
      --files data.h5ad \
      --output ~/mamplans/

See :ref:`cmd-create-mamplan` for all available flags, including
``--metadata-file`` to populate the service section from a YAML file.

**Option 2: Copy and edit manually**

Copy the example below and edit the fields. Note the :ref:`mutable-fields`
that Mampok manages automatically — do not set these by hand unless you know
what you are doing.

Annotated Example
-----------------

This is the structure of a complete Mamplan (all optional sections included):

.. code-block:: json

    {
      "project": {
        "project_id": "my-cellxgene-project",
        "tool": "cellxgene",
        "files": ["data.h5ad"],
        "creation_date": "2026-03-26T12:00:00Z",
        "init_container": ["sleep-init"]
      },
      "deployment": {
        "cluster": "BN",
        "status": false,
        "auth": false,
        "bucket": "",
        "lifetime": "2027-01-01T00:00:00Z",
        "url": ""
      },
      "service": {
        "owner": "jdoe",
        "analyst": ["jdoe"],
        "datatype": ["scRNA-seq"],
        "download_allowed": false,
        "metadata": [],
        "organization": ["mpi-bn"],
        "user": ["jdoe"]
      },
      "container": {
        "main": {
          "env": [{"name": "CUSTOM_VAR", "value": "hello"}]
        }
      },
      "tags": {
        "gse": "GSE123456"
      }
    }

Section Reference
-----------------

``project`` section
~~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 20 12 10 45

   * - Field
     - Type
     - Required
     - Description
   * - ``project_id``
     - string
     - yes
     - Unique project identifier. Lowercase, hyphens only. Must match the
       filename prefix.
   * - ``tool``
     - string
     - yes
     - Tool name. Must match a Mamplate file in ``mamplates_path``
       (e.g. ``"cellxgene"`` → ``cellxgene-mamplate.json``).
   * - ``files``
     - array of strings
     - yes
     - Paths to data files to upload to S3 under ``analysis_data/``. Paths
       are relative to the working directory when you run ``mampok deploy``.
       Can be empty (``[]``) if no files need to be uploaded.
   * - ``creation_date``
     - ISO 8601 datetime (UTC)
     - yes
     - Set automatically by ``create-mamplan``. Format:
       ``2026-03-26T12:00:00Z``.
   * - ``init_container``
     - array of strings
     - no
     - Names of additional init container Mamplates to run before the main
       container. Mampok always adds a built-in S3 download init container
       when ``files`` is non-empty.
   * - ``project_size``
     - integer (KB)
     - no
     - Total size of uploaded files. Set automatically by Mampok after deploy.

``deployment`` section
~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 20 12 10 10 45

   * - Field
     - Type
     - Required
     - Default
     - Description
   * - ``cluster``
     - string
     - yes
     - —
     - Name of the target cluster profile in ``config.json``
       (e.g. ``"BN"``).
   * - ``status``
     - boolean
     - yes
     - ``false``
     - Whether the project is currently deployed. **Written by Mampok.**
       Do not set manually.
   * - ``auth``
     - boolean
     - yes
     - ``false``
     - Enable login protection via the Gatekeeper auth proxy. Requires
       ``auth_proxy`` to be configured in ``config.json``.
   * - ``bucket``
     - string
     - yes
     - auto
     - S3 bucket name. Leave empty (``""``) to let Mampok auto-generate it
       as ``{prefix}-{project_id}-{tool}``.
   * - ``lifetime``
     - ISO 8601 datetime (UTC)
     - yes
     - —
     - Expiry date of the deployment. **Overwritten by Mampok on deploy**
       to ``now + lifetime_days``. Use ``mampok edit-mamplan`` or
       ``mampok create-mamplan`` to set a relative value (``30d``, ``4w``,
       ``3m``).
   * - ``url``
     - string
     - yes
     - auto
     - Public URL of the deployed tool. **Written by Mampok after deploy.**
   * - ``custom_url_id``
     - string
     - no
     - ``project_id``
     - Custom path segment used in the Ingress URL instead of ``project_id``.
       Useful when the project ID is too long or not user-friendly.
   * - ``random_url_suffix``
     - boolean
     - no
     - ``false``
     - Append 5 random characters to the URL path for additional obscurity.

``service`` section
~~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 20 12 10 45

   * - Field
     - Type
     - Required
     - Description
   * - ``owner``
     - string
     - yes
     - Username of the project owner. Used for auth secret derivation.
   * - ``analyst``
     - array of strings
     - yes
     - Usernames of analysts working on this project.
   * - ``datatype``
     - array of strings
     - yes
     - Data type labels (e.g. ``["scRNA-seq", "ATAC-seq"]``).
   * - ``download_allowed``
     - boolean
     - yes
     - Whether users may download files from this project via the portal.
   * - ``metadata``
     - array of strings
     - yes
     - Metadata IDs (e.g. GEO accessions). Can be empty (``[]``).
   * - ``organization``
     - array of strings
     - yes
     - Organizations with access. Use ``["public"]`` for unrestricted access
       (bypasses auth even when ``auth: true``). Can be empty (``[]``).
   * - ``user``
     - array of strings
     - yes
     - Additional individual usernames with access. Combined with
       ``organization`` when generating the auth secret.

``container`` section (optional)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The optional ``container`` section allows you to override fields from the
Mamplate's container definition for this specific project. This is useful
when you need project-specific environment variables, resource limits, or
startup arguments without modifying the shared Mamplate.

.. code-block:: json

    "container": {
      "main": {
        "env": [{"name": "GENOME", "value": "hg38"}],
        "resources": {
          "limits": {"cpu": "8", "memory": "32Gi"},
          "requests": {"cpu": "2", "memory": "8Gi"}
        }
      },
      "init": {
        "command": ["/bin/sh", "-c", "echo ready"]
      }
    }

Merge rules:

* **Dict fields** (e.g. ``resources``, ``env`` as a dict) are deep-merged.
* **List fields** (e.g. ``env`` as a list, ``args``, ``command``) are
  **replaced**, not appended.
* Template tokens (``__section.key__``) are expanded after the merge.

``tags`` section (optional)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The ``tags`` section is a free-form JSON object for additional metadata.
Well-known keys:

.. list-table::
   :header-rows: 1
   :widths: 20 60

   * - Key
     - Description
   * - ``gse``
     - GEO Series accession number (e.g. ``"GSE123456"``)
   * - ``pubmedid``
     - PubMed ID of the associated publication

Any other keys are allowed and will be stored as-is.

.. _mutable-fields:

Mutable Fields
--------------

The following fields are **written or overwritten by Mampok** at runtime.
You should not set them manually in a freshly created Mamplan:

.. list-table::
   :header-rows: 1
   :widths: 30 55

   * - Field
     - When it is set
   * - ``deployment.status``
     - ``true`` after successful deploy; ``false`` after stop
   * - ``deployment.url``
     - Written after successful deploy
   * - ``deployment.lifetime``
     - Overwritten on deploy to ``now + config.lifetime_days``
   * - ``project.project_size``
     - Written after files are uploaded to S3 (total KB)

.. warning::

   If you edit these fields manually, Mampok will use the values you set.
   This can cause ``check-status`` to report incorrect results or
   ``stop-expired`` to miss an expired project.

Lifetime Format
---------------

The ``deployment.lifetime`` field stores an ISO 8601 UTC datetime string::

    2027-01-01T00:00:00Z

When creating or editing a Mamplan via the CLI, you can use convenient
relative shorthands that are automatically converted to absolute dates:

.. list-table::
   :header-rows: 1
   :widths: 15 40

   * - Format
     - Meaning
   * - ``30d``
     - 30 days from now
   * - ``4w``
     - 4 weeks (28 days) from now
   * - ``3m``
     - 3 months (90 days) from now

In ``edit-mamplan``, you can also extend the existing lifetime by a relative
offset::

    mampok edit-mamplan my-project-mamplan.json -e deployment:lifetime:+30d

This adds 30 days to the **current lifetime** (not to today), making it safe
to renew a project multiple times without losing days.

What Happens on Stop
--------------------

When you run ``mampok stop``:

1. A final S3 sync is triggered (if the Mamplate uses ``container_data``).
2. All Kubernetes resources are deleted (Deployment, Service, Ingress,
   Secrets).
3. ``deployment.status`` is set to ``false`` and the Mamplan file is saved.
4. **The S3 bucket and all data are preserved.** You can redeploy at any
   time and the data will still be there.
