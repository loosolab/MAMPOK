"""Mamplan — konkrete Deployment-Konfiguration."""

from __future__ import annotations

from pathlib import Path

from mampok.mamplan.base import MamplanBase


class Mamplan(MamplanBase):
    """Konkrete Deployment-Konfiguration für ein Mampok-Projekt.

    Beschreibt welches Tool, welches Image, welche Ressourcen, Expiration, etc.
    Wird gegen `mamplan_schema.json` validiert.

    Args:
        mamplan: Mamplan-Konfigurations-Dict.
    """

    def __init__(self, mamplan: dict) -> None:
        """Initialisiert Mamplan und lädt das zugehörige JSON-Schema.

        Args:
            mamplan: Mamplan-Konfigurations-Dict.

        Raises:
            jsonschema.ValidationError: Wenn mamplan das Schema verletzt.
        """
        raise NotImplementedError

    @classmethod
    def read_in(cls, path: Path) -> "Mamplan":
        """Lädt einen Mamplan aus einer JSON- oder YAML-Datei.

        Args:
            path: Pfad zur Mamplan-Datei.

        Returns:
            Neue Mamplan-Instanz.
        """
        raise NotImplementedError

    def _get_schema_name(self) -> str:
        """Gibt den Dateinamen des Mamplan-Schemas zurück.

        Returns:
            'mamplan_schema.json'
        """
        raise NotImplementedError
