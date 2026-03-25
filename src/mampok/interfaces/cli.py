"""CLI-Interface — Typer-basierte Kommandozeilen-Schnittstelle."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Callable

import typer

from mampok.config.config import MampokConfig
from mampok.mamplan.mamplan import Mamplan
from mampok.mamplan.mamplate import Mamplate
from mampok.mampok.mampok import Mampok

logger = logging.getLogger(__name__)

app = typer.Typer(
    name="mampok",
    help="Kubernetes deployment manager for bioinformatics pipelines.",
    no_args_is_help=True,
)


@app.callback()
def _setup_logging(
    log_level: Annotated[
        str,
        typer.Option("--log-level", help="Log level: DEBUG, INFO, WARNING, ERROR."),
    ] = "WARNING",
    debug: Annotated[
        bool,
        typer.Option("--debug", help="Shorthand for --log-level DEBUG."),
    ] = False,
) -> None:
    """Configure logging for Mampok."""
    level = logging.DEBUG if debug else getattr(logging, log_level.upper(), logging.WARNING)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

# ---------------------------------------------------------------------------
# Shared Typer option definitions
# ---------------------------------------------------------------------------

_OPT_CONFIG = typer.Option(
    "--config",
    help="Path to Mampok config file.",
)
_OPT_SELECTION = typer.Option(
    "-s",
    "--selection",
    help="Filter: section:key:value (repeatable, AND-combined).",
)
_OPT_REGEX_SELECTION = typer.Option(
    "-rs",
    "--regex-select",
    help="Regex filter: section:key:pattern (repeatable, AND-combined).",
)
_OPT_TIMEOUT = typer.Option(
    "--timeout",
    help="Timeout in seconds for wait_for_ready.",
    show_default=True,
)
_OPT_THROW_ERROR = typer.Option(
    "--throw-error",
    help="Disable error tolerance — raise on first failure.",
)
_OPT_YES = typer.Option(
    "-Y",
    "--yes",
    help="Skip confirmation prompts.",
)
_OPT_DRY_RUN = typer.Option(
    "--dry-run",
    help="Print manifests without deploying.",
)


# ---------------------------------------------------------------------------
# I2 — Mamplan-Loading
# ---------------------------------------------------------------------------


def load_mamplans(path: Path) -> list[Mamplan]:
    """Load one or more Mamplans from a file or directory.

    Args:
        path: Path to a single Mamplan JSON file or a directory. Directories
            are scanned recursively for ``*-mamplan.json`` files.

    Returns:
        List of loaded and validated Mamplan instances.

    Raises:
        FileNotFoundError: If path does not exist.
        ValueError: If path is a file but has an unexpected extension.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Path not found: {path}")

    if path.is_file():
        return [Mamplan.read_in(path)]

    mamplan_files = sorted(path.rglob("*-mamplan.json"))
    if not mamplan_files:
        typer.echo(f"No mamplan files found in: {path}")
        return []
    return [Mamplan.read_in(f) for f in mamplan_files]


def load_mamplates(mamplates_path: Path) -> dict[str, Mamplate]:
    """Load all Mamplates from a directory into a dict keyed by tool name.

    Args:
        mamplates_path: Directory containing ``*-mamplate.json`` files.

    Returns:
        Dict mapping tool name to Mamplate instance.

    Raises:
        FileNotFoundError: If directory does not exist.
    """
    mamplates_path = Path(mamplates_path)
    if not mamplates_path.exists():
        raise FileNotFoundError(f"Mamplates directory not found: {mamplates_path}")

    result: dict[str, Mamplate] = {}
    for f in sorted(mamplates_path.glob("*-mamplate.json")):
        mamplate = Mamplate.read_in(f)
        result[mamplate.data["tool"]] = mamplate
    return result


# ---------------------------------------------------------------------------
# I4 — Factory
# ---------------------------------------------------------------------------


def create_mampok_instance(
    config: MampokConfig,
    mamplan: Mamplan,
    mamplates: dict[str, Mamplate],
) -> Mampok:
    """Create a fully configured Mampok instance from config + mamplan.

    Args:
        config: MampokConfig with cluster and S3 credentials.
        mamplan: Loaded Mamplan instance.
        mamplates: Dict of available Mamplates keyed by tool name.

    Returns:
        Configured Mampok orchestrator instance.

    Raises:
        KeyError: If the tool referenced by the Mamplan has no Mamplate.
    """
    cluster_name = mamplan.data["deployment"]["cluster"]
    tool = mamplan.data["project"]["tool"]
    project_id = mamplan.data["project"]["project_id"]

    if tool not in mamplates:
        raise KeyError(
            f"No mamplate found for tool '{tool}'. "
            f"Available: {list(mamplates)}"
        )
    mamplate = mamplates[tool]

    raw_bucket = mamplan.data["deployment"].get("bucket") or ""
    if raw_bucket:
        bucket = raw_bucket
    else:
        prefix = config.s3.prefix
        bucket = f"{prefix}-{project_id}-{tool}" if prefix else f"{project_id}-{tool}"

    kube = config.build_deployment_manager(cluster_name)
    s3 = config.build_s3_client(bucket)
    return Mampok(mamplan, mamplate, kube, s3)


# ---------------------------------------------------------------------------
# I5 — Error Tolerance
# ---------------------------------------------------------------------------


def run_with_error_tolerance(
    mamplans: list[Mamplan],
    action: Callable[[Mamplan], None],
    throw_error: bool = False,
) -> None:
    """Iterate over Mamplans and collect errors instead of aborting.

    Args:
        mamplans: List of Mamplans to process.
        action: Callable executed for each Mamplan.
        throw_error: If True, re-raise the first exception immediately
            (disables error tolerance).

    Raises:
        Exception: Re-raised immediately when throw_error is True.
        typer.Exit: With code 1 if any errors were collected.
    """
    errors: list[tuple[str, Exception]] = []

    for mamplan in mamplans:
        project_id = mamplan.data["project"]["project_id"]
        try:
            action(mamplan)
        except Exception as exc:
            if throw_error:
                raise
            errors.append((project_id, exc))
            typer.echo(f"[ERROR] {project_id}: {exc}", err=True)

    if errors:
        typer.echo("\nError summary:", err=True)
        for project_id, exc in errors:
            typer.echo(f"  {project_id}: {exc}", err=True)
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# I3 — Mamplan-Selektion
# ---------------------------------------------------------------------------


def _get_nested(data: dict, keys: list[str]) -> object:
    """Retrieve a nested dict value via a list of keys.

    Args:
        data: Dict to traverse.
        keys: Ordered list of keys.

    Returns:
        The value at the nested path, or None if any key is missing.
    """
    current: object = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)  # type: ignore[assignment]
    return current


def _parse_selection_token(token: str) -> tuple[list[str], str]:
    """Parse 'section:key:value' into (key_path, value).

    Args:
        token: Selection string of the form ``section:key:value``.
            The value part may itself contain colons.

    Returns:
        Tuple of (key_path, value) where key_path is a list of keys.

    Raises:
        ValueError: If token has fewer than two colons.
    """
    parts = token.split(":", 2)
    if len(parts) < 3:
        raise ValueError(
            f"Invalid selection token '{token}'. "
            "Expected format: section:key:value"
        )
    section, key, value = parts
    return [section, key], value


def apply_selection(
    mamplans: list[Mamplan],
    selections: list[str],
    regex_selections: list[str],
) -> list[Mamplan]:
    """Filter Mamplans by key-value and/or regex criteria (AND-combined).

    Empty selection lists leave the Mamplan list unchanged.

    Args:
        mamplans: List of Mamplans to filter.
        selections: Exact-match filters as ``section:key:value`` strings.
        regex_selections: Regex filters as ``section:key:pattern`` strings.

    Returns:
        Filtered list of Mamplans. May be empty if nothing matches.
    """
    if not selections and not regex_selections:
        return mamplans

    result: list[Mamplan] = []
    for mamplan in mamplans:
        if _mamplan_matches(mamplan, selections, regex_selections):
            result.append(mamplan)
    return result


def _mamplan_matches(
    mamplan: Mamplan,
    selections: list[str],
    regex_selections: list[str],
) -> bool:
    """Return True if the Mamplan matches all selection criteria.

    Args:
        mamplan: Mamplan to test.
        selections: Exact-match filters.
        regex_selections: Regex filters.

    Returns:
        True if all filters match.
    """
    for token in selections:
        try:
            keys, expected = _parse_selection_token(token)
        except ValueError as exc:
            typer.echo(f"[WARNING] {exc}", err=True)
            continue
        actual = _get_nested(mamplan.data, keys)
        if str(actual) != expected:
            return False

    for token in regex_selections:
        try:
            keys, pattern = _parse_selection_token(token)
        except ValueError as exc:
            typer.echo(f"[WARNING] {exc}", err=True)
            continue
        actual = _get_nested(mamplan.data, keys)
        if not re.search(pattern, str(actual) if actual is not None else ""):
            return False

    return True


# ---------------------------------------------------------------------------
# I3 helper — parse edit arguments
# ---------------------------------------------------------------------------


def _parse_edit_args(fields: list[str]) -> dict:
    """Parse ``-e section:key:value`` strings into edit() kwargs.

    Args:
        fields: List of ``section:key:value`` strings.

    Returns:
        Dict with ``__``-joined keys suitable for ``mamplan.edit(**kwargs)``.

    Raises:
        ValueError: If a token has fewer than two colons.
    """
    kwargs: dict = {}
    for token in fields:
        parts = token.split(":", 2)
        if len(parts) < 3:
            raise ValueError(
                f"Invalid edit token '{token}'. "
                "Expected format: section:key:value"
            )
        section, key, value = parts
        kwargs[f"{section}__{key}"] = value
    return kwargs


# ---------------------------------------------------------------------------
# I13 helper — derive user list from mamplan
# ---------------------------------------------------------------------------


def _derive_users(mamplan: Mamplan) -> list[str]:
    """Derive the user list for auth secret from service.organization + service.user.

    If 'public' is in organization, returns ``['public']``.

    Args:
        mamplan: Mamplan to inspect.

    Returns:
        Deduplicated list of usernames.
    """
    service = mamplan.data.get("service", {})
    organization: list[str] = service.get("organization", [])
    users: list[str] = service.get("user", [])

    if "public" in organization:
        return ["public"]

    combined = list(dict.fromkeys(organization + users))
    return combined


# ---------------------------------------------------------------------------
# CLI class (I6–I14)
# ---------------------------------------------------------------------------


class CLI:
    """Typer-based CLI for Mampok.

    Iterates over Mamplans with error tolerance: if one Mamplan fails,
    the error is collected and processing continues with the next one.
    All errors are reported at the end.

    Args:
        config: Loaded and validated MampokConfig.
    """

    def __init__(self, config: MampokConfig) -> None:
        """Initialize CLI.

        Args:
            config: Loaded and validated MampokConfig.
        """
        self.config = config

    def _load(self, path: Path) -> tuple[list[Mamplan], dict[str, Mamplate]]:
        """Load Mamplans from path and all Mamplates from config.

        Args:
            path: Path to Mamplan file or directory.

        Returns:
            Tuple of (mamplans, mamplates).
        """
        mamplans = load_mamplans(path)
        mamplates = load_mamplates(self.config.mamplates_path)
        return mamplans, mamplates

    # I6
    def deploy(
        self,
        mamplan_path: Path,
        selection: list[str] | None = None,
        regex_selection: list[str] | None = None,
        timeout: int = 300,
        dry_run: bool = False,
        throw_error: bool = False,
    ) -> None:
        """Deploy one or more projects to Kubernetes.

        Args:
            mamplan_path: Path to Mamplan file or directory.
            selection: Key-value selection filters.
            regex_selection: Regex selection filters.
            timeout: Wait-for-ready timeout in seconds.
            dry_run: If True, print manifests without deploying.
            throw_error: If True, disable error tolerance.
        """
        mamplans, mamplates = self._load(mamplan_path)
        mamplans = apply_selection(mamplans, selection or [], regex_selection or [])

        if dry_run:
            for mamplan in mamplans:
                mampok = create_mampok_instance(self.config, mamplan, mamplates)
                cfg = mampok._build_deployment_config(self.config)
                typer.echo(f"[DRY-RUN] {cfg.project_id}: would deploy to cluster '{cfg.namespace}'")
            return

        config = self.config

        def _deploy(mamplan: Mamplan) -> None:
            mampok = create_mampok_instance(config, mamplan, mamplates)
            for _ in mampok.deploy(config, timeout=timeout):
                pass
            typer.echo(f"Deployed: {mamplan.data['project']['project_id']}")

        run_with_error_tolerance(mamplans, _deploy, throw_error=throw_error)

    # I7
    def stop(
        self,
        mamplan_path: Path,
        selection: list[str] | None = None,
        regex_selection: list[str] | None = None,
        throw_error: bool = False,
    ) -> None:
        """Stop one or more deployments (removes K8s resources, S3 remains).

        Args:
            mamplan_path: Path to Mamplan file or directory.
            selection: Key-value selection filters.
            regex_selection: Regex selection filters.
            throw_error: If True, disable error tolerance.
        """
        mamplans, mamplates = self._load(mamplan_path)
        mamplans = apply_selection(mamplans, selection or [], regex_selection or [])
        config = self.config

        def _stop(mamplan: Mamplan) -> None:
            mampok = create_mampok_instance(config, mamplan, mamplates)
            mampok.stop(config)
            typer.echo(f"Stopped: {mamplan.data['project']['project_id']}")

        run_with_error_tolerance(mamplans, _stop, throw_error=throw_error)

    # I8
    def stop_expired(
        self,
        repository: Path,
        yes: bool = False,
        throw_error: bool = False,
    ) -> None:
        """Stop all expired active deployments in a repository.

        Args:
            repository: Path to Mamplan repository directory.
            yes: If True, skip confirmation prompt.
            throw_error: If True, disable error tolerance.
        """
        all_mamplans = load_mamplans(repository)
        expired = [m for m in all_mamplans if _is_mamplan_expired(m)]

        if not expired:
            typer.echo("No expired deployments found.")
            return

        typer.echo(f"Found {len(expired)} expired deployment(s):")
        for m in expired:
            typer.echo(f"  - {m.data['project']['project_id']}")

        if not yes:
            confirmed = typer.confirm("Stop all expired deployments?")
            if not confirmed:
                typer.echo("Aborted.")
                return

        mamplates = load_mamplates(self.config.mamplates_path)
        config = self.config

        def _stop(mamplan: Mamplan) -> None:
            mampok = create_mampok_instance(config, mamplan, mamplates)
            mampok.stop(config)
            typer.echo(f"Stopped: {mamplan.data['project']['project_id']}")

        run_with_error_tolerance(expired, _stop, throw_error=throw_error)

    # I9
    def redeploy(
        self,
        mamplan_path: Path,
        selection: list[str] | None = None,
        regex_selection: list[str] | None = None,
        timeout: int = 300,
        throw_error: bool = False,
    ) -> None:
        """Stop and redeploy one or more projects.

        Args:
            mamplan_path: Path to Mamplan file or directory.
            selection: Key-value selection filters.
            regex_selection: Regex selection filters.
            timeout: Wait-for-ready timeout in seconds.
            throw_error: If True, disable error tolerance.
        """
        mamplans, mamplates = self._load(mamplan_path)
        mamplans = apply_selection(mamplans, selection or [], regex_selection or [])
        config = self.config

        def _redeploy(mamplan: Mamplan) -> None:
            mampok = create_mampok_instance(config, mamplan, mamplates)
            mampok.stop(config)
            for _ in mampok.deploy(config, timeout=timeout):
                pass
            typer.echo(f"Redeployed: {mamplan.data['project']['project_id']}")

        run_with_error_tolerance(mamplans, _redeploy, throw_error=throw_error)

    # I10
    def edit_mamplan(
        self,
        mamplan_path: Path,
        fields: list[str] | None = None,
        redeploy: bool = False,
        timeout: int = 300,
        throw_error: bool = False,
    ) -> None:
        """Edit Mamplan fields and optionally redeploy.

        Args:
            mamplan_path: Path to a single Mamplan file.
            fields: Edit tokens as ``section:key:value`` strings.
            redeploy: If True, redeploy after editing.
            timeout: Wait-for-ready timeout (used when redeploy=True).
            throw_error: If True, disable error tolerance.
        """
        mamplan = Mamplan.read_in(mamplan_path)
        kwargs = _parse_edit_args(fields or [])
        mamplan.edit(**kwargs)
        mamplan.write(mamplan_path)
        typer.echo(f"Saved: {mamplan_path}")

        if redeploy:
            mamplates = load_mamplates(self.config.mamplates_path)
            config = self.config

            def _redeploy(m: Mamplan) -> None:
                mampok = create_mampok_instance(config, m, mamplates)
                mampok.stop(config)
                for _ in mampok.deploy(config, timeout=timeout):
                    pass
                typer.echo(f"Redeployed: {m.data['project']['project_id']}")

            run_with_error_tolerance([mamplan], _redeploy, throw_error=throw_error)

    # I11
    def create_mamplan(self, **kwargs) -> None:
        """Create a new Mamplan from keyword arguments.

        Args:
            **kwargs: Mamplan sections (project, deployment, service, etc.).
        """
        output: Path = kwargs.pop("output")
        mamplan = Mamplan.create(**kwargs)
        mamplan.write(output)
        typer.echo(f"Created: {output / mamplan._get_auto_filename()}"
                   if Path(output).is_dir() else f"Created: {output}")

    # I12
    def check_status_report(
        self,
        repository: Path,
        selection: list[str] | None = None,
        regex_selection: list[str] | None = None,
        throw_error: bool = False,
    ) -> None:
        """Print a status report for all Mamplans in a repository.

        Args:
            repository: Path to Mamplan repository directory.
            selection: Key-value selection filters.
            regex_selection: Regex selection filters.
            throw_error: If True, disable error tolerance.
        """
        mamplans, mamplates = self._load(repository)
        mamplans = apply_selection(mamplans, selection or [], regex_selection or [])
        config = self.config

        rows: list[dict] = []

        def _check(mamplan: Mamplan) -> None:
            mampok = create_mampok_instance(config, mamplan, mamplates)
            status = mampok.check_status(config)
            rows.append(status)

        run_with_error_tolerance(mamplans, _check, throw_error=throw_error)

        if not rows:
            typer.echo("No mamplans found.")
            return

        col_id = max(len(r["project_id"]) for r in rows)
        col_id = max(col_id, len("Project ID"))
        header = (
            f"{'Project ID':<{col_id}}  "
            f"{'Expected':<8}  "
            f"{'Actual':<8}  "
            f"Healthy"
        )
        typer.echo(header)
        typer.echo("-" * len(header))
        for row in rows:
            expected = "active" if row["expected_active"] else "inactive"
            actual = "active" if row["actually_deployed"] else "missing"
            healthy = "✓" if row["healthy"] else "✗"
            typer.echo(
                f"{row['project_id']:<{col_id}}  "
                f"{expected:<8}  "
                f"{actual:<8}  "
                f"{healthy}"
            )

    # I13
    def update_auth(
        self,
        mamplan_path: Path,
        throw_error: bool = False,
    ) -> None:
        """Update the auth secret for one or more projects.

        Derives the user list from service.organization + service.user.
        If 'public' is in organization, uses ['public'].

        Args:
            mamplan_path: Path to Mamplan file or directory.
            throw_error: If True, disable error tolerance.
        """
        mamplans, mamplates = self._load(mamplan_path)
        config = self.config

        def _update(mamplan: Mamplan) -> None:
            users = _derive_users(mamplan)
            mampok = create_mampok_instance(config, mamplan, mamplates)
            mampok.update_auth_secret(users, config)
            typer.echo(
                f"Updated auth: {mamplan.data['project']['project_id']} "
                f"({len(users)} user(s))"
            )

        run_with_error_tolerance(mamplans, _update, throw_error=throw_error)

    # I14
    def download(
        self,
        mamplan_path: Path,
        output: Path,
        throw_error: bool = False,
    ) -> None:
        """Download output files from S3 to local filesystem.

        Uses ``downloadpaths`` from the Mamplate to determine which S3 keys
        to download. Each entry maps a local label to the file's base name
        in the S3 bucket.

        Args:
            mamplan_path: Path to a single Mamplan file.
            output: Local output directory.
            throw_error: If True, disable error tolerance.
        """
        output = Path(output)
        output.mkdir(parents=True, exist_ok=True)

        mamplans, mamplates = self._load(mamplan_path)
        config = self.config

        def _download(mamplan: Mamplan) -> None:
            mampok = create_mampok_instance(config, mamplan, mamplates)
            merged = mamplan.merge_container_config(mampok.mamplate)
            downloadpaths: dict[str, str] = merged["main"].get("downloadpaths", {})
            if not downloadpaths:
                typer.echo(
                    f"[WARNING] No downloadpaths defined for "
                    f"{mamplan.data['project']['project_id']}"
                )
                return
            for label, container_path in downloadpaths.items():
                s3_key = Path(container_path).name
                local_file = output / label
                mampok.s3.download_to_local(s3_key, local_file)
                typer.echo(f"Downloaded: {s3_key} → {local_file}")

        run_with_error_tolerance(mamplans, _download, throw_error=throw_error)


# ---------------------------------------------------------------------------
# Helper — expiration check without full Mampok instance
# ---------------------------------------------------------------------------


def _is_mamplan_expired(mamplan: Mamplan) -> bool:
    """Return True if the Mamplan is active and its lifetime has passed.

    Args:
        mamplan: Mamplan to check.

    Returns:
        True if deployment.status is True and lifetime is in the past.
    """
    deployment = mamplan.data["deployment"]
    if not deployment["status"]:
        return False
    lifetime = datetime.fromisoformat(deployment["lifetime"])
    if lifetime.tzinfo is None:
        lifetime = lifetime.replace(tzinfo=timezone.utc)
    return lifetime < datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Lifetime parsing helper
# ---------------------------------------------------------------------------

_RELATIVE_LIFETIME_RE = re.compile(r"^(\d+)([dwm])$", re.IGNORECASE)


def _parse_lifetime(value: str) -> str:
    """Parse lifetime as relative shorthand or ISO 8601 string.

    Args:
        value: Relative string like '30d', '4w', '3m', or ISO 8601 datetime.

    Returns:
        ISO 8601 UTC datetime string.

    Raises:
        typer.BadParameter: If the value is neither a valid relative format nor ISO 8601.
    """
    match = _RELATIVE_LIFETIME_RE.match(value)
    if match:
        amount = int(match.group(1))
        unit = match.group(2).lower()
        if unit == "d":
            delta = timedelta(days=amount)
        elif unit == "w":
            delta = timedelta(weeks=amount)
        else:  # 'm'
            delta = timedelta(days=amount * 30)
        return (datetime.now(timezone.utc) + delta).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value
    except ValueError:
        raise typer.BadParameter(
            f"Invalid lifetime '{value}'. Use relative (30d, 4w, 3m) or ISO 8601 (2026-12-31T00:00:00Z)."
        )


# ---------------------------------------------------------------------------
# Typer commands (thin wrappers, I6–I14)
# ---------------------------------------------------------------------------


@app.command()
def deploy(
    mamplan: Annotated[Path, typer.Argument(help="Path to mamplan file or directory.")],
    config: Annotated[Path, _OPT_CONFIG],
    selection: Annotated[list[str], _OPT_SELECTION] = [],
    regex_selection: Annotated[list[str], _OPT_REGEX_SELECTION] = [],
    timeout: Annotated[int, _OPT_TIMEOUT] = 300,
    dry_run: Annotated[bool, _OPT_DRY_RUN] = False,
    throw_error: Annotated[bool, _OPT_THROW_ERROR] = False,
) -> None:
    """Deploy a project to Kubernetes."""
    logger.info(
        "deploy: mamplan=%s, config=%s, selection=%s, regex_selection=%s, timeout=%s, dry_run=%s, throw_error=%s",
        mamplan, config, selection, regex_selection, timeout, dry_run, throw_error,
    )
    cfg = MampokConfig.from_file(config.expanduser())
    CLI(cfg).deploy(
        mamplan,
        selection=selection,
        regex_selection=regex_selection,
        timeout=timeout,
        dry_run=dry_run,
        throw_error=throw_error,
    )


@app.command()
def stop(
    mamplan: Annotated[Path, typer.Argument(help="Path to mamplan file or directory.")],
    config: Annotated[Path, _OPT_CONFIG],
    selection: Annotated[list[str], _OPT_SELECTION] = [],
    regex_selection: Annotated[list[str], _OPT_REGEX_SELECTION] = [],
    throw_error: Annotated[bool, _OPT_THROW_ERROR] = False,
) -> None:
    """Stop a deployment (removes K8s resources, S3 remains)."""
    logger.info(
        "stop: mamplan=%s, config=%s, selection=%s, regex_selection=%s, throw_error=%s",
        mamplan, config, selection, regex_selection, throw_error,
    )
    cfg = MampokConfig.from_file(config.expanduser())
    CLI(cfg).stop(
        mamplan,
        selection=selection,
        regex_selection=regex_selection,
        throw_error=throw_error,
    )


@app.command(name="stop-expired")
def stop_expired(
    repository: Annotated[Path, typer.Argument(help="Path to mamplan repository directory.")],
    config: Annotated[Path, _OPT_CONFIG],
    yes: Annotated[bool, _OPT_YES] = False,
    throw_error: Annotated[bool, _OPT_THROW_ERROR] = False,
) -> None:
    """Stop all expired active deployments in a repository."""
    logger.info("stop-expired: repository=%s, config=%s, yes=%s, throw_error=%s", repository, config, yes, throw_error)
    cfg = MampokConfig.from_file(config.expanduser())
    CLI(cfg).stop_expired(repository, yes=yes, throw_error=throw_error)


@app.command()
def redeploy(
    mamplan: Annotated[Path, typer.Argument(help="Path to mamplan file or directory.")],
    config: Annotated[Path, _OPT_CONFIG],
    selection: Annotated[list[str], _OPT_SELECTION] = [],
    regex_selection: Annotated[list[str], _OPT_REGEX_SELECTION] = [],
    timeout: Annotated[int, _OPT_TIMEOUT] = 300,
    throw_error: Annotated[bool, _OPT_THROW_ERROR] = False,
) -> None:
    """Stop and redeploy a project."""
    logger.info(
        "redeploy: mamplan=%s, config=%s, selection=%s, regex_selection=%s, timeout=%s, throw_error=%s",
        mamplan, config, selection, regex_selection, timeout, throw_error,
    )
    cfg = MampokConfig.from_file(config.expanduser())
    CLI(cfg).redeploy(
        mamplan,
        selection=selection,
        regex_selection=regex_selection,
        timeout=timeout,
        throw_error=throw_error,
    )


@app.command(name="edit-mamplan")
def edit_mamplan(
    mamplan: Annotated[Path, typer.Argument(help="Path to mamplan file.")],
    config: Annotated[Path, _OPT_CONFIG],
    fields: Annotated[
        list[str],
        typer.Option("--edit", "-e", help="Fields to edit: section:key:value."),
    ] = [],
    redeploy_after: Annotated[
        bool,
        typer.Option("--redeploy", help="Redeploy after editing."),
    ] = False,
    timeout: Annotated[int, _OPT_TIMEOUT] = 300,
    throw_error: Annotated[bool, _OPT_THROW_ERROR] = False,
) -> None:
    """Edit mamplan fields and optionally redeploy."""
    logger.info(
        "edit-mamplan: mamplan=%s, config=%s, fields=%s, redeploy=%s, timeout=%s, throw_error=%s",
        mamplan, config, fields, redeploy_after, timeout, throw_error,
    )
    cfg = MampokConfig.from_file(config.expanduser())
    CLI(cfg).edit_mamplan(
        mamplan,
        fields=fields,
        redeploy=redeploy_after,
        timeout=timeout,
        throw_error=throw_error,
    )


@app.command(name="create-mamplan")
def create_mamplan(
    project_id: Annotated[str, typer.Option(help="Unique project ID.")],
    tool: Annotated[str, typer.Option(help="Tool name (must match a mamplate).")],
    cluster: Annotated[str, typer.Option(help="Target cluster identifier.")],
    lifetime: Annotated[str, typer.Option(help="Expiry datetime: ISO 8601 (2026-12-31T00:00:00Z) or relative (30d, 4w, 3m).")],
    output: Annotated[Path, typer.Option(help="Output path (file or directory).")],
    config: Annotated[Path, _OPT_CONFIG],
    owner: Annotated[str, typer.Option(help="Project owner username.")],
    datatype: Annotated[list[str], typer.Option(help="Data types (repeatable).")],
    files: Annotated[list[str], typer.Option(help="Files to upload (repeatable).")] = [],
    analyst: Annotated[list[str], typer.Option(help="Analyst usernames (repeatable).")] = [],
    organization: Annotated[list[str], typer.Option(help="Organizations (repeatable).")] = [],
    user: Annotated[list[str], typer.Option(help="User access list (repeatable).")] = [],
    metadata: Annotated[list[str], typer.Option(help="Metadata IDs (repeatable).")] = [],
    bucket: Annotated[str, typer.Option(help="S3 bucket name (auto-generated if empty).")] = "",
    auth: Annotated[bool, typer.Option(help="Enable login protection.")] = False,
    generate_url: Annotated[bool, typer.Option(help="Auto-generate deployment URL.")] = True,
) -> None:
    """Create a new mamplan file."""
    logger.info(
        "create-mamplan: project_id=%s, tool=%s, cluster=%s, lifetime=%s, output=%s, owner=%s, datatype=%s, auth=%s",
        project_id, tool, cluster, lifetime, output, owner, datatype, auth,
    )
    cfg = MampokConfig.from_file(config.expanduser())
    creation_date = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lifetime = _parse_lifetime(lifetime)
    CLI(cfg).create_mamplan(
        output=output,
        project={
            "project_id": project_id,
            "tool": tool,
            "files": files,
            "creation_date": creation_date,
        },
        deployment={
            "cluster": cluster,
            "lifetime": lifetime,
            "bucket": bucket,
            "url": "",
            "auth": auth,
            "generate_url": generate_url,
        },
        service={
            "analyst": analyst or [owner] if owner else analyst,
            "owner": owner,
            "organization": organization,
            "user": user,
            "datatype": datatype,
            "metadata": metadata,
        },
    )


@app.command(name="check-status")
def check_status(
    repository: Annotated[Path, typer.Argument(help="Path to mamplan repository directory.")],
    config: Annotated[Path, _OPT_CONFIG],
    selection: Annotated[list[str], _OPT_SELECTION] = [],
    regex_selection: Annotated[list[str], _OPT_REGEX_SELECTION] = [],
    throw_error: Annotated[bool, _OPT_THROW_ERROR] = False,
) -> None:
    """Show deployment status report for all mamplans in a repository."""
    logger.info(
        "check-status: repository=%s, config=%s, selection=%s, regex_selection=%s, throw_error=%s",
        repository, config, selection, regex_selection, throw_error,
    )
    cfg = MampokConfig.from_file(config.expanduser())
    CLI(cfg).check_status_report(
        repository,
        selection=selection,
        regex_selection=regex_selection,
        throw_error=throw_error,
    )


@app.command(name="update-auth")
def update_auth(
    mamplan: Annotated[Path, typer.Argument(help="Path to mamplan file or directory.")],
    config: Annotated[Path, _OPT_CONFIG],
    throw_error: Annotated[bool, _OPT_THROW_ERROR] = False,
) -> None:
    """Update the auth secret for a project."""
    logger.info("update-auth: mamplan=%s, config=%s, throw_error=%s", mamplan, config, throw_error)
    cfg = MampokConfig.from_file(config.expanduser())
    CLI(cfg).update_auth(mamplan, throw_error=throw_error)


@app.command()
def download(
    mamplan: Annotated[Path, typer.Argument(help="Path to mamplan file or directory.")],
    output: Annotated[Path, typer.Argument(help="Local output directory.")],
    config: Annotated[Path, _OPT_CONFIG],
    throw_error: Annotated[bool, _OPT_THROW_ERROR] = False,
) -> None:
    """Download output files from S3 to local filesystem."""
    logger.info("download: mamplan=%s, output=%s, config=%s, throw_error=%s", mamplan, output, config, throw_error)
    cfg = MampokConfig.from_file(config.expanduser())
    CLI(cfg).download(mamplan, output, throw_error=throw_error)
