"""MamplanBase — abstrakte Basisklasse für Mamplan und Mamplate."""

from __future__ import annotations

import importlib.resources
import json
from abc import ABC, abstractmethod
from pathlib import Path


class MamplanBase(ABC):
    """Abstrakte Basisklasse für Mamplan und Mamplate.

    Verwaltet ein Konfigurations-Dict und validiert es gegen ein JSON-Schema.
    Konkrete Subklassen laden ihr Schema aus dem Package-Data-Verzeichnis.

    Args:
        mamplan: Konfigurations-Dict (Mamplan oder Mamplate).
        schema: Geladenes JSON-Schema-Dict zur Validation.
    """

    def __init__(self, mamplan: dict, schema: dict) -> None:
        """Initialisiert MamplanBase.

        Args:
            mamplan: Konfigurations-Dict.
            schema: Geladenes JSON-Schema-Dict.
        """
        raise NotImplementedError

    def check_schema(self) -> bool:
        """Validiert das Konfigurations-Dict gegen das JSON-Schema.

        Returns:
            True wenn valide.

        Raises:
            jsonschema.ValidationError: Wenn die Konfiguration ungültig ist,
                mit sprechender Fehlermeldung.
        """
        raise NotImplementedError

    @classmethod
    @abstractmethod
    def read_in(cls, path: Path) -> "MamplanBase":
        """Lädt eine Konfiguration aus einer JSON- oder YAML-Datei.

        Args:
            path: Pfad zur Konfigurationsdatei.

        Returns:
            Neue Instanz der konkreten Subklasse.
        """
        raise NotImplementedError

    def write(self, path: Path) -> None:
        """Schreibt die Konfiguration als YAML-Datei.

        Args:
            path: Zielpfad. Wenn ein Verzeichnis, wird der Dateiname auto-generiert.
        """
        raise NotImplementedError

    def edit(self, **kwargs) -> None:
        """Aktualisiert Felder im Konfigurations-Dict und re-validiert.

        Args:
            **kwargs: Felder und neue Werte. Verschachtelte Keys können als
                dot-notation übergeben werden (z.B. deployment__status=True).

        Raises:
            jsonschema.ValidationError: Wenn das Ergebnis das Schema verletzt.
        """
        raise NotImplementedError

    @abstractmethod
    def _get_schema_name(self) -> str:
        """Gibt den Dateinamen des JSON-Schemas zurück.

        Returns:
            Dateiname (z.B. 'mamplan_schema.json').
        """
        raise NotImplementedError
