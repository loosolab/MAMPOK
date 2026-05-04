"""MamplanBase — abstract base class for Mamplan and Mamplate."""

from __future__ import annotations

import copy
import importlib.resources
import json
import logging
import re
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

import jsonschema
from referencing import Registry, Resource

if TYPE_CHECKING:
    from mampok.mamplan.mamplate import Mamplate

# Dict fields: deep-merge in merge_container_config instead of replacing
_DICT_FIELDS = {"resources", "volume", "downloadpaths", "annotation", "readinessProbe"}
# List fields: fully replace in merge_container_config
_LIST_FIELDS = {"args", "command", "env"}


def parse_lifetime(value: str) -> datetime:
    """Parse an ISO 8601 lifetime string to a timezone-aware UTC datetime.

    Any timezone offset (e.g. +02:00) is replaced with UTC while keeping the
    date and time numbers unchanged — so the calendar date the user intended
    is preserved.  Naive strings (no tz info) are treated as UTC.

    Examples::

        "2024-12-31T00:00:00+02:00" → datetime(2024, 12, 31, 0, 0, tzinfo=utc)
        "2024-12-31T00:00:00Z"      → datetime(2024, 12, 31, 0, 0, tzinfo=utc)
        "2024-12-31T00:00:00"       → datetime(2024, 12, 31, 0, 0, tzinfo=utc)
    """
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt.replace(tzinfo=timezone.utc)

_TEMPLATE_PATTERN = re.compile(r"__([a-zA-Z0-9_.]+)__")


def _resolve_path(data: dict, path: str) -> str:
    """Resolve a dot-separated path in a dict and return a string."""
    keys = path.split(".")
    current = data
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            raise ValueError(f"Template path '{path}' not found in Mamplan")
        current = current[key]
    if isinstance(current, list):
        return ",".join(str(v) for v in current)
    if isinstance(current, bool):
        return "true" if current else "false"
    if current is None:
        raise ValueError(f"Template path '{path}' is None")
    return str(current)


def _apply_template_substitution(merged: dict, mamplan_data: dict) -> dict:
    """Replace __key.subkey__ tokens in args, command, and env values."""
    def replace_token(match, _data=mamplan_data):
        return _resolve_path(_data, match.group(1))

    for field in ("args", "command"):
        if field not in merged:
            continue
        merged[field] = [
            _TEMPLATE_PATTERN.sub(replace_token, item)
            for item in merged[field]
        ]

    if "env" in merged:
        merged["env"] = [
            {**entry, "value": _TEMPLATE_PATTERN.sub(replace_token, entry["value"])}
            if "value" in entry
            else entry
            for entry in merged["env"]
        ]

    return merged

logger = logging.getLogger(__name__)


class MamplanBase(ABC):
    """Abstract base class for Mamplan and Mamplate.

    Manages a configuration dict and validates it against a JSON schema.
    The schema is cached per subclass (loaded once, shared across all instances).

    Subclasses must set:
        _schema_name (ClassVar[str]): Filename of the JSON schema.
        _schema_cache (ClassVar[dict | None]): Initialize to None (own cache).
    """

    _schema_name: ClassVar[str]
    _schema_cache: ClassVar[dict | None] = None
    _registry: ClassVar[Registry | None] = None

    def __init__(self, data: dict) -> None:
        """Initialize MamplanBase.

        Loads the schema from the package data directory (cached per subclass)
        and immediately validates against the schema.

        Args:
            data: Configuration dict (Mamplan or Mamplate).

        Raises:
            jsonschema.ValidationError: If data violates the schema.
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
        """Validate the configuration dict against the JSON schema.

        Uses a ``referencing`` registry so that $ref references between
        schemas (mamplan_schema.json → mamplate_schema.json) are resolved correctly.

        Returns:
            True if valid.

        Raises:
            jsonschema.ValidationError: If the configuration is invalid.
        """
        cls = type(self)
        if cls.__dict__.get("_registry") is None:
            cls._registry = _build_registry()
        jsonschema.validate(self.data, self.schema, registry=cls._registry)
        return True

    @classmethod
    def read_in(cls, path: Path) -> "MamplanBase":
        """Load a configuration from a JSON file.

        Args:
            path: Path to the JSON file.

        Returns:
            New validated instance of the concrete subclass.

        Raises:
            FileNotFoundError: If the file does not exist.
            json.JSONDecodeError: If the JSON syntax is invalid.
            jsonschema.ValidationError: If the content violates the schema.
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        logger.debug("read_in: %s", path)
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        instance = cls(data)
        instance.source_path = path
        return instance

    def write(self, path: Path) -> None:
        """Write the configuration as a JSON file (indent=2).

        Args:
            path: Target path. If a directory, the filename is
                auto-generated via _get_auto_filename().
        """
        path = Path(path)
        if path.is_dir():
            path = path / self._get_auto_filename()
        logger.debug("write: %s", path)
        with path.open("w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)

    def edit(self, **kwargs) -> None:
        """Update fields in the configuration dict and re-validate atomically.

        Nested keys via ``__`` notation (e.g. ``deployment__status=True``).
        On schema violation, the dict is rolled back to its previous state.

        Args:
            **kwargs: Fields and new values. Nested keys as ``a__b__c``.

        Raises:
            jsonschema.ValidationError: If the result violates the schema.
                The dict remains unchanged in this case (rollback).
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
        """Return the auto-generated filename (when write() receives a directory).

        Returns:
            Filename, e.g. 'my-project-mamplan.json' or 'cellxgene-mamplate.json'.
        """

    @property
    def auth(self) -> bool:
        """True if the deployment is auth-protected.

        Returns:
            deployment.auth from the configuration dict.
        """
        return self.data["deployment"]["auth"]

    @property
    def is_expired(self) -> bool:
        """True if deployment.status=True and deployment.lifetime has passed.

        Returns:
            True if the deployment is active and expired.
        """
        deployment = self.data["deployment"]
        if not deployment.get("status", False):
            return False
        return parse_lifetime(deployment["lifetime"]) < datetime.now(timezone.utc)

    def merge_container_config(
        self,
        mamplate: "Mamplate",
        mamplan_data: dict,
        init_mamplates: "list[Mamplate] | None" = None,
    ) -> dict:
        """Merge the container configuration from Mamplate with Mamplan overrides.

        Mamplan values take precedence. Dicts are merged, lists are replaced.
        Template tokens of the form __key.subkey__ in args/command are replaced
        with the corresponding values from mamplan_data.

        Args:
            mamplate: The associated Mamplate with the container blueprint.
            mamplan_data: The full Mamplan dict for template substitution.
            init_mamplates: Optional list of Mamplates for custom init containers.

        Returns:
            Dict with a 'main' key (and optionally an 'init' key as a list), ready for
            the Mampok orchestrator to convert into a DeploymentConfig.
            Example: {'main': {tool, image, ports, resources, ...}, 'init': [{...}, ...]}
        """
        mamplan_container = self.data.get("container", {})

        main_base = copy.deepcopy(mamplate.data)
        main_overrides = mamplan_container.get("main", {})
        merged_main = _deep_merge_container(main_base, main_overrides)

        result: dict = {"main": _apply_template_substitution(merged_main, mamplan_data)}

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
    """Merge override dict into base dict according to container merge rules.

    Dicts are merged recursively, lists are replaced by the override, scalars are replaced.

    Args:
        base: Base dict (Mamplate data).
        overrides: Override dict (Mamplan container.main or container.init).

    Returns:
        Merged dict.
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
    """Recursive dict merge: override values overwrite base values."""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge_dicts(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _build_registry() -> Registry:
    """Build a referencing Registry with both schemas for $ref resolution.

    Created once per subclass and cached in _registry.

    Returns:
        Registry with mamplan_schema.json and mamplate_schema.json.
    """
    schemas_pkg = importlib.resources.files("mampok.mamplan").joinpath("schemas")
    resources = []
    for schema_filename in ("mamplan_schema.json", "mamplate_schema.json"):
        schema_ref = schemas_pkg.joinpath(schema_filename)
        with schema_ref.open("r", encoding="utf-8") as f:
            schema_dict = json.load(f)
        resources.append((schema_filename, Resource.from_contents(schema_dict)))
    return Registry().with_resources(resources)
