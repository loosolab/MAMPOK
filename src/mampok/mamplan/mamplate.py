"""Mamplate — Template mit Container-Blueprint-Informationen."""

from __future__ import annotations

from pathlib import Path

from mampok.mamplan.base import MamplanBase


class Mamplate(MamplanBase):
    """Template mit allen Informationen über den zu erzeugenden Container.

    Enthält Defaults und container-spezifische Konfiguration (Image, Resources,
    Ports, Env-Variablen etc.). Wird gegen `mamplate_schema.json` validiert.

    Ein Mamplan referenziert ein Mamplate über das `tool`-Feld.

    Args:
        mamplate: Mamplate-Konfigurations-Dict.
    """

    def __init__(self, mamplate: dict) -> None:
        """Initialisiert Mamplate und lädt das zugehörige JSON-Schema.

        Args:
            mamplate: Mamplate-Konfigurations-Dict.

        Raises:
            jsonschema.ValidationError: Wenn mamplate das Schema verletzt.
        """
        raise NotImplementedError

    @classmethod
    def read_in(cls, path: Path) -> "Mamplate":
        """Lädt ein Mamplate aus einer JSON- oder YAML-Datei.

        Args:
            path: Pfad zur Mamplate-Datei.

        Returns:
            Neue Mamplate-Instanz.
        """
        raise NotImplementedError

    def _get_schema_name(self) -> str:
        """Gibt den Dateinamen des Mamplate-Schemas zurück.

        Returns:
            'mamplate_schema.json'
        """
        raise NotImplementedError
