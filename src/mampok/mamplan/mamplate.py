"""Mamplate — Template mit Container-Blueprint-Informationen."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import ClassVar

from mampok.mamplan.base import MamplanBase


class Mamplate(MamplanBase):
    """Template mit allen Informationen über den zu erzeugenden Container.

    Enthält Defaults und container-spezifische Konfiguration (Image, Resources,
    Ports, Env-Variablen etc.). Wird gegen ``mamplate_schema.json`` validiert.

    Ein Mamplan referenziert ein Mamplate über das ``tool``-Feld.

    Args:
        data: Mamplate-Konfigurations-Dict.

    Raises:
        jsonschema.ValidationError: Wenn data das Schema verletzt.
    """

    _schema_name: ClassVar[str] = "mamplate_schema.json"
    _schema_cache: ClassVar[dict | None] = None
    _registry: ClassVar[object | None] = None

    def __init__(self, data: dict) -> None:
        """Initialisiert Mamplate.

        Args:
            data: Mamplate-Konfigurations-Dict.

        Raises:
            jsonschema.ValidationError: Wenn data das Schema verletzt.
        """
        super().__init__(data)

    def _get_auto_filename(self) -> str:
        """Gibt den auto-generierten Dateinamen zurück.

        Returns:
            '{tool}-mamplate.json'
        """
        return f"{self.data['tool']}-mamplate.json"

    @classmethod
    def read_in(cls, path: Path) -> "Mamplate":
        """Lädt ein Mamplate aus einer JSON-Datei.

        Args:
            path: Pfad zur Mamplate-Datei.

        Returns:
            Neue Mamplate-Instanz.

        Raises:
            FileNotFoundError: Wenn die Datei nicht existiert.
            json.JSONDecodeError: Wenn die JSON-Syntax ungültig ist.
            jsonschema.ValidationError: Wenn der Inhalt das Schema verletzt.
        """
        return super().read_in(path)  # type: ignore[return-value]

    @classmethod
    def create(cls, **kwargs) -> "Mamplate":
        """Factory-Methode für neue Mamplates.

        Keine Normalisierung — tool, image, containertype und resources
        sind direkte Pflichtfelder.

        Args:
            **kwargs: Mamplate-Felder (tool, image, containertype, resources, ports, etc.).

        Returns:
            Validierte Mamplate-Instanz.

        Raises:
            jsonschema.ValidationError: Wenn Pflichtfelder fehlen oder ungültig sind.
        """
        return cls(copy.deepcopy(kwargs))
