"""Parsing von Projekt-Metadaten-Files (YAML) für die Mamplan-Generierung."""

from pathlib import Path

import yaml


def parse_metadata_files(paths: list[Path]) -> dict:
    """Liest YAML-Metadaten-Files und gibt einen gemergten service-Dict zurück.

    Extrahiert aus jedem File:
    - ``project.owner.ldap_name`` → ``owner`` (aus erstem File)
    - ``project.nerd.ldap_name`` → ``analyst`` (aus allen Files, kein Fallback)
    - ``project.owner.department`` → ``organization`` (aus allen Files)
    - ``technical_details.techniques[].technique[]`` → ``datatype`` (aus allen Files)
    - ``project.id`` → ``metadata`` (aus allen Files)

    Bei mehreren Files werden Listen kombiniert (dedupliziert, Reihenfolge erhalten).
    ``owner`` stammt aus dem ersten File, das dieses Feld enthält.

    Args:
        paths: Liste von Pfaden zu YAML-Metadaten-Files.

    Returns:
        Dict mit den Schlüsseln ``owner``, ``analyst``, ``organization``,
        ``datatype``, ``metadata``. Fehlende Felder ergeben leere Strings
        bzw. leere Listen.
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

        # owner: erstes File mit gültigem Wert gewinnt
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

        # analyst: project.nerd[].ldap_name – kein Fallback auf owner
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
    """Kombiniert zwei Listen ohne Duplikate, erhält die Reihenfolge.

    Args:
        base: Ausgangsliste.
        additions: Hinzuzufügende Elemente.

    Returns:
        Neue Liste mit allen Elementen aus ``base`` gefolgt von Elementen
        aus ``additions``, die noch nicht in ``base`` enthalten waren.
    """
    seen = set(base)
    result = list(base)
    for item in additions:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result
