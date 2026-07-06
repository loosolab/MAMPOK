Configuration
=============

Mampok reads its configuration from a JSON file. The path must be passed
explicitly to every command via the ``--config PATH`` option; there is no
default location.

.. figure:: images/config_structure.png
   :align: center
   :width: 90%

   Structure of the config.json file.

Minimal Example
---------------

.. code-block:: json

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
      "mamplates_path": "/home/user/mamplates",
      "lifetime_days": 30,
      "mampok_version": ">=2.0.0,<3.0.0"
    }

File Location
-------------

The config path has no default and must be passed explicitly to every command::

    mampok deploy ~/mamplans/ --config /path/to/config.json

Field Reference
---------------

Top-level fields
~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 22 10 10 45

   * - Field
     - Type
     - Required
     - Description
   * - ``mamplates_path``
     - string
     - yes
     - Path to the directory containing ``*-mamplate.json`` files.
   * - ``lifetime_days``
     - integer
     - yes
     - Default deployment lifetime in days. Written to
       ``deployment.lifetime`` at deploy time as ``now + lifetime_days``.
   * - ``mampok_version``
     - string
     - yes
     - `PEP 440 version specifier
       <https://peps.python.org/pep-0440/#version-specifiers>`_ for the
       required Mampok version (e.g. ``">=2.0.0,<3.0.0"``). Mampok checks
       this on startup and raises an error if the installed version does not
       match. See :ref:`version-pinning`.
   * - ``default_cluster``
     - string
     - no
     - Fallback cluster name when a Mamplan does not specify one. Primarily
       useful for the Python API (``create_sh_mamplan``).

``cluster`` section
~~~~~~~~~~~~~~~~~~~

The ``cluster`` key contains a dictionary of named cluster profiles. You can
have as many as you need. The key (e.g. ``"MY_CLUSTER"``) must match the
``deployment.cluster`` field in your Mamplans.

.. code-block:: json

    "cluster": {
      "MY_CLUSTER": {
        "host": "ingress.example.com",
        "namespace": "mampok",
        "kubeconfig_path": "/home/user/.kube/my-cluster-config",
        "ingress_class": "nginx"
      },
      "MY_CLUSTER_2": {
        "host": "ingress2.example.com",
        "namespace": "mampok-public",
        "kubeconfig_path": "/home/user/.kube/my-cluster-2-config",
        "ingress_class": "nginx"
      }
    }

.. list-table::
   :header-rows: 1
   :widths: 22 10 10 45

   * - Field
     - Type
     - Required
     - Description
   * - ``host``
     - string
     - yes
     - Ingress host domain for this cluster (e.g.
       ``"ingress.example.com"``). Used to construct deployment URLs.
   * - ``namespace``
     - string
     - yes
     - Kubernetes namespace where resources are created.
   * - ``kubeconfig_path``
     - string
     - yes
     - Absolute path to the kubeconfig file for this cluster.
   * - ``ingress_class``
     - string
     - no
     - Kubernetes Ingress class name (e.g. ``"nginx"``).
   * - ``annotations``
     - object
     - no
     - Extra Ingress annotations applied to every deployment on this cluster.
   * - ``dnsissuer``
     - string
     - no
     - cert-manager issuer name for TLS certificate generation.
   * - ``dnssecret``
     - string
     - no
     - DNS secret name for ACME challenge.

``s3`` section
~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 22 10 10 45

   * - Field
     - Type
     - Required
     - Description
   * - ``endpoint``
     - string
     - yes
     - S3-compatible endpoint URL (e.g. ``"https://s3.example.com"``).
       Works with AWS S3, MinIO, Ceph, and other S3-compatible stores.
   * - ``access_key``
     - string
     - yes
     - S3 access key ID.
   * - ``secret_key``
     - string
     - yes
     - S3 secret access key. See security note below.
   * - ``secretname``
     - string
     - yes
     - Name of the Kubernetes Secret that holds the S3 credentials. This
       secret must exist in the cluster namespace before deploying.
   * - ``prefix``
     - string
     - no
     - Prefix prepended to auto-generated bucket names:
       ``{prefix}-{project_id}-{tool}``. Can be empty.

.. warning::

   ``secret_key`` is stored in plain text in the config file. Restrict access
   with appropriate file permissions:

   * **Personal config** (only you should read it)::

       chmod 600 /path/to/config.json

   * **Shared config** (a group of users should read it, but not modify it)::

       chmod 640 /path/to/config.json
       chgrp <your-group> /path/to/config.json

``auth_proxy`` section (optional)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The ``auth_proxy`` section is required only if you deploy projects with
``deployment.auth: true``. It configures the Gatekeeper sidecar container
that handles JWT-based authentication.

.. code-block:: json

    "auth_proxy": {
      "auth_proxy_image": "registry.example.com/gatekeeper:latest",
      "proxy_port": 8080,
      "auth_annotations": {
        "nginx.ingress.kubernetes.io/auth-url": "http://auth.example.com/verify"
      },
      "image_pull_secrets": ["registry-pull-secret"],
      "project_auth_path": "/opt/mampok/project_auth.json"
    }

.. list-table::
   :header-rows: 1
   :widths: 22 10 10 45

   * - Field
     - Type
     - Required
     - Description
   * - ``auth_proxy_image``
     - string
     - yes
     - Docker image for the Gatekeeper sidecar container.
   * - ``proxy_port``
     - integer
     - no
     - Port on which the Gatekeeper listens. Default: ``8080``.
   * - ``auth_annotations``
     - object
     - no
     - Extra Ingress annotations applied when ``auth: true``. Merged with
       cluster-level ``annotations``.
   * - ``image_pull_secrets``
     - array of strings
     - no
     - Pull secrets needed to fetch the auth proxy image.
   * - ``project_auth_path``
     - string
     - no
     - Path to the ``project_auth.json`` file used by the Gatekeeper
       container to look up valid users.

Multiple Clusters
-----------------

You can define any number of cluster profiles in the ``cluster`` dict. Each
Mamplan's ``deployment.cluster`` field must match one of these keys::

    # Mamplan references "MY_CLUSTER_2":
    "deployment": {
      "cluster": "MY_CLUSTER_2",
      ...
    }

    # config.json defines "MY_CLUSTER_2":
    "cluster": {
      "MY_CLUSTER": { ... },
      "MY_CLUSTER_2": { ... }
    }

.. _version-pinning:

Version Pinning
---------------

The ``mampok_version`` field specifies which version(s) of Mampok are
compatible with this config file. Mampok validates this on startup and raises
an error if the installed version does not satisfy the specifier.

Example values:

.. list-table::
   :header-rows: 1
   :widths: 30 55

   * - Value
     - Meaning
   * - ``">=2.0.0,<3.0.0"``
     - Any 2.x release (recommended for production)
   * - ``"==2.1.0"``
     - Exact version only
   * - ``">=2.0.0"``
     - Any version 2.0.0 or newer

.. warning::

   If the installed Mampok version does not match the specifier, Mampok
   raises a ``ValueError`` and exits. Update the specifier or install a
   compatible Mampok version.
