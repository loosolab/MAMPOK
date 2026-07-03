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

For **scalar fields**, the value at ``mamplan[section][key]`` is compared to
``value`` as a string.

For **list fields**, Mampok checks whether ``value`` is an element of the
list (membership test). This means ``-s service:organization:mpi-bn`` matches
any Mamplan that has ``"mpi-bn"`` anywhere in its ``organization`` list,
regardless of other elements.

The option is repeatable.

.. note::

   Mampok validates selection field paths before filtering. If you reference a
   field that does not exist (e.g. a typo in the key name), the command exits
   immediately with an error message listing the valid fields for that section.

Examples:

.. list-table::
   :header-rows: 1
   :widths: 45 40

   * - Filter
     - Effect
   * - ``-s project:tool:cellxgene``
     - Only Cellxgene projects
   * - ``-s deployment:cluster:MY_CLUSTER``
     - Only projects on cluster MY_CLUSTER
   * - ``-s deployment:status:True``
     - Only currently deployed projects
   * - ``-s deployment:auth:True``
     - Only auth-protected projects
   * - ``-s service:owner:jdoe``
     - Only projects owned by jdoe
   * - ``-s service:organization:mpi-bn``
     - Projects where ``mpi-bn`` is in the organization list

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

    # Only cellxgene projects on cluster MY_CLUSTER
    mampok deploy ~/mamplans/ \
      -s project:tool:cellxgene \
      -s deployment:cluster:MY_CLUSTER

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
     - ``MY_CLUSTER``
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
     - list element
     - ``scRNA-seq``
   * - ``service:organization``
     - list element
     - ``mpi-bn``

List Fields
-----------

When the Mamplan field contains a list (e.g. ``service.organization``,
``service.datatype``), ``-s`` performs a **membership check**: the filter
value must be an element of the list. This is more precise than a string
comparison and works regardless of list order or length.

.. code-block:: bash

    # All projects where mpi-bn is in the organization list
    mampok deploy ~/mamplans/ -s service:organization:mpi-bn

    # All projects with scRNA-seq in the datatype list
    mampok check-status ~/mamplans/ -s service:datatype:scRNA-seq

Use ``-rs`` when you need pattern matching within list elements (e.g. partial
name, case-insensitive)::

    # Projects with any RNA-seq datatype variant
    mampok check-status ~/mamplans/ -rs service:datatype:RNA-seq
