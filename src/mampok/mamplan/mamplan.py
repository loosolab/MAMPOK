"""Mamplan — concrete deployment configuration."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import ClassVar

from mampok.mamplan.base import MamplanBase


# Fields with schema defaults that are automatically set by create()
_DEPLOYMENT_DEFAULTS: dict = {
    "status": False,
    "auth": False,
    "random_url_suffix": False,
    "url": "",
}

_SERVICE_DEFAULTS: dict = {
    "download_allowed": False,
}


class Mamplan(MamplanBase):
    """Concrete deployment configuration for a Mampok project.

    Describes which tool, image, resources, expiration, etc.
    Validated against ``mamplan_schema.json``.

    Args:
        data: Mamplan configuration dict.

    Raises:
        jsonschema.ValidationError: If data violates the schema.
    """

    _schema_name: ClassVar[str] = "mamplan_schema.json"
    _schema_cache: ClassVar[dict | None] = None
    _registry: ClassVar[object | None] = None

    def __init__(self, data: dict) -> None:
        """Initialize Mamplan.

        Args:
            data: Mamplan configuration dict.

        Raises:
            jsonschema.ValidationError: If data violates the schema.
        """
        super().__init__(data)

    def _get_auto_filename(self) -> str:
        """Return the auto-generated filename.

        Returns:
            '{project_id}-mamplan.json'
        """
        return f"{self.data['project']['project_id']}-mamplan.json"

    @classmethod
    def read_in(cls, path: Path) -> "Mamplan":
        """Load a Mamplan from a JSON file.

        Args:
            path: Path to the Mamplan file.

        Returns:
            New Mamplan instance.

        Raises:
            FileNotFoundError: If the file does not exist.
            json.JSONDecodeError: If the JSON syntax is invalid.
            jsonschema.ValidationError: If the content violates the schema.
        """
        return super().read_in(path)  # type: ignore[return-value]

    @classmethod
    def create(cls, **kwargs) -> "Mamplan":
        """Factory method for new Mamplans.

        Normalises ``project_id`` (lowercase, ``_`` → ``-``) and fills
        missing optional fields with schema defaults.

        Args:
            **kwargs: Nested sections of the Mamplan:
                project (dict): Required fields: project_id, tool, files, creation_date.
                deployment (dict): Required fields: cluster, lifetime, bucket, url.
                    Optional fields are filled with defaults.
                service (dict): Required fields: analyst, datatype, owner, user, metadata, organization.
                container (dict, optional): Container overrides.
                tags (dict, optional): Free metadata.

        Returns:
            Validated Mamplan instance with normalised fields and defaults.

        Raises:
            jsonschema.ValidationError: If required fields are missing or invalid.
        """
        data = copy.deepcopy(kwargs)

        # normalise project_id: lowercase, _ → -
        if "project" in data and "project_id" in data["project"]:
            pid = data["project"]["project_id"]
            data["project"]["project_id"] = pid.lower().replace("_", "-")

        # Deployment defaults for missing optional fields
        if "deployment" in data:
            for key, default_val in _DEPLOYMENT_DEFAULTS.items():
                data["deployment"].setdefault(key, default_val)

        # Service defaults
        if "service" in data:
            for key, default_val in _SERVICE_DEFAULTS.items():
                data["service"].setdefault(key, default_val)

        return cls(data)

