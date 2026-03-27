"""Python-API — programmatische Schnittstelle für andere Tools."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Iterator

from mampok.config.config import MampokConfig
from mampok.interfaces.cli import create_mampok_instance
from mampok.mamplan.mamplan import Mamplan
from mampok.mamplan.mamplate import Mamplate
from mampok.mamplan.metadata import _merge_unique, parse_metadata_files


class API:
    """Importierbare Python-API für programmatischen Mampok-Zugriff.

    Für jede Operation wird pro Mamplan eine Mampok-Instanz erstellt
    und die Operation delegiert.

    Im Gegensatz zur CLI:
    - Kein interaktiver User-Input
    - deploy() / redeploy() geben Fortschritts-Iteratoren zurück
    - Explizite Edit-Methoden (edit_lifetime, edit_sharing) statt String-Parsing
    - check_status_report() gibt list[dict] zurück statt zu drucken
    - Keine Error Tolerance — Exceptions propagieren direkt

    Args:
        config_path: Pfad zur MampokConfig-JSON-Datei.
    """

    def __init__(self, config_path: Path) -> None:
        """Initialisiert API mit Pfad zur Config-Datei.

        Args:
            config_path: Pfad zur MampokConfig-JSON-Datei.
        """
        self.config_path = Path(config_path)

    # ---------------------------------------------------------------------------
    # Private helpers
    # ---------------------------------------------------------------------------

    def _load_config(self) -> MampokConfig:
        """Load MampokConfig from config_path."""
        return MampokConfig.from_file(self.config_path)

    def _load_mamplans(self, path: Path) -> list[Mamplan]:
        """Load Mamplan(s) from a file or directory.

        Args:
            path: Path to a single Mamplan JSON file or a directory.
                  Directories are scanned recursively for *-mamplan.json files.

        Returns:
            List of loaded and validated Mamplan instances.

        Raises:
            FileNotFoundError: If path does not exist.
        """
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Path not found: {p}")
        if p.is_file():
            return [Mamplan.read_in(p)]
        return [Mamplan.read_in(f) for f in sorted(p.rglob("*-mamplan.json"))]

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

    def _load(self, path: Path) -> tuple[list[Mamplan], dict[str, Mamplate], MampokConfig]:
        """Load Mamplans, Mamplates and MampokConfig in one call.

        Args:
            path: Path to Mamplan file or directory.

        Returns:
            Tuple of (mamplans, mamplates, config).
        """
        config = self._load_config()
        mamplans = self._load_mamplans(path)
        mamplates = self._load_mamplates(config)
        return mamplans, mamplates, config

    # ---------------------------------------------------------------------------
    # core operations
    # ---------------------------------------------------------------------------

    def deploy(self, mamplan_path: Path, timeout: int = 300, cleanup: bool = True) -> Iterator[dict]:
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
            KeyError: If the tool has no matching Mamplate.
            TimeoutError: If pods are not ready within the timeout.
        """
        mamplans, mamplates, config = self._load(mamplan_path)
        for mamplan in mamplans:
            mampok = create_mampok_instance(config, mamplan, mamplates)
            yield from mampok.deploy(config, timeout=timeout, cleanup=cleanup)
            mamplan.write(mamplan.source_path)

    def stop(self, mamplan_path: Path) -> None:
        """Stop a deployment (removes K8s resources, S3 bucket remains).

        Args:
            mamplan_path: Path to the Mamplan file.
        """
        mamplans, mamplates, config = self._load(mamplan_path)
        for mamplan in mamplans:
            mampok = create_mampok_instance(config, mamplan, mamplates)
            mampok.stop(config)
            mamplan.write(mamplan.source_path)

    def stop_expired(self, repository: Path) -> None:
        """Stop all expired active deployments in a repository.

        Args:
            repository: Path to the Mamplan repository directory.
        """
        all_mamplans, mamplates, config = self._load(repository)
        expired = [m for m in all_mamplans if m.is_expired]
        for mamplan in expired:
            mampok = create_mampok_instance(config, mamplan, mamplates)
            mampok.stop(config)
            mamplan.write(mamplan.source_path)

    def redeploy(self, mamplan_path: Path) -> Iterator[dict]:
        """Stop and redeploy a project.

        Yields stop confirmation, then all deploy progress dicts.

        Args:
            mamplan_path: Path to the Mamplan file.

        Yields:
            {"stage": "stop", "status": "done", "project_id": str}
            followed by all yields from deploy().
        """
        mamplans, mamplates, config = self._load(mamplan_path)
        for mamplan in mamplans:
            mampok = create_mampok_instance(config, mamplan, mamplates)
            mampok.stop(config)
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

    def check_status_report(self, repository: Path) -> list[dict]:
        """Return a status report for all Mamplans in a repository.

        Args:
            repository: Path to the Mamplan repository directory.

        Returns:
            List of status dicts:
            [{"project_id": str, "expected_active": bool,
              "actually_deployed": bool, "healthy": bool}, ...]
        """
        mamplans, mamplates, config = self._load(repository)
        rows: list[dict] = []
        for mamplan in mamplans:
            mampok = create_mampok_instance(config, mamplan, mamplates)
            rows.append(mampok.check_status(config))
        return rows

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
        mamplan = Mamplan.read_in(mamplan_path)
        mamplan.edit(deployment__lifetime=lifetime)
        mamplan.write(mamplan_path)

    def edit_sharing(
        self,
        mamplan_path: Path,
        users: list[str] | None = None,
        organizations: list[str] | None = None,
    ) -> Iterator[dict]:
        """Update the sharing tags of a Mamplan and optionally refresh the auth secret.

        Two-phase operation:
        1. Update tags.user / tags.organization and save to disk.
        2. If auth=True and status=True (running deployment): update the K8s
           auth secret to reflect the new user list. On failure, the Mamplan
           is rolled back to its original state before the exception is re-raised.

        Args:
            mamplan_path: Path to the Mamplan file.
            users: New user list for tags.user (replaces existing).
            organizations: New organization list for tags.organization (replaces existing).

        Yields:
            {"stage": "edit_sharing", "status": "saved", "project_id": str}
            {"stage": "auth_secret", "status": "updated"} (if auth+status=True)
            {"stage": "auth_secret", "status": "failed", "reason": str} (on K8s error)
            {"stage": "rollback", "status": "done"} (after rollback on failure)

        Raises:
            FileNotFoundError: If mamplan_path does not exist.
            jsonschema.ValidationError: If the new tags violate the schema (no file written).
            Exception: Re-raised K8s exception after rollback if auth secret update fails.
        """
        mamplan_path = Path(mamplan_path)
        mamplan = Mamplan.read_in(mamplan_path)
        original_data = copy.deepcopy(mamplan.data)
        project_id = mamplan.data["project"]["project_id"]

        # Phase 1: update tags (MamplanBase.edit() is atomic — rolls back on ValidationError)
        if users is not None:
            mamplan.edit(tags__user=users)
        if organizations is not None:
            mamplan.edit(tags__organization=organizations)
        mamplan.write(mamplan_path)
        yield {"stage": "edit_sharing", "status": "saved", "project_id": project_id}

        # Phase 2: auth secret update (only for active, auth-protected deployments)
        auth = mamplan.data["deployment"].get("auth", False)
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
        output: Path | None = None,
    ) -> dict:
        """Return project metadata and K8s status for one or more Mamplans.

        Args:
            mamplan_path: Path to a Mamplan file or directory.
                          If a file, returns info for that single Mamplan.
                          If a directory, returns info for all Mamplans found.
            output: Optional path to write the result as a JSON file.

        Returns:
            Dict with structure:
            {"projects": {project_id: {"mamplan": dict, "tags": dict,
                                       "url": str, "status": bool}}}
        """
        mamplans, mamplates, config = self._load(mamplan_path)
        projects: dict = {}
        for mamplan in mamplans:
            mampok = create_mampok_instance(config, mamplan, mamplates)
            k8s_status = mampok.check_status(config)
            project_id = mamplan.data["project"]["project_id"]
            projects[project_id] = {
                "mamplan": mamplan.data,
                "tags": mamplan.data.get("tags", {}),
                "url": mamplan.data["deployment"].get("url", ""),
                "status": k8s_status["actually_deployed"],
            }
        result = {"projects": projects}
        if output is not None:
            output = Path(output)
            with output.open("w", encoding="utf-8") as f:
                json.dump(result, f, indent=2, ensure_ascii=False)
        return result

    def copy_results(
        self,
        mamplan_path: Path,
        dest_bucket: str,
        dest_prefix: str = "",
    ) -> None:
        """Copy result files from the project S3 bucket to another bucket (S3→S3).

        The list of files to copy is taken from the ``downloadpaths`` field in
        the Mamplate/Mamplan container config. No local storage is used.

        Args:
            mamplan_path: Path to the Mamplan file.
            dest_bucket: Name of the destination S3 bucket.
            dest_prefix: Optional key prefix in the destination bucket.

        Raises:
            FileNotFoundError: If mamplan_path does not exist.
            KeyError: If the tool has no matching Mamplate.
        """
        mamplans, mamplates, config = self._load(mamplan_path)
        for mamplan in mamplans:
            mampok = create_mampok_instance(config, mamplan, mamplates)
            merged = mamplan.merge_container_config(mampok.mamplate)
            downloadpaths: dict[str, str] = merged["main"].get("downloadpaths", {})
            src_bucket = mampok.s3.bucket
            for label, container_path in downloadpaths.items():
                src_key = Path(container_path).name
                dest_key = f"{dest_prefix}{label}" if dest_prefix else label
                mampok.s3.copy(src_bucket, src_key, dest_bucket, dest_key)


