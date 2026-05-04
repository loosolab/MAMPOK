"""Python API — programmatic interface for other tools."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from mampok.config.config import MampokConfig
from mampok.interfaces.cli import create_mampok_instance
from mampok.kubernetes.builder import _sync_sidecar_subpath
from mampok.mamplan.base import MamplanBase, parse_lifetime
from mampok.mamplan.mamplan import Mamplan
from mampok.mamplan.mamplate import Mamplate
from mampok.mamplan.metadata import _merge_unique, parse_metadata_files
from mampok.mamplan.shmamplan import SHMamplan


def _parse_iso_to_datetime(value: str) -> datetime | None:
    """ISO 8601 UTC string → timezone-aware datetime. Empty/None → None."""
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class API:
    """Importable Python API for programmatic Mampok access.

    For each operation, one Mampok instance is created per Mamplan
    and the operation is delegated.

    Unlike the CLI:
    - No interactive user input
    - deploy() / redeploy() return progress iterators
    - Explicit edit methods (edit_lifetime, edit_sharing) instead of string parsing
    - No error tolerance — exceptions propagate directly

    Args:
        config_path: Path to the MampokConfig JSON file.
    """

    def __init__(self, config_path: Path) -> None:
        """Initialize API with path to the config file.

        Args:
            config_path: Path to the MampokConfig JSON file.
        """
        self.config_path = Path(config_path)

    # ---------------------------------------------------------------------------
    # Private helpers
    # ---------------------------------------------------------------------------

    def _load_config(self) -> MampokConfig:
        """Load MampokConfig from config_path."""
        return MampokConfig.from_file(self.config_path)

    def _load_mamplan(self, path: Path) -> MamplanBase:
        """Load a Mamplan or SHMamplan from a file.

        Detects Software Hub mamplans by the ``-shmamplan.json`` filename suffix
        and loads them as ``SHMamplan`` instances. All other files are loaded
        as standard ``Mamplan`` instances.

        Args:
            path: Path to a Mamplan or SHMamplan JSON file.

        Returns:
            Loaded and validated MamplanBase instance (Mamplan or SHMamplan).

        Raises:
            FileNotFoundError: If path does not exist.
            IsADirectoryError: If path is a directory.
        """
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Path not found: {p}")
        if p.is_dir():
            raise IsADirectoryError(f"mamplan_path must be a file, got directory: {p}")
        if p.name.endswith("-shmamplan.json"):
            return SHMamplan.read_in(p)
        return Mamplan.read_in(p)

    def _load_mamplates(self, config: MampokConfig) -> dict[str, Mamplate]:
        """Load all Mamplates from config.mamplates_path.

        Args:
            config: Loaded MampokConfig.

        Returns:
            Dict mapping tool name to Mamplate instance.
        """
        result: dict[str, Mamplate] = {}
        for f in sorted(config.mamplates_path.glob("*-mamplate.json")):
            m = Mamplate.read_in(f)
            result[m.data["tool"]] = m
        return result

    def _load(self, path: Path) -> tuple[MamplanBase, dict[str, Mamplate], MampokConfig]:
        """Load a Mamplan or SHMamplan, Mamplates and MampokConfig in one call.

        Args:
            path: Path to a Mamplan or SHMamplan file.

        Returns:
            Tuple of (mamplan, mamplates, config).
        """
        config = self._load_config()
        mamplan = self._load_mamplan(path)
        mamplates = self._load_mamplates(config)
        return mamplan, mamplates, config

    # ---------------------------------------------------------------------------
    # core operations
    # ---------------------------------------------------------------------------

    def deploy(self, mamplan_path: Path, timeout: int = 900, cleanup: bool = True) -> Iterator[dict]:
        """Deploy a project to Kubernetes.

        Yields progress dicts for each stage of the deployment:
        init → s3_bucket → s3_upload (per file) → k8s_apply (per resource)
        → k8s_ready (per readiness event) → done (with selfservice data).

        On failure during K8s steps, already-created resources are automatically
        deleted (unless cleanup=False).

        Args:
            mamplan_path: Path to the Mamplan file.
            timeout: Maximum seconds to wait for pods to become ready.
            cleanup: If True, K8s resources are deleted automatically on failure.

        Yields:
            Progress dicts, final one contains "selfservice" key with url and auth info.

        Raises:
            FileNotFoundError: If mamplan_path does not exist.
            IsADirectoryError: If mamplan_path is a directory.
            KeyError: If the tool has no matching Mamplate.
            TimeoutError: If pods are not ready within the timeout.
        """
        mamplan, mamplates, config = self._load(mamplan_path)
        mampok = create_mampok_instance(config, mamplan, mamplates)
        yield from mampok.deploy(config, timeout=timeout, cleanup=cleanup)
        mamplan.write(mamplan.source_path)

    def stop(self, mamplan_path: Path) -> Iterator[dict]:
        """Stop a deployment (removes K8s resources, S3 bucket remains).

        Yields progress dicts from the stop sequence (S3 sync + K8s resource deletion).
        Caller must iterate to drive execution.

        Args:
            mamplan_path: Path to the Mamplan file.

        Yields:
            Progress dicts from Mampok.stop().

        Raises:
            FileNotFoundError: If mamplan_path does not exist.
            IsADirectoryError: If mamplan_path is a directory.
        """
        mamplan, mamplates, config = self._load(mamplan_path)
        mampok = create_mampok_instance(config, mamplan, mamplates)
        yield from mampok.stop(config)
        mamplan.write(mamplan.source_path)

    def redeploy(self, mamplan_path: Path) -> Iterator[dict]:
        """Stop and redeploy a project.

        Yields stop confirmation, then all deploy progress dicts.

        Args:
            mamplan_path: Path to the Mamplan file.

        Yields:
            {"stage": "stop", "status": "done", "project_id": str}
            followed by all yields from deploy().

        Raises:
            FileNotFoundError: If mamplan_path does not exist.
            IsADirectoryError: If mamplan_path is a directory.
        """
        mamplan, mamplates, config = self._load(mamplan_path)
        mampok = create_mampok_instance(config, mamplan, mamplates)
        yield from mampok.stop(config)
        yield {
            "stage": "stop",
            "status": "done",
            "project_id": mamplan.data["project"]["project_id"],
        }
        yield from mampok.deploy(config)
        mamplan.write(mamplan.source_path)

    def create_mamplan(self, output: Path, metadata_files: list[Path] | None = None, **kwargs) -> None:
        """Create a new Mamplan from keyword arguments and write it to disk.

        Args:
            output: Output path (file or directory). If directory, filename
                    is auto-generated as {project_id}-mamplan.json.
            metadata_files: Optional list of YAML metadata file paths. Extracted
                fields (owner, analyst, organization, datatype, metadata) are
                merged into the service section. Explicit values in ``kwargs``
                take precedence for scalar fields; list fields are merged.
            **kwargs: Mamplan sections (project, deployment, service, etc.).

        Raises:
            jsonschema.ValidationError: If the provided data violates the schema.
            ValueError: If the tool has no matching Mamplate or the cluster is not in the config.
        """
        if metadata_files:
            yaml_svc = parse_metadata_files(metadata_files)
            svc = kwargs.get("service", {})
            kwargs["service"] = {
                **svc,
                "owner": svc.get("owner") or yaml_svc.get("owner", ""),
                "analyst": _merge_unique(svc.get("analyst", []), yaml_svc.get("analyst", [])),
                "organization": _merge_unique(svc.get("organization", []), yaml_svc.get("organization", [])),
                "datatype": _merge_unique(svc.get("datatype", []), yaml_svc.get("datatype", [])),
                "metadata": _merge_unique(svc.get("metadata", []), yaml_svc.get("metadata", [])),
            }

        tool = kwargs.get("project", {}).get("tool")
        cluster = kwargs.get("deployment", {}).get("cluster")
        config = self._load_config()
        mamplates = self._load_mamplates(config)
        if tool and tool not in mamplates:
            raise ValueError(
                f"No mamplate for tool '{tool}'. Available: {sorted(mamplates)}"
            )
        if cluster and cluster not in config.clusters:
            raise ValueError(
                f"Cluster '{cluster}' not found in config. Available: {sorted(config.clusters)}"
            )

        # Default lifetime to now() as placeholder — deploy will overwrite with now + lifetime_days
        from datetime import datetime, timezone
        deployment = kwargs.get("deployment", {})
        if "lifetime" not in deployment:
            deployment["lifetime"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            kwargs["deployment"] = deployment

        mamplan = Mamplan.create(**kwargs)
        mamplan.write(Path(output))

    def edit_mamplan(self, mamplan_path: Path, **kwargs) -> None:
        """Edit a Mamplan using double-underscore nested key notation.

        Generic fallback for field updates. For specific use cases, prefer
        edit_lifetime() or edit_sharing() which include side-effect handling.

        Args:
            mamplan_path: Path to the Mamplan file.
            **kwargs: Fields to update using ``section__key`` notation.
                      Example: deployment__lifetime="2025-12-31T00:00:00"

        Raises:
            jsonschema.ValidationError: If the result violates the schema (atomic rollback).
        """
        mamplan_path = Path(mamplan_path)
        mamplan = Mamplan.read_in(mamplan_path)
        mamplan.edit(**kwargs)
        mamplan.write(mamplan_path)

    def list_expiring(self, repository: Path, within_days: int = 7) -> list[dict]:
        """Return active deployments expiring within ``within_days`` days.

        Args:
            repository: Path to the Mamplan repository directory.
            within_days: Number of days to look ahead. Default: 7.

        Returns:
            List of dicts: [{"project_id": str, "lifetime": str, "days_remaining": int}, ...]
        """
        from datetime import timedelta
        from mampok.interfaces.cli import _mamplan_expiry_info, load_mamplans

        within = timedelta(days=within_days)
        return [r for m in load_mamplans(Path(repository)) if (r := _mamplan_expiry_info(m, within))]

    # ---------------------------------------------------------------------------
    # API-specific edit methods
    # ---------------------------------------------------------------------------

    def edit_lifetime(self, mamplan_path: Path, lifetime: str) -> None:
        """Update the deployment lifetime of a Mamplan.

        Args:
            mamplan_path: Path to the Mamplan file.
            lifetime: New lifetime value (ISO 8601 datetime string,
                      e.g. "2025-12-31T00:00:00").

        Raises:
            FileNotFoundError: If mamplan_path does not exist.
            jsonschema.ValidationError: If the value violates the schema.
        """
        mamplan_path = Path(mamplan_path)
        mamplan = self._load_mamplan(mamplan_path)
        normalized = parse_lifetime(lifetime).strftime("%Y-%m-%dT%H:%M:%SZ")
        mamplan.edit(deployment__lifetime=normalized)
        mamplan.write(mamplan_path)

    def edit_sharing(
        self,
        mamplan_path: Path,
        users: list[str] | None = None,
        organizations: list[str] | None = None,
    ) -> Iterator[dict]:
        """Update the sharing config of a Mamplan and optionally refresh the auth secret.

        Two-phase operation:
        1. Update service.user / service.organization and save to disk.
        2. If auth=True and status=True (running deployment): update the K8s
           auth secret to reflect the new user list. On failure, the Mamplan
           is rolled back to its original state before the exception is re-raised.

        Args:
            mamplan_path: Path to the Mamplan file.
            users: New user list for service.user (replaces existing).
            organizations: New organization list for service.organization (replaces existing).

        Yields:
            {"stage": "edit_sharing", "status": "saved", "project_id": str}
            {"stage": "auth_secret", "status": "updated"} (if auth+status=True)
            {"stage": "auth_secret", "status": "failed", "reason": str} (on K8s error)
            {"stage": "rollback", "status": "done"} (after rollback on failure)

        Raises:
            FileNotFoundError: If mamplan_path does not exist.
            jsonschema.ValidationError: If the new values violate the schema (no file written).
            Exception: Re-raised K8s exception after rollback if auth secret update fails.
        """
        mamplan_path = Path(mamplan_path)
        mamplan = Mamplan.read_in(mamplan_path)
        original_data = copy.deepcopy(mamplan.data)
        project_id = mamplan.data["project"]["project_id"]

        # Phase 1: update service (MamplanBase.edit() is atomic — rolls back on ValidationError)
        if users is not None:
            mamplan.edit(service__user=users)
        if organizations is not None:
            mamplan.edit(service__organization=organizations)
        mamplan.write(mamplan_path)
        yield {"stage": "edit_sharing", "status": "saved", "project_id": project_id}

        # Phase 2: auth secret update (only for active, auth-protected deployments)
        auth = mamplan.auth
        status = mamplan.data["deployment"].get("status", False)

        if auth and status:
            try:
                config = self._load_config()
                mamplates = self._load_mamplates(config)
                mampok = create_mampok_instance(config, mamplan, mamplates)
                auth_users = (users or []) + (organizations or [])
                token_url = mampok.update_auth_secret(auth_users, config)
                yield {"stage": "auth_secret", "status": "updated", "token_url": token_url}
            except Exception as exc:
                yield {"stage": "auth_secret", "status": "failed", "reason": str(exc)}
                # Rollback: restore Mamplan to original state
                mamplan.data = original_data
                mamplan.write(mamplan_path)
                yield {"stage": "rollback", "status": "done"}
                raise

    # ---------------------------------------------------------------------------
    # API-specific additional methods
    # ---------------------------------------------------------------------------

    def project_info(
        self,
        mamplan_path: Path,
    ) -> dict:
        """Return project metadata and K8s status for a Mamplan.

        Args:
            mamplan_path: Path to the Mamplan file.

        Returns:
            Dict with structure:
            {"projects": {project_id: {flat MongoDB-compatible dict}}}
            Keys correspond directly to MongoDB field names per mampok_v2 schema.
            Date fields (creation_date, lifetime) are timezone-aware datetime objects.

        Raises:
            FileNotFoundError: If mamplan_path does not exist.
            IsADirectoryError: If mamplan_path is a directory.
        """
        mamplan, mamplates, config = self._load(mamplan_path)
        mampok = create_mampok_instance(config, mamplan, mamplates)
        k8s_status = mampok.check_status(config)
        project_id = mamplan.data["project"]["project_id"]
        p = mamplan.data["project"]
        d = mamplan.data["deployment"]
        s = mamplan.data["service"]
        tags = mamplan.data.get("tags", {})
        tool = p["tool"]
        mamplate = mamplates.get(tool)
        tool_displayname = mamplate.data.get("toolDisplayname", tool) if mamplate else tool
        cd_raw_paths = mamplate.data.get("container_data", {}).get("paths", []) if mamplate else []
        projects: dict = {
            project_id: {
                # project section
                "project_id":    p["project_id"],
                "tool":          tool,
                "toolDisplayname": tool_displayname,
                "files":         p.get("files", []),
                "creation_date": _parse_iso_to_datetime(p.get("creation_date", "")),
                "project_size":  p.get("project_size"),
                # deployment section
                "cluster":          d["cluster"],
                "status":           k8s_status["actually_deployed"],
                "auth":             d.get("auth", False),
                "bucket":           d.get("bucket", ""),
                "url":              d.get("url", ""),
                "lifetime":         _parse_iso_to_datetime(d.get("lifetime", "")),
                # service section
                "owner":            s["owner"],
                "analyst":          s.get("analyst", []),
                "organization":     s.get("organization", []),
                "datatype":         s.get("datatype", []),
                "metadata":         s.get("metadata", []),
                "download_allowed": s.get("download_allowed", False),
                "user":             s.get("user", []),
                # S3 subpaths under container_data/ derived from mamplate container_data.paths
                "container_data_paths": [_sync_sidecar_subpath(cp) for cp in cd_raw_paths],
                # free tags (gse, pubmedid, etc.) – user/organization not duplicated
                **{k: v for k, v in tags.items() if k not in ("user", "organization")},
            }
        }
        return {"projects": projects}

    def create_sh_mamplan(
        self,
        output: Path,
        username: str,
        tool: str,
        bucket: str,
        cluster: str | None = None,
        lifetime: str | None = None,
    ) -> str:
        """Create a Software Hub mamplan and write it to disk.

        Validates input against shmamplan_schema.json and writes a
        ``{project_id}-shmamplan.json`` file. auth=True is implicit — it is set
        automatically and not required as an argument.

        Args:
            output: Output path (file or directory). If directory, filename is
                    auto-generated as ``{project_id}-shmamplan.json``.
            username: Username of the container owner.
            tool: Mampok tool name (must exist as mamplate).
            bucket: S3 bucket name for user data.
            cluster: Target cluster identifier. If None, uses config.default_cluster.
            lifetime: ISO 8601 expiry datetime. If None, uses config default
                      (now + lifetime_days).

        Returns:
            Normalized project_id string (e.g. "alice-cellxgene").

        Raises:
            ValueError: If cluster is not specified and no default_cluster in config,
                        or if tool not in mamplates, or if cluster not in config.
            jsonschema.ValidationError: If input violates shmamplan_schema.json.
        """
        from datetime import datetime, timedelta, timezone

        config = self._load_config()

        if cluster is None:
            cluster = config.default_cluster
            if cluster is None:
                raise ValueError(
                    "No cluster specified and no default_cluster configured. "
                    "Pass cluster explicitly or set default_cluster in the config."
                )

        mamplates = self._load_mamplates(config)
        if tool not in mamplates:
            raise ValueError(
                f"No mamplate for tool '{tool}'. Available: {sorted(mamplates)}"
            )
        if cluster not in config.clusters:
            raise ValueError(
                f"Cluster '{cluster}' not found in config. Available: {sorted(config.clusters)}"
            )

        if lifetime is None:
            lifetime = (
                datetime.now(timezone.utc) + timedelta(days=config.lifetime_days)
            ).strftime("%Y-%m-%dT%H:%M:%SZ")

        project_id = f"{username}-{tool}".replace("_", "-")

        sh = SHMamplan.create(
            project={"project_id": project_id, "tool": tool},
            deployment={"cluster": cluster, "bucket": bucket, "lifetime": lifetime},
            service={"owner": username},
        )
        sh.write(Path(output))
        return project_id


