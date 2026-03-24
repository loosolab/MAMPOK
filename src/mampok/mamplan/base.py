"""MamplanBase — abstrakte Basisklasse für Mamplan und Mamplate."""

from __future__ import annotations

import copy
import importlib.resources
import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import ClassVar

import jsonschema
from referencing import Registry, Resource


class MamplanBase(ABC):
    """Abstrakte Basisklasse für Mamplan und Mamplate.

    Verwaltet ein Konfigurations-Dict und validiert es gegen ein JSON-Schema.
    Das Schema wird per Subklasse gecacht (einmal laden, für alle Instanzen).

    Subklassen müssen setzen:
        _schema_name (ClassVar[str]): Dateiname des JSON-Schemas.
        _schema_cache (ClassVar[dict | None]): Auf None initialisieren (eigener Cache).
    """

    _schema_name: ClassVar[str]
    _schema_cache: ClassVar[dict | None] = None
    _registry: ClassVar[Registry | None] = None

    def __init__(self, data: dict) -> None:
        """Initialisiert MamplanBase.

        Lädt das Schema aus dem Package-Data-Verzeichnis (gecacht pro Subklasse)
        und validiert sofort gegen das Schema.

        Args:
            data: Konfigurations-Dict (Mamplan oder Mamplate).

        Raises:
            jsonschema.ValidationError: Wenn data das Schema verletzt.
        """
        cls = type(self)
        if cls.__dict__.get("_schema_cache") is None:
            schema_ref = (
                importlib.resources.files("mampok.mamplan")
                .joinpath("schemas")
                .joinpath(cls._schema_name)
            )
            with schema_ref.open("r", encoding="utf-8") as f:
                cls._schema_cache = json.load(f)
        self.data = data
        self.schema: dict = cls._schema_cache  # type: ignore[assignment]
        self.check_schema()

    def check_schema(self) -> bool:
        """Validiert das Konfigurations-Dict gegen das JSON-Schema.

        Verwendet eine ``referencing``-Registry, damit $ref-Verweise zwischen
        Schemas (mamplan_schema.json → mamplate_schema.json) korrekt aufgelöst werden.

        Returns:
            True wenn valide.

        Raises:
            jsonschema.ValidationError: Wenn die Konfiguration ungültig ist.
        """
        cls = type(self)
        if cls.__dict__.get("_registry") is None:
            cls._registry = _build_registry()
        jsonschema.validate(self.data, self.schema, registry=cls._registry)
        return True

    @classmethod
    def read_in(cls, path: Path) -> "MamplanBase":
        """Lädt eine Konfiguration aus einer JSON-Datei.

        Args:
            path: Pfad zur JSON-Datei.

        Returns:
            Neue validierte Instanz der konkreten Subklasse.

        Raises:
            FileNotFoundError: Wenn die Datei nicht existiert.
            json.JSONDecodeError: Wenn die JSON-Syntax ungültig ist.
            jsonschema.ValidationError: Wenn der Inhalt das Schema verletzt.
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Datei nicht gefunden: {path}")
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return cls(data)

    def write(self, path: Path) -> None:
        """Schreibt die Konfiguration als JSON-Datei (indent=2).

        Args:
            path: Zielpfad. Wenn ein Verzeichnis, wird der Dateiname
                auto-generiert via _get_auto_filename().
        """
        path = Path(path)
        if path.is_dir():
            path = path / self._get_auto_filename()
        with path.open("w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)

    def edit(self, **kwargs) -> None:
        """Aktualisiert Felder im Konfigurations-Dict und re-validiert atomar.

        Verschachtelte Keys via ``__``-Notation (z.B. ``deployment__status=True``).
        Bei Schema-Verletzung wird das Dict auf den alten Zustand zurückgerollt.

        Args:
            **kwargs: Felder und neue Werte. Verschachtelte Keys als ``a__b__c``.

        Raises:
            jsonschema.ValidationError: Wenn das Ergebnis das Schema verletzt.
                Das Dict bleibt in diesem Fall unverändert (Rollback).
        """
        backup = copy.deepcopy(self.data)
        try:
            for key, value in kwargs.items():
                parts = key.split("__")
                target = self.data
                for part in parts[:-1]:
                    target = target[part]
                target[parts[-1]] = value
            self.check_schema()
        except jsonschema.ValidationError:
            self.data = backup
            raise

    @abstractmethod
    def _get_auto_filename(self) -> str:
        """Gibt den auto-generierten Dateinamen zurück (wenn write() ein Verzeichnis erhält).

        Returns:
            Dateiname, z.B. 'my-project-mamplan.json' oder 'cellxgene-mamplate.json'.
        """


def _build_registry() -> Registry:
    """Baut eine referencing-Registry mit beiden Schemas für $ref-Auflösung.

    Wird pro Subklasse einmalig erstellt und in _registry gecacht.

    Returns:
        Registry mit mamplan_schema.json und mamplate_schema.json.
    """
    schemas_pkg = importlib.resources.files("mampok.mamplan").joinpath("schemas")
    resources = []
    for schema_filename in ("mamplan_schema.json", "mamplate_schema.json"):
        schema_ref = schemas_pkg.joinpath(schema_filename)
        with schema_ref.open("r", encoding="utf-8") as f:
            schema_dict = json.load(f)
        resources.append((schema_filename, Resource.from_contents(schema_dict)))
    return Registry().with_resources(resources)
