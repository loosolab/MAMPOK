"""Mamplate — template with container blueprint information."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import ClassVar

from mampok.mamplan.base import MamplanBase


class Mamplate(MamplanBase):
    """Template with all information about the container to be created.

    Contains defaults and container-specific configuration (image, resources,
    ports, env variables, etc.). Validated against ``mamplate_schema.json``.

    A Mamplan references a Mamplate via the ``tool`` field.

    Args:
        data: Mamplate configuration dict.

    Raises:
        jsonschema.ValidationError: If data violates the schema.
    """

    _schema_name: ClassVar[str] = "mamplate_schema.json"
    _schema_cache: ClassVar[dict | None] = None
    _registry: ClassVar[object | None] = None

    def __init__(self, data: dict) -> None:
        """Initialize Mamplate.

        Args:
            data: Mamplate configuration dict.

        Raises:
            jsonschema.ValidationError: If data violates the schema.
        """
        super().__init__(data)

    def _get_auto_filename(self) -> str:
        """Return the auto-generated filename.

        Returns:
            '{tool}-mamplate.json'
        """
        return f"{self.data['tool']}-mamplate.json"

    @classmethod
    def read_in(cls, path: Path) -> "Mamplate":
        """Load a Mamplate from a JSON file.

        Args:
            path: Path to the Mamplate file.

        Returns:
            New Mamplate instance.

        Raises:
            FileNotFoundError: If the file does not exist.
            json.JSONDecodeError: If the JSON syntax is invalid.
            jsonschema.ValidationError: If the content violates the schema.
        """
        return super().read_in(path)  # type: ignore[return-value]

    @classmethod
    def create(cls, **kwargs) -> "Mamplate":
        """Factory method for new Mamplates.

        No normalisation — tool, image, containertype, and resources
        are direct required fields.

        Args:
            **kwargs: Mamplate fields (tool, image, containertype, resources, ports, etc.).

        Returns:
            Validated Mamplate instance.

        Raises:
            jsonschema.ValidationError: If required fields are missing or invalid.
        """
        return cls(copy.deepcopy(kwargs))
