"""Mamplan — konkrete Deployment-Konfiguration."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from pathlib import Path
from typing import ClassVar

from mampok.mamplan.base import MamplanBase


# Felder mit Schema-Defaults die bei create() automatisch gesetzt werden
_DEPLOYMENT_DEFAULTS: dict = {
    "status": False,
    "auth": False,
    "generate_url": True,
    "random_url_suffix": False,
}

_SERVICE_DEFAULTS: dict = {
    "download_allowed": False,
}

# Dict-Felder: bei merge_container_config deep-mergen statt ersetzen
_DICT_FIELDS = {"resources", "volume", "downloadpaths", "annotation", "readinessProbe"}
# Listen-Felder: bei merge_container_config komplett ersetzen
_LIST_FIELDS = {"args", "command", "env"}


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

    @property
    def is_expired(self) -> bool:
        """True if deployment.status is True and deployment.lifetime has passed.

        Returns:
            True if the deployment is active and its lifetime is in the past.
        """
        deployment = self.data["deployment"]
        if not deployment.get("status", False):
            return False
        lifetime = datetime.fromisoformat(deployment["lifetime"])
        if lifetime.tzinfo is None:
            lifetime = lifetime.replace(tzinfo=timezone.utc)
        return lifetime < datetime.now(timezone.utc)

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

    def merge_container_config(  # type: ignore[name-defined]
        self,
        mamplate: "Mamplate",
        init_mamplates: "list[Mamplate] | None" = None,
    ) -> dict:
        """Merged die Container-Konfiguration von Mamplate mit Mamplan-Overrides.

        Mamplan-Werte haben Vorrang. Dicts werden gemergt, Listen ersetzt.

        Args:
            mamplate: Das zugehörige Mamplate mit Container-Blueprint.
            init_mamplates: Optionale Liste von Mamplates für custom Init-Container.

        Returns:
            Dict mit 'main'-Key (und optional 'init'-Key als Liste), bereit für
            den Mampok-Orchestrator zur Umwandlung in DeploymentConfig.
            Beispiel: {'main': {tool, image, ports, resources, ...}, 'init': [{...}, ...]}
        """
        mamplan_container = self.data.get("container", {})

        main_base = copy.deepcopy(mamplate.data)
        main_overrides = mamplan_container.get("main", {})
        merged_main = _deep_merge_container(main_base, main_overrides)

        result: dict = {"main": merged_main}

        # Init-Container: nur wenn Mamplan container.init oder project.init_container hat
        init_overrides = mamplan_container.get("init", {})
        resolved_init_mamplates = init_mamplates or []
        if resolved_init_mamplates or init_overrides:
            init_list = []
            for init_mt in resolved_init_mamplates:
                base = copy.deepcopy(init_mt.data)
                init_list.append(_deep_merge_container(base, init_overrides))
            if not resolved_init_mamplates and init_overrides:
                init_list.append(_deep_merge_container({}, init_overrides))
            result["init"] = init_list

        return result


def _deep_merge_container(base: dict, overrides: dict) -> dict:
    """Merged override-Dict in base-Dict gemäß Container-Merge-Regeln.

    Dicts werden rekursiv gemergt, Listen vom Override ersetzt, Skalare ersetzt.

    Args:
        base: Basis-Dict (Mamplate-Daten).
        overrides: Override-Dict (Mamplan container.main oder container.init).

    Returns:
        Gemergtes Dict.
    """
    result = copy.deepcopy(base)
    for key, value in overrides.items():
        if key in _LIST_FIELDS:
            result[key] = copy.deepcopy(value)
        elif key in _DICT_FIELDS and isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge_dicts(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _merge_dicts(base: dict, override: dict) -> dict:
    """Rekursiver Dict-Merge: override-Werte überschreiben base-Werte."""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge_dicts(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result
