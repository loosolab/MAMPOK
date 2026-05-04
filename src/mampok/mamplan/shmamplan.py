"""SHMamplan — Software Hub deployment configuration (minimal format)."""

from __future__ import annotations

import copy
from typing import ClassVar

from mampok.mamplan.base import MamplanBase


class SHMamplan(MamplanBase):
    """Software Hub deployment configuration.

    Minimal persistent format for self-service tool deployments.
    Validated against ``shmamplan_schema.json``.

    Unlike ``Mamplan``, SHMamplan contains no analysis metadata
    (datatype, analyst, metadata, organization). The following values are implicit:
    - deployment.auth = True (always auth-protected)
    - service.user = [] (no sharing; owner access via deployment auth secret)
    - service.organization = [] (no sharing)

    Filename on disk: ``{project_id}-shmamplan.json``

    Args:
        data: SHMamplan configuration dict.

    Raises:
        jsonschema.ValidationError: If data violates the schema.
    """

    _schema_name: ClassVar[str] = "shmamplan_schema.json"
    _schema_cache: ClassVar[dict | None] = None
    _registry: ClassVar[object | None] = None

    @property
    def auth(self) -> bool:
        """Always True — SHMamplans are always auth-protected.

        Returns:
            True
        """
        return True

    def _get_auto_filename(self) -> str:
        """Return the auto-generated filename.

        Returns:
            '{project_id}-shmamplan.json'
        """
        return f"{self.data['project']['project_id']}-shmamplan.json"

    @classmethod
    def create(cls, **kwargs) -> "SHMamplan":
        """Factory method for new SHMamplans.

        Normalises ``project_id`` (lowercase, ``_`` → ``-``) and fills
        missing optional fields with SH defaults.

        Args:
            **kwargs: Sections of the SHMamplan:
                project (dict): Required fields: project_id, tool.
                deployment (dict): Required fields: cluster, bucket, lifetime.
                    Optional fields are filled with SH defaults.
                service (dict): Required fields: owner.
                container (dict, optional): Container overrides.

        Returns:
            Validated SHMamplan instance with normalised fields and defaults.

        Raises:
            jsonschema.ValidationError: If required fields are missing or invalid.
        """
        data = copy.deepcopy(kwargs)

        # normalise project_id: lowercase, _ → -
        if "project" in data and "project_id" in data["project"]:
            pid = data["project"]["project_id"]
            data["project"]["project_id"] = pid.lower().replace("_", "-")

        # deployment defaults
        data.setdefault("deployment", {})
        data["deployment"].setdefault("status", False)
        data["deployment"].setdefault("url", "")

        return cls(data)

    @classmethod
    def read_in(cls, path: "Path") -> "SHMamplan":
        """Load a SHMamplan from a JSON file.

        Args:
            path: Path to the SHMamplan file.

        Returns:
            New SHMamplan instance.

        Raises:
            FileNotFoundError: If the file does not exist.
            json.JSONDecodeError: If the JSON syntax is invalid.
            jsonschema.ValidationError: If the content violates the schema.
        """
        instance = super().read_in(path)
        # ensure pipeline defaults after loading
        instance.data["deployment"].setdefault("status", False)
        return instance  # type: ignore[return-value]
