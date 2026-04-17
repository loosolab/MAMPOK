API Reference
=============

Auto-generated reference documentation for the Mampok Python package.

.. note::

   For usage examples and explanations, see :doc:`python_api`.
   This page contains the raw autodoc output.

Python API Interface
--------------------

.. autoclass:: mampok.interfaces.api.API
   :members:
   :undoc-members:
   :show-inheritance:

Core Orchestrator
-----------------

.. autoclass:: mampok.mampok.mampok.Mampok
   :members:
   :undoc-members:
   :show-inheritance:

Configuration
-------------

.. autoclass:: mampok.config.config.MampokConfig
   :members:
   :undoc-members:
   :show-inheritance:

.. autoclass:: mampok.config.config.ClusterConfig
   :members:
   :undoc-members:
   :show-inheritance:

.. autoclass:: mampok.config.config.S3Config
   :members:
   :undoc-members:
   :show-inheritance:

.. autoclass:: mampok.config.config.AuthProxyConfig
   :members:
   :undoc-members:
   :show-inheritance:

Mamplan and Mamplate Classes
-----------------------------

.. autoclass:: mampok.mamplan.mamplan.Mamplan
   :members:
   :undoc-members:
   :show-inheritance:

.. autoclass:: mampok.mamplan.mamplate.Mamplate
   :members:
   :undoc-members:
   :show-inheritance:

.. autoclass:: mampok.mamplan.shmamplan.SHMamplan
   :members:
   :undoc-members:
   :show-inheritance:

.. autoclass:: mampok.mamplan.base.MamplanBase
   :members:
   :undoc-members:
   :show-inheritance:

Deployment Config
-----------------

.. autoclass:: mampok.kubernetes.config.DeploymentConfig
   :members:
   :undoc-members:
   :show-inheritance:

CLI Helpers
-----------

.. automodule:: mampok.interfaces.cli
   :members: load_mamplans, load_mamplates, apply_selection, run_with_error_tolerance
   :undoc-members:
