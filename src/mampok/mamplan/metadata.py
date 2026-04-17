"""Parsing of project metadata files (YAML) for Mamplan generation."""

from pathlib import Path

import yaml


def parse_metadata_files(paths: list[Path]) -> dict:
    """Read YAML metadata files and return a merged service dict.

    Extracts from each file:
    - ``project.owner.ldap_name`` → ``owner`` (from first file)
    - ``project.nerd.ldap_name`` → ``analyst`` (from all files, no fallback)
    - ``project.owner.department`` → ``organization`` (from all files)
    - ``technical_details.techniques[].technique[]`` → ``datatype`` (from all files)
    - ``project.id`` → ``metadata`` (from all files)

    When multiple files are given, lists are combined (deduplicated, order preserved).
    ``owner`` comes from the first file that contains this field.

    Args:
        paths: List of paths to YAML metadata files.

    Returns:
        Dict with keys ``owner``, ``analyst``, ``organization``,
        ``datatype``, ``metadata``. Missing fields result in empty strings
        or empty lists respectively.
    """
    result: dict = {
        "owner": "",
        "analyst": [],
        "organization": [],
        "datatype": [],
        "metadata": [],
    }

    for path in paths:
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)

        if not isinstance(data, dict):
            continue

        project = data.get("project", {}) or {}

        # owner: first file with a valid value wins
        if not result["owner"]:
            owner_block = project.get("owner", {}) or {}
            ldap = owner_block.get("ldap_name", "")
            if ldap:
                result["owner"] = ldap

        # organization: project.owner.department
        owner_block = project.get("owner", {}) or {}
        dept = owner_block.get("department", "")
        if dept:
            result["organization"] = _merge_unique(result["organization"], [dept])

        # analyst: project.nerd[].ldap_name – no fallback to owner
        nerd_list = project.get("nerd") or []
        nerd_ldaps = [n["ldap_name"] for n in nerd_list if isinstance(n, dict) and n.get("ldap_name")]
        result["analyst"] = _merge_unique(result["analyst"], nerd_ldaps)

        # metadata: project.id
        project_id = project.get("id", "")
        if project_id:
            result["metadata"] = _merge_unique(result["metadata"], [str(project_id)])

        # datatype: technical_details.techniques[].technique[]
        tech_details = data.get("technical_details", {}) or {}
        for entry in tech_details.get("techniques", []) or []:
            for technique in entry.get("technique", []) or []:
                if technique:
                    result["datatype"] = _merge_unique(result["datatype"], [str(technique)])

    return result


def _merge_unique(base: list, additions: list) -> list:
    """Combine two lists without duplicates, preserving order.

    Args:
        base: Starting list.
        additions: Elements to add.

    Returns:
        New list with all elements from ``base`` followed by elements
        from ``additions`` that were not already in ``base``.
    """
    seen = set(base)
    result = list(base)
    for item in additions:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result
