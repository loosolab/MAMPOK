"""Mamplan — konkrete Deployment-Konfiguration."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import ClassVar

from mampok.mamplan.base import MamplanBase


# Felder mit Schema-Defaults die bei create() automatisch gesetzt werden
_DEPLOYMENT_DEFAULTS: dict = {
    "status": False,
    "auth": False,
    "random_url_suffix": False,
}

_SERVICE_DEFAULTS: dict = {
    "download_allowed": False,
}


class Mamplan(MamplanBase):
    """Konkrete Deployment-Konfiguration für ein Mampok-Projekt.

    Beschreibt welches Tool, welches Image, welche Ressourcen, Expiration, etc.
    Wird gegen ``mamplan_schema.json`` validiert.

    Args:
        data: Mamplan-Konfigurations-Dict.

    Raises:
        jsonschema.ValidationError: Wenn data das Schema verletzt.
    """

    _schema_name: ClassVar[str] = "mamplan_schema.json"
    _schema_cache: ClassVar[dict | None] = None
    _registry: ClassVar[object | None] = None

    def __init__(self, data: dict) -> None:
        """Initialisiert Mamplan.

        Args:
            data: Mamplan-Konfigurations-Dict.

        Raises:
            jsonschema.ValidationError: Wenn data das Schema verletzt.
        """
        super().__init__(data)

    def _get_auto_filename(self) -> str:
        """Gibt den auto-generierten Dateinamen zurück.

        Returns:
            '{project_id}-mamplan.json'
        """
        return f"{self.data['project']['project_id']}-mamplan.json"

    @classmethod
    def read_in(cls, path: Path) -> "Mamplan":
        """Lädt einen Mamplan aus einer JSON-Datei.

        Args:
            path: Pfad zur Mamplan-Datei.

        Returns:
            Neue Mamplan-Instanz.

        Raises:
            FileNotFoundError: Wenn die Datei nicht existiert.
            json.JSONDecodeError: Wenn die JSON-Syntax ungültig ist.
            jsonschema.ValidationError: Wenn der Inhalt das Schema verletzt.
        """
        return super().read_in(path)  # type: ignore[return-value]

    @classmethod
    def create(cls, **kwargs) -> "Mamplan":
        """Factory-Methode für neue Mamplans.

        Normalisiert ``project_id`` (lowercase, ``_`` → ``-``) und füllt
        fehlende optionale Felder mit Schema-Defaults.

        Args:
            **kwargs: Verschachtelte Sections des Mamplans:
                project (dict): Pflichtfelder: project_id, tool, files, creation_date.
                deployment (dict): Pflichtfelder: cluster, lifetime, bucket, url.
                    Optionale Felder werden mit Defaults gefüllt.
                service (dict): Pflichtfelder: analyst, datatype, owner, user, metadata, organization.
                container (dict, optional): Container-Overrides.
                tags (dict, optional): Freie Metadaten.

        Returns:
            Validierte Mamplan-Instanz mit normalisierten Feldern und Defaults.

        Raises:
            jsonschema.ValidationError: Wenn Pflichtfelder fehlen oder ungültig sind.
        """
        data = copy.deepcopy(kwargs)

        # project_id normalisieren: lowercase, _ → -
        if "project" in data and "project_id" in data["project"]:
            pid = data["project"]["project_id"]
            data["project"]["project_id"] = pid.lower().replace("_", "-")

        # Deployment-Defaults für fehlende optionale Felder
        if "deployment" in data:
            for key, default_val in _DEPLOYMENT_DEFAULTS.items():
                data["deployment"].setdefault(key, default_val)

        # Service-Defaults
        if "service" in data:
            for key, default_val in _SERVICE_DEFAULTS.items():
                data["service"].setdefault(key, default_val)

        return cls(data)

