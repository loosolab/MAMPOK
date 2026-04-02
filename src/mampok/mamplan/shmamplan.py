"""SHMamplan — Software Hub Deployment-Konfiguration (minimales Format)."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import ClassVar

from mampok.mamplan.base import MamplanBase


class SHMamplan(MamplanBase):
    """Software Hub deployment configuration.

    Minimales persistentes Format für Self-Service Tool-Deployments.
    Wird gegen ``shmamplan_schema.json`` validiert.

    Im Gegensatz zu ``Mamplan`` enthält SHMamplan keine Analyse-Metadaten
    (datatype, analyst, metadata, organization). Folgende Werte sind implizit:
    - deployment.auth = True (immer auth-geschützt)
    - deployment.generate_url = True (URL wird immer generiert)
    - service.user = [] (kein Sharing; Owner-Zugriff via deployment auth secret)
    - service.organization = [] (kein Sharing)

    Dateibenennung auf Disk: ``{project_id}-shmamplan.json``

    Args:
        data: SHMamplan-Konfigurations-Dict.

    Raises:
        jsonschema.ValidationError: Wenn data das Schema verletzt.
    """

    _schema_name: ClassVar[str] = "shmamplan_schema.json"
    _schema_cache: ClassVar[dict | None] = None
    _registry: ClassVar[object | None] = None

    @property
    def is_expired(self) -> bool:
        """True wenn deployment.status=True und deployment.lifetime abgelaufen.

        Returns:
            True wenn das Deployment aktiv und abgelaufen ist.
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
            '{project_id}-shmamplan.json'
        """
        return f"{self.data['project']['project_id']}-shmamplan.json"

    @classmethod
    def create(cls, **kwargs) -> "SHMamplan":
        """Factory-Methode für neue SHMamplans.

        Normalisiert ``project_id`` (lowercase, ``_`` → ``-``) und füllt
        fehlende optionale Felder mit SH-Defaults.

        Args:
            **kwargs: Sections des SHMamplans:
                project (dict): Pflichtfelder: project_id, tool.
                deployment (dict): Pflichtfelder: cluster, bucket, lifetime.
                    Optionale Felder werden mit SH-Defaults gefüllt.
                service (dict): Pflichtfelder: owner.
                container (dict, optional): Container-Overrides.

        Returns:
            Validierte SHMamplan-Instanz mit normalisierten Feldern und Defaults.

        Raises:
            jsonschema.ValidationError: Wenn Pflichtfelder fehlen oder ungültig sind.
        """
        data = copy.deepcopy(kwargs)

        # project_id normalisieren: lowercase, _ → -
        if "project" in data and "project_id" in data["project"]:
            pid = data["project"]["project_id"]
            data["project"]["project_id"] = pid.lower().replace("_", "-")

        # project.files: immer leere Liste für SH (kein S3-Upload)
        data.setdefault("project", {})
        data["project"].setdefault("files", [])

        # deployment defaults
        data.setdefault("deployment", {})
        data["deployment"].setdefault("status", False)
        data["deployment"].setdefault("url", "")
        data["deployment"].setdefault("auth", True)
        data["deployment"].setdefault("generate_url", True)
        data["deployment"].setdefault("random_url_suffix", False)

        return cls(data)

    @classmethod
    def read_in(cls, path: "Path") -> "SHMamplan":
        """Lädt einen SHMamplan aus einer JSON-Datei.

        Args:
            path: Pfad zur SHMamplan-Datei.

        Returns:
            Neue SHMamplan-Instanz.

        Raises:
            FileNotFoundError: Wenn die Datei nicht existiert.
            json.JSONDecodeError: Wenn die JSON-Syntax ungültig ist.
            jsonschema.ValidationError: Wenn der Inhalt das Schema verletzt.
        """
        instance = super().read_in(path)
        # Pipeline-Defaults nach dem Laden sicherstellen
        instance.data["project"].setdefault("files", [])
        instance.data["deployment"].setdefault("status", False)
        instance.data["deployment"].setdefault("url", "")
        instance.data["deployment"].setdefault("auth", True)
        instance.data["deployment"].setdefault("generate_url", True)
        instance.data["deployment"].setdefault("random_url_suffix", False)
        return instance  # type: ignore[return-value]
