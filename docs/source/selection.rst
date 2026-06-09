Selection and Filtering
=======================

Many Mampok commands accept ``-s`` and ``-rs`` options to filter which
Mamplans are affected. This page explains how filtering works.

How It Works
------------

When you pass filter options, Mampok applies them **after** loading all
Mamplans from the path argument. Only Mamplans that match **all** filters
are processed; the rest are silently skipped.

Multiple filters are AND-combined — a Mamplan must pass every filter to be
included.

Exact Match (``-s / --selection``)
------------------------------------

**Syntax**::

    -s section:key:value

The value at ``mamplan[section][key]`` is compared to ``value`` as a string.
The option is repeatable.

Examples:

.. list-table::
   :header-rows: 1
   :widths: 45 40

   * - Filter
     - Effect
   * - ``-s project:tool:cellxgene``
     - Only Cellxgene projects
   * - ``-s deployment:cluster:BN``
     - Only projects on cluster BN
   * - ``-s deployment:status:True``
     - Only currently deployed projects
   * - ``-s deployment:auth:True``
     - Only auth-protected projects
   * - ``-s service:owner:jdoe``
     - Only projects owned by jdoe

Note that boolean values must be written as ``True`` or ``False`` (Python
string representation).

Regex Match (``-rs / --regex-select``)
-----------------------------------------

**Syntax**::

    -rs section:key:pattern

Uses Python's ``re.search()`` — the pattern is matched anywhere in the
string representation of the field value. The match is **not anchored** to
the start or end. The option is repeatable.

Examples:

.. list-table::
   :header-rows: 1
   :widths: 45 40

   * - Filter
     - Effect
   * - ``-rs project:project_id:^mouse-``
     - Projects whose ID starts with ``mouse-``
   * - ``-rs project:tool:jupyter``
     - Projects using any Jupyter variant
   * - ``-rs service:owner:^(alice|bob)$``
     - Projects owned by alice or bob

Combining Filters
-----------------

Multiple ``-s`` and ``-rs`` flags can be combined freely — all must match::

    # Only cellxgene projects on cluster BN
    mampok deploy ~/mamplans/ \
      -s project:tool:cellxgene \
      -s deployment:cluster:BN

    # Deployed projects owned by anyone except jdoe
    mampok check-status ~/mamplans/ \
      -s deployment:status:True \
      -rs service:owner:^(?!jdoe$)

Quick Reference
---------------

Common selectable paths:

.. list-table::
   :header-rows: 1
   :widths: 30 15 35

   * - Path
     - Type
     - Example value
   * - ``project:tool``
     - string
     - ``cellxgene``
   * - ``project:project_id``
     - string
     - ``my-project``
   * - ``deployment:cluster``
     - string
     - ``BN``
   * - ``deployment:status``
     - bool as string
     - ``True`` or ``False``
   * - ``deployment:auth``
     - bool as string
     - ``True`` or ``False``
   * - ``service:owner``
     - string
     - ``jdoe``
   * - ``service:datatype``
     - list as string
     - ``['scRNA-seq']``
   * - ``service:organization``
     - list as string
     - ``['mpi-bn']``

List Fields
-----------

When the Mamplan field contains a list (e.g. ``service.organization``,
``service.datatype``), the comparison is against Python's ``str()``
representation of the list — for example, ``"['mpi-bn', 'mpi-iem']"``.

Use ``-rs`` with a simple substring pattern for list fields::

    # All projects belonging to mpi-bn (even if they have other orgs too)
    mampok deploy ~/mamplans/ -rs service:organization:mpi-bn

    # All projects with scRNA-seq data
    mampok check-status ~/mamplans/ -rs service:datatype:scRNA-seq
