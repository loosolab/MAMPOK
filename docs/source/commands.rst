CLI Commands
============

Mampok provides 10 CLI commands. All commands accept a ``--config`` option
to specify a config file (default: ``~/.mampok/config.json``).

.. tip::

   Run ``mampok --help`` for a summary, or ``mampok <command> --help`` for
   command-specific help.

Global Options
--------------

These options are available on all commands:

.. list-table::
   :header-rows: 1
   :widths: 25 15 45

   * - Option
     - Default
     - Description
   * - ``--config PATH``
     - ``~/.mampok/config.json``
     - Path to the Mampok config file.
   * - ``--log-level LEVEL``
     - ``WARNING``
     - Logging verbosity: ``DEBUG``, ``INFO``, ``WARNING``, ``ERROR``.
   * - ``--debug``
     - off
     - Shorthand for ``--log-level DEBUG``.

Selection options (available on most commands — see :doc:`selection`):

.. list-table::
   :header-rows: 1
   :widths: 25 45

   * - Option
     - Description
   * - ``-s / --selection section:key:value``
     - Exact-match filter (repeatable, AND-combined).
   * - ``-rs / --regex-select section:key:pattern``
     - Regex filter (repeatable, AND-combined).

----

.. _cmd-deploy:

deploy
------

**Synopsis**::

    mampok deploy <path> [OPTIONS]

**Description**

Deploy one or more projects to Kubernetes. ``<path>`` can be a single
Mamplan file or a directory (scanned recursively for ``*-mamplan.json`` and
``*-shmamplan.json`` files).

Before deploying, Mampok shows a confirmation table listing the affected
projects. Use ``-Y`` to skip the prompt.

After a successful deployment the Mamplan file is updated in-place with
``deployment.status=true``, the generated URL, and the new lifetime
(``now + lifetime_days``).

**Arguments**

.. list-table::
   :header-rows: 1
   :widths: 20 60

   * - Argument
     - Description
   * - ``<path>``
     - Path to a Mamplan file or directory.

**Options**

.. list-table::
   :header-rows: 1
   :widths: 25 12 45

   * - Option
     - Default
     - Description
   * - ``--config PATH``
     - ``~/.mampok/config.json``
     - Config file path.
   * - ``-s / --selection``
     - —
     - Filter Mamplans (see :doc:`selection`).
   * - ``-rs / --regex-select``
     - —
     - Regex filter (see :doc:`selection`).
   * - ``--timeout INT``
     - ``300``
     - Seconds to wait for pods to become ready.
   * - ``--dry-run``
     - off
     - Print what would be deployed without actually applying resources.
   * - ``--no-cleanup``
     - off
     - Do not delete Kubernetes resources automatically on deploy failure.
       Useful for debugging — resources remain so you can inspect them.
   * - ``--reupload``
     - off
     - Force re-upload of all files to S3, ignoring the size-based cache.
   * - ``--throw-error``
     - off
     - Abort on the first failure instead of collecting errors.
   * - ``-Y / --yes``
     - off
     - Skip the confirmation prompt.

**Examples**

Deploy a single project::

    mampok deploy ~/mamplans/my-project-mamplan.json

Deploy all projects in a directory::

    mampok deploy ~/mamplans/

Deploy only cellxgene projects::

    mampok deploy ~/mamplans/ -s project:tool:cellxgene

Preview without deploying::

    mampok deploy ~/mamplans/ --dry-run

**Notes**

* Files are only re-uploaded if the S3 object size differs from the local
  file. Use ``--reupload`` to force a fresh upload regardless of size.
* If pod readiness times out, the deploy fails but Kubernetes resources
  are left in place so you can investigate. Use ``--no-cleanup`` intentionally
  if you always want this behavior.

----

.. _cmd-stop:

stop
----

**Synopsis**::

    mampok stop <path> [OPTIONS]

**Description**

Stop one or more running deployments. Removes all Kubernetes resources
(Deployment, Service, Ingress, Secrets) and sets ``deployment.status=false``
in the Mamplan file.

.. important::

   **S3 data is preserved.** The bucket and all uploaded files remain intact
   so you can redeploy later.

**Arguments**

.. list-table::
   :header-rows: 1
   :widths: 20 60

   * - Argument
     - Description
   * - ``<path>``
     - Path to a Mamplan file or directory.

**Options**

.. list-table::
   :header-rows: 1
   :widths: 25 12 45

   * - Option
     - Default
     - Description
   * - ``--config PATH``
     - ``~/.mampok/config.json``
     - Config file path.
   * - ``-s / --selection``
     - —
     - Filter Mamplans.
   * - ``-rs / --regex-select``
     - —
     - Regex filter.
   * - ``--download``
     - off
     - Download S3 data to local disk before stopping. Requires
       ``--output-dir``.
   * - ``-o / --output-dir PATH``
     - —
     - Destination directory for the download (required when
       ``--download`` is used).
   * - ``--throw-error``
     - off
     - Abort on first failure.
   * - ``-Y / --yes``
     - off
     - Skip confirmation prompt.

**Examples**

Stop a single project::

    mampok stop ~/mamplans/my-project-mamplan.json -Y

Download data and then stop::

    mampok stop ~/mamplans/ --download --output-dir ~/downloads/ -Y

----

.. _cmd-redeploy:

redeploy
--------

**Synopsis**::

    mampok redeploy <path> [OPTIONS]

**Description**

Stop and redeploy one or more projects in a single operation. S3 data
persists through the stop/start cycle. Equivalent to running ``mampok stop``
followed by ``mampok deploy``.

**Options**

.. list-table::
   :header-rows: 1
   :widths: 25 12 45

   * - Option
     - Default
     - Description
   * - ``--config PATH``
     - ``~/.mampok/config.json``
     - Config file path.
   * - ``-s / --selection``
     - —
     - Filter Mamplans.
   * - ``-rs / --regex-select``
     - —
     - Regex filter.
   * - ``--timeout INT``
     - ``300``
     - Pod readiness timeout in seconds.
   * - ``--reupload``
     - off
     - Force re-upload of all files to S3.
   * - ``--throw-error``
     - off
     - Abort on first failure.
   * - ``-Y / --yes``
     - off
     - Skip confirmation prompt.

**Examples**

Redeploy a project (e.g. after editing the Mamplan)::

    mampok redeploy ~/mamplans/my-project-mamplan.json -Y

Redeploy with forced file re-upload::

    mampok redeploy ~/mamplans/my-project-mamplan.json --reupload -Y

----

.. _cmd-stop-expired:

stop-expired
------------

**Synopsis**::

    mampok stop-expired <repository> [OPTIONS]

**Description**

Stop all active deployments whose ``deployment.lifetime`` is in the past.
Operates on an entire repository directory. Shows a confirmation table of
affected projects before proceeding.

Safe to use in automated cron jobs with ``-Y``. The exit code is ``1`` if
any project failed to stop (useful for cron monitoring).

**Arguments**

.. list-table::
   :header-rows: 1
   :widths: 20 60

   * - Argument
     - Description
   * - ``<repository>``
     - Path to the Mamplan repository directory.

**Options**

.. list-table::
   :header-rows: 1
   :widths: 25 12 45

   * - Option
     - Default
     - Description
   * - ``--config PATH``
     - ``~/.mampok/config.json``
     - Config file path.
   * - ``--throw-error``
     - off
     - Abort on first failure.
   * - ``-Y / --yes``
     - off
     - Skip confirmation prompt (recommended for cron).

**Example**::

    mampok stop-expired ~/mamplans/ --config ~/.mampok/config.json -Y

----

.. _cmd-list-expiring:

list-expiring
-------------

**Synopsis**::

    mampok list-expiring <repository> [OPTIONS]

**Description**

List all active deployments that will expire within a given time window.
Useful for setting up monitoring or pre-expiry alerts.

**Arguments**

.. list-table::
   :header-rows: 1
   :widths: 20 60

   * - Argument
     - Description
   * - ``<repository>``
     - Path to the Mamplan repository directory.

**Options**

.. list-table::
   :header-rows: 1
   :widths: 25 12 45

   * - Option
     - Default
     - Description
   * - ``--config PATH``
     - ``~/.mampok/config.json``
     - Config file path.
   * - ``--within VALUE``
     - ``7d``
     - Alert window. Relative format: ``7d`` (7 days), ``2w`` (2 weeks),
       ``1m`` (1 month / 30 days).

**Output**

.. code-block:: text

    Project ID              Lifetime                    Days Remaining
    ──────────────────────────────────────────────────────────────────
    my-cellxgene-project    2026-04-24T12:00:00Z        5

**Example**::

    mampok list-expiring ~/mamplans/ --within 14d

----

.. _cmd-edit-mamplan:

edit-mamplan
------------

**Synopsis**::

    mampok edit-mamplan <path> [OPTIONS]

**Description**

Edit one or more fields of a Mamplan file and optionally redeploy. Changes
are shown before applying; use ``-Y`` to skip confirmation.

Accepts a single Mamplan file (not a directory).

**Arguments**

.. list-table::
   :header-rows: 1
   :widths: 20 60

   * - Argument
     - Description
   * - ``<path>``
     - Path to a single Mamplan file.

**Options**

.. list-table::
   :header-rows: 1
   :widths: 30 12 45

   * - Option
     - Default
     - Description
   * - ``-e / --edit section:key:value``
     - —
     - Field to edit (repeatable). Format: ``section:key:value``.
   * - ``--redeploy``
     - off
     - Stop and redeploy the project after saving the changes.
   * - ``--timeout INT``
     - ``300``
     - Pod readiness timeout (used when ``--redeploy`` is set).
   * - ``--throw-error``
     - off
     - Abort on first failure.
   * - ``-Y / --yes``
     - off
     - Skip confirmation prompt.

**Token format**

Fields are specified as ``section:key:value``. The value may contain colons.
Examples:

.. list-table::
   :header-rows: 1
   :widths: 45 40

   * - Token
     - Effect
   * - ``deployment:lifetime:+30d``
     - Extend current lifetime by 30 days
   * - ``deployment:lifetime:+4w``
     - Extend current lifetime by 4 weeks
   * - ``deployment:auth:true``
     - Enable authentication
   * - ``service:owner:alice``
     - Change the owner

.. important::

   The ``+Nd/w/m`` offset for ``deployment:lifetime`` is added to the
   **existing lifetime**, not to today. This means repeatedly renewing a
   project extends it correctly each time.

**Examples**

Renew a project's lifetime by 30 days::

    mampok edit-mamplan my-project-mamplan.json -e deployment:lifetime:+30d -Y

Change multiple fields and redeploy::

    mampok edit-mamplan my-project-mamplan.json \
      -e service:owner:alice \
      -e deployment:auth:true \
      --redeploy -Y

----

.. _cmd-create-mamplan:

create-mamplan
--------------

**Synopsis**::

    mampok create-mamplan --project-id ID --tool TOOL --cluster CLUSTER \
      --owner OWNER --datatype TYPE --output PATH [OPTIONS]

**Description**

Create a new Mamplan JSON file. The ``--project-id``, ``--tool``,
``--cluster``, ``--owner``, and ``--datatype`` options are required (owner
and datatype can be supplied via ``--metadata-file`` instead).

Validates that the specified tool has a matching Mamplate and the cluster
exists in config before writing the file.

**Options**

.. list-table::
   :header-rows: 1
   :widths: 28 12 47

   * - Option
     - Required
     - Description
   * - ``--project-id TEXT``
     - yes
     - Unique project ID. Auto-normalized (lowercase, underscores → hyphens).
   * - ``--tool TEXT``
     - yes
     - Tool name. Must match a Mamplate in ``mamplates_path``.
   * - ``--cluster TEXT``
     - yes
     - Target cluster name. Must exist in config.
   * - ``--output PATH``
     - yes
     - Output file or directory. If directory, filename is auto-generated.
   * - ``--owner TEXT``
     - yes*
     - Project owner username. *Required unless supplied via
       ``--metadata-file``.
   * - ``--datatype TEXT``
     - yes*
     - Data type (repeatable). *Required unless in ``--metadata-file``.
   * - ``--files TEXT``
     - no
     - Files to upload (repeatable).
   * - ``--analyst TEXT``
     - no
     - Analyst usernames (repeatable).
   * - ``--organization TEXT``
     - no
     - Organizations (repeatable).
   * - ``--user TEXT``
     - no
     - Additional user access list (repeatable).
   * - ``--metadata TEXT``
     - no
     - Metadata IDs (repeatable).
   * - ``--metadata-file PATH``
     - no
     - YAML metadata file(s) to populate the service section (repeatable).
       Merged with explicit flags; explicit values take precedence for
       scalar fields.
   * - ``--bucket TEXT``
     - no
     - S3 bucket name. Auto-generated if empty.
   * - ``--auth / --no-auth``
     - no
     - Enable login protection. Default: ``--no-auth``.
   * - ``--custom-url-id TEXT``
     - no
     - Custom URL path segment replacing project-id in the URL.

**Examples**

Minimal creation::

    mampok create-mamplan \
      --project-id mouse-atlas \
      --tool cellxgene \
      --cluster BN \
      --owner jdoe \
      --datatype scRNA-seq \
      --output ~/mamplans/

With metadata file and multiple data files::

    mampok create-mamplan \
      --project-id mouse-atlas \
      --tool cellxgene \
      --cluster BN \
      --metadata-file project_metadata.yaml \
      --files atlas.h5ad \
      --files markers.csv \
      --output ~/mamplans/mouse-atlas-mamplan.json

----

.. _cmd-check-status:

check-status
------------

**Synopsis**::

    mampok check-status <repository> [OPTIONS]

**Description**

Compare the expected state (``deployment.status`` in each Mamplan file)
against the actual state (live Kubernetes resources). Prints a three-column
report.

**Output**

.. code-block:: text

    Project ID              Expected    Actual      Healthy
    ────────────────────────────────────────────────────────
    my-cellxgene-project    active      active      ✓
    old-project             inactive    active      ✗
    new-project             active      missing     ✗

* **Expected** — derived from ``deployment.status`` in the Mamplan file.
* **Actual** — live state from Kubernetes (active = deployment exists and
  has ready pods; missing = deployment not found).
* **Healthy** — ``✓`` when Expected and Actual match; ``✗`` otherwise.

**Arguments**

.. list-table::
   :header-rows: 1
   :widths: 20 60

   * - Argument
     - Description
   * - ``<repository>``
     - Path to the Mamplan repository directory.

**Options**

.. list-table::
   :header-rows: 1
   :widths: 25 12 45

   * - Option
     - Default
     - Description
   * - ``-s / --selection``
     - —
     - Filter Mamplans.
   * - ``-rs / --regex-select``
     - —
     - Regex filter.
   * - ``--throw-error``
     - off
     - Abort on first failure.

**Example**::

    mampok check-status ~/mamplans/ -s deployment:cluster:BN

----

.. _cmd-update-auth:

update-auth
-----------

**Synopsis**::

    mampok update-auth <path> [OPTIONS]

**Description**

Regenerate the Kubernetes auth secret for one or more projects. The new
secret is derived from ``service.organization`` and ``service.user`` in the
Mamplan. If ``"public"`` is in ``service.organization``, the secret is set
for public (unauthenticated) access.

Prints the new token URL after updating.

**Arguments**

.. list-table::
   :header-rows: 1
   :widths: 20 60

   * - Argument
     - Description
   * - ``<path>``
     - Path to a Mamplan file or directory.

**Options**

.. list-table::
   :header-rows: 1
   :widths: 25 12 45

   * - Option
     - Default
     - Description
   * - ``--throw-error``
     - off
     - Abort on first failure.
   * - ``-Y / --yes``
     - off
     - Skip confirmation prompt.

**Example**::

    mampok update-auth ~/mamplans/my-project-mamplan.json -Y

----

.. _cmd-download:

download
--------

**Synopsis**::

    mampok download <path> --output-dir DIR [OPTIONS]

**Description**

Download the persistent S3 data for one or more projects to the local
filesystem. A subdirectory named after the ``project_id`` is created inside
``--output-dir``.

This command downloads ``container_data/`` from S3 (the paths defined in the
Mamplate's ``container_data.paths`` or ``full_bucket_overwrite`` setting). It
does **not** stop the deployment.

**Arguments**

.. list-table::
   :header-rows: 1
   :widths: 20 60

   * - Argument
     - Description
   * - ``<path>``
     - Path to a Mamplan file or directory.

**Options**

.. list-table::
   :header-rows: 1
   :widths: 30 12 45

   * - Option
     - Required
     - Description
   * - ``-o / --output-dir PATH``
     - yes
     - Local destination directory.
   * - ``-s / --selection``
     - no
     - Filter Mamplans.
   * - ``-rs / --regex-select``
     - no
     - Regex filter.
   * - ``--throw-error``
     - no
     - Abort on first failure.
   * - ``-Y / --yes``
     - no
     - Skip confirmation prompt.

**Example**::

    mampok download ~/mamplans/my-project-mamplan.json \
      --output-dir ~/downloads/ -Y

Error Tolerance
---------------

By default, Mampok processes all Mamplans even if one fails. Errors are
collected and a summary is printed at the end. The exit code is ``1`` if any
errors occurred.

Use ``--throw-error`` to abort immediately on the first failure instead.

This behavior applies to all commands that process multiple Mamplans:
``deploy``, ``stop``, ``redeploy``, ``stop-expired``, ``check-status``,
``update-auth``, ``download``.
