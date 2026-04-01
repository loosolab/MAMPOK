"""MamplanBase — abstrakte Basisklasse für Mamplan und Mamplate."""

from __future__ import annotations

import copy
import importlib.resources
import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

import jsonschema
from referencing import Registry, Resource

if TYPE_CHECKING:
    from mampok.mamplan.mamplate import Mamplate

# Dict-Felder: bei merge_container_config deep-mergen statt ersetzen
_DICT_FIELDS = {"resources", "volume", "downloadpaths", "annotation", "readinessProbe"}
# Listen-Felder: bei merge_container_config komplett ersetzen
_LIST_FIELDS = {"args", "command", "env"}

logger = logging.getLogger(__name__)


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
        self.source_path: Path | None = None
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
        logger.debug("read_in: %s", path)
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        instance = cls(data)
        instance.source_path = path
        return instance

    def write(self, path: Path) -> None:
        """Schreibt die Konfiguration als JSON-Datei (indent=2).

        Args:
            path: Zielpfad. Wenn ein Verzeichnis, wird der Dateiname
                auto-generiert via _get_auto_filename().
        """
        path = Path(path)
        if path.is_dir():
            path = path / self._get_auto_filename()
        logger.debug("write: %s", path)
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
        logger.debug("edit: %s", kwargs)
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

    def merge_container_config(
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
