"""CLI-Interface — Typer-basierte Kommandozeilen-Schnittstelle."""

from __future__ import annotations

import logging
import re
import sys
import textwrap
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Callable, Iterator, Optional

import typer

from mampok.config.config import MampokConfig
from mampok.mamplan.base import MamplanBase, parse_lifetime
from mampok.mamplan.mamplan import Mamplan
from mampok.mamplan.mamplate import Mamplate
from mampok.mamplan.shmamplan import SHMamplan
from mampok.mamplan.metadata import _merge_unique, parse_metadata_files
from mampok.mampok.mampok import Mampok

logger = logging.getLogger(__name__)

app = typer.Typer(
    name="mampok",
    help="Kubernetes deployment manager for bioinformatics pipelines.",
    no_args_is_help=True,
    context_settings={"help_option_names": ["--help", "-h"]},
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
_OPT_NO_CLEANUP = typer.Option(
    "--no-cleanup",
    help="Skip automatic K8s resource cleanup on deploy failure (useful for debugging).",
)
_OPT_REUPLOAD = typer.Option(
    "--reupload",
    help="Force re-upload of all files to S3, skipping size-based cache check.",
)


# ---------------------------------------------------------------------------
# I2 — Mamplan-Loading
# ---------------------------------------------------------------------------


def _load_single_mamplan(path: Path) -> MamplanBase:
    """Load a single Mamplan or SHMamplan file based on filename suffix."""
    if path.name.endswith("-shmamplan.json"):
        return SHMamplan.read_in(path)
    return Mamplan.read_in(path)


def load_mamplans(path: Path) -> list[MamplanBase]:
    """Load one or more Mamplans or SHMamplans from a file or directory.

    Args:
        path: Path to a single Mamplan/SHMamplan JSON file or a directory.
            Directories are scanned recursively for ``*-mamplan.json`` and
            ``*-shmamplan.json`` files.

    Returns:
        List of loaded and validated MamplanBase instances.

    Raises:
        FileNotFoundError: If path does not exist.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Path not found: {path}")

    if path.is_file():
        return [_load_single_mamplan(path)]

    # *-mamplan.json matches both *-mamplan.json and *-shmamplan.json via glob wildcard
    mamplan_files = sorted(path.rglob("*-mamplan.json"))
    if not mamplan_files:
        typer.echo(f"No mamplan files found in: {path}")
        return []
    return [_load_single_mamplan(f) for f in mamplan_files]


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

    init_container_types = mamplan.data.get("project", {}).get("init_container", [])
    init_mamplates = []
    for t in init_container_types:
        if t not in mamplates:
            raise KeyError(
                f"No mamplate found for init_container '{t}'. "
                f"Available: {list(mamplates)}"
            )
        init_mamplates.append(mamplates[t])

    raw_bucket = mamplan.data["deployment"].get("bucket") or ""
    if raw_bucket:
        bucket = raw_bucket
    else:
        prefix = config.s3.prefix
        bucket = f"{prefix}-{project_id}-{tool}" if prefix else f"{project_id}-{tool}"

    kube = config.build_deployment_manager(cluster_name)
    s3 = config.build_s3_client(bucket)
    return Mampok(mamplan, mamplate, kube, s3, init_mamplates=init_mamplates)


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


def _fmt_bytes(n: int) -> str:
    """Convert a byte count to a human-readable string (e.g. 250.0 MB)."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n} B" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n} B"  # unreachable, satisfies type checker


class _Printer:
    """Manages in-place progress lines (\\r) and normal echo lines."""

    def __init__(self) -> None:
        self._active = False

    def echo(self, text: str) -> None:
        if self._active:
            sys.stdout.write("\n")
            sys.stdout.flush()
            self._active = False
        typer.echo(text)

    def progress(self, text: str) -> None:
        sys.stdout.write(f"\r{text}")
        sys.stdout.flush()
        self._active = True

    def end(self) -> None:
        if self._active:
            sys.stdout.write("\n")
            sys.stdout.flush()
            self._active = False


def _handle_deploy_events(events: Iterator[dict], p: _Printer) -> None:
    """Consume a mampok.deploy() event stream and print progress to the terminal."""
    k8s_init_shown = False
    for event in events:
        stage = event.get("stage")
        status = event.get("status")

        if stage == "s3_upload":
            file_ = event.get("file", "")
            size_human = _fmt_bytes(event.get("size_bytes", 0))
            if status == "starting":
                p.progress(f"  Uploading {file_} ({size_human}): 0%")
            elif status == "progress":
                pct = event.get("transferred_pct", 0)
                p.progress(f"  Uploading {file_} ({size_human}): {pct}%")
            elif status == "done":
                p.echo(f"  Uploaded {file_} ({size_human})")
            elif status == "complete":
                n = event.get("total_files", 0)
                if n > 0:
                    total_human = _fmt_bytes(event.get("total_bytes", 0))
                    p.echo(f"  Total uploaded: {n} file(s), {total_human}")

        elif stage == "k8s_apply":
            p.echo(f"  Applied: {event.get('resource')}")

        elif stage == "k8s_init":
            if not k8s_init_shown:
                k8s_init_shown = True
                p.echo("  Waiting for init containers...")

        elif stage == "init_container_progress":
            container = event.get("container", "")
            if status == "progress":
                pct = event.get("transferred_pct", "?")
                tbytes = event.get("transferred_bytes_human", "")
                total = event.get("total_bytes_human", "")
                speed = event.get("speed", "")
                detail = f"{pct}%"
                if tbytes and total:
                    detail += f"  ({tbytes} / {total}"
                    if speed:
                        detail += f"  at {speed}"
                    detail += ")"
                p.progress(f"  Init container {container}: {detail}")
            elif status == "done":
                p.echo(f"  Init container {container} complete")

        elif stage == "k8s_ready":
            ready = event.get("ready_replicas", 0)
            p.progress(f"  Waiting for pod... ({ready} ready)")

        elif stage == "k8s_pod_warning":
            reason = event.get("reason", "")
            container = event.get("container", "")
            restarts = event.get("restart_count", 0)
            message = event.get("message", "")
            p.echo(f"  WARNING: {reason} (container={container}, restarts={restarts}): {message}")

        elif stage == "k8s_cleanup":
            p.echo("  Cleaned up K8s resources after deploy error")


def _handle_stop_events(events: Iterator[dict], p: _Printer) -> None:
    """Consume a mampok.stop() event stream and print progress to the terminal."""
    for event in events:
        stage = event.get("stage")
        status = event.get("status")
        if stage == "s3_final_sync":
            pod = event.get("pod", "")
            if status == "starting":
                p.echo(f"  syncing S3 data ({pod}) ...")
            elif status == "progress":
                pct = event.get("transferred_pct", "?")
                tbytes = event.get("transferred_bytes_human", "")
                total = event.get("total_bytes_human", "")
                speed = event.get("speed", "")
                detail = f"{pct}%"
                if tbytes and total:
                    detail += f"  ({tbytes} / {total}"
                    if speed:
                        detail += f"  at {speed}"
                    detail += ")"
                p.progress(f"  Syncing S3 ({pod}): {detail}")
            elif status == "done":
                p.echo("  S3 sync complete")
            elif status == "timeout":
                tf = event.get("transferred_files", "?")
                tot = event.get("total_files", "?")
                p.echo(f"  S3 sync timeout: {tf}/{tot} files transferred")
            elif status in ("skipped", "failed"):
                p.echo(f"  S3 sync {status}: {event.get('reason', '')}")
        elif stage == "k8s_delete":
            p.echo(f"  deleted: {event.get('resource')}")


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


_RELATIVE_OFFSET_RE = re.compile(r"^\+(\d+)([dwm])$", re.IGNORECASE)


def _expand_relative_lifetime(fields: list[str], mamplan: Mamplan) -> list[str]:
    """Expand '+Nd/w/m' offset tokens in deployment:lifetime to absolute ISO 8601.

    The offset is added to the mamplan's **existing** lifetime, not to now().
    Tokens for other fields are passed through unchanged.

    Args:
        fields: List of 'section:key:value' edit tokens.
        mamplan: The current (already loaded) Mamplan instance.

    Returns:
        New list of tokens with relative lifetime offsets resolved to absolute values.

    Raises:
        typer.BadParameter: If the existing lifetime cannot be parsed.
    """
    result = []
    for token in fields:
        parts = token.split(":", 2)
        if len(parts) == 3 and parts[0] == "deployment" and parts[1] == "lifetime":
            match = _RELATIVE_OFFSET_RE.match(parts[2])
            if match:
                amount = int(match.group(1))
                unit = match.group(2).lower()
                delta_map = {"d": timedelta(days=amount), "w": timedelta(weeks=amount), "m": timedelta(days=amount * 30)}
                delta = delta_map[unit]
                existing_str = mamplan.data["deployment"]["lifetime"]
                try:
                    existing = datetime.fromisoformat(existing_str.replace("Z", "+00:00"))
                except ValueError as exc:
                    raise typer.BadParameter(f"Cannot parse existing lifetime '{existing_str}': {exc}")
                new_iso = (existing + delta).strftime("%Y-%m-%dT%H:%M:%SZ")
                result.append(f"deployment:lifetime:{new_iso}")
                continue
        result.append(token)
    return result


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
# I5b — Interactive Confirmation
# ---------------------------------------------------------------------------


def _confirm_mamplans(
    mamplans: list[Mamplan],
    action: str,
    yes: bool = False,
) -> bool:
    """Show affected Mamplans and ask for confirmation.

    Args:
        mamplans: Affected Mamplans.
        action: Description of the action (e.g. 'deployed', 'stopped').
        yes: If True, the prompt is skipped.

    Returns:
        True if confirmed or yes=True, otherwise False.
    """
    if not mamplans:
        return True

    _W_ID, _W_CLUSTER, _W_OWNER, _W_URL, _W_PATH = 20, 12, 12, 48, 40

    header = (
        f"  {'Project ID':<{_W_ID}}  {'Cluster':<{_W_CLUSTER}}  "
        f"{'Owner':<{_W_OWNER}}  {'URL':<{_W_URL}}  Path"
    )
    separator = "  " + "-" * (len(header) - 2)

    typer.echo(f"\nThe following {len(mamplans)} Mamplan(s) will be {action}:")
    typer.echo(header)
    typer.echo(separator)

    for m in mamplans:
        project_id = m.data["project"]["project_id"]
        cluster = m.data["deployment"]["cluster"]
        owner = m.data.get("service", {}).get("owner", "")
        url = m.data["deployment"].get("url", "")
        path_str = str(m.source_path) if m.source_path else ""

        url_lines = textwrap.wrap(url, _W_URL) or [""]
        path_lines = textwrap.wrap(path_str, _W_PATH) or [""]
        n_lines = max(len(url_lines), len(path_lines))

        for i in range(n_lines):
            if i == 0:
                id_col = f"{project_id:<{_W_ID}}"
                cluster_col = f"{cluster:<{_W_CLUSTER}}"
                owner_col = f"{owner:<{_W_OWNER}}"
            else:
                id_col = " " * _W_ID
                cluster_col = " " * _W_CLUSTER
                owner_col = " " * _W_OWNER
            url_col = (url_lines[i] if i < len(url_lines) else "")
            path_col = (path_lines[i] if i < len(path_lines) else "")
            typer.echo(f"  {id_col}  {cluster_col}  {owner_col}  {url_col:<{_W_URL}}  {path_col}")

    typer.echo("")

    if yes:
        return True
    confirmed = typer.confirm("Continue?")
    if not confirmed:
        typer.echo("Aborted.")
    return confirmed


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
        timeout: int = 900,
        dry_run: bool = False,
        throw_error: bool = False,
        no_cleanup: bool = False,
        yes: bool = False,
    ) -> None:
        """Deploy one or more projects to Kubernetes.

        Args:
            mamplan_path: Path to Mamplan file or directory.
            selection: Key-value selection filters.
            regex_selection: Regex selection filters.
            timeout: Wait-for-ready timeout in seconds.
            dry_run: If True, print manifests without deploying.
            throw_error: If True, disable error tolerance.
            no_cleanup: If True, skip automatic K8s cleanup on failure.
            yes: If True, skip confirmation prompt.
        """
        mamplans, mamplates = self._load(mamplan_path)
        mamplans = apply_selection(mamplans, selection or [], regex_selection or [])

        if dry_run:
            for mamplan in mamplans:
                mampok = create_mampok_instance(self.config, mamplan, mamplates)
                cfg = mampok._build_deployment_config(self.config)
                typer.echo(f"[DRY-RUN] {cfg.project_id}: would deploy to cluster '{cfg.namespace}', url='{cfg.url}'")
            return

        if not _confirm_mamplans(mamplans, "deployed", yes):
            return

        config = self.config

        def _deploy(mamplan: Mamplan) -> None:
            mampok = create_mampok_instance(config, mamplan, mamplates)
            p = _Printer()
            _handle_deploy_events(mampok.deploy(config, timeout=timeout, cleanup=not no_cleanup), p)
            p.end()
            mamplan.write(mamplan.source_path)
            typer.echo(f"Deployed: {mamplan.data['project']['project_id']}")
            url = mamplan.data["deployment"].get("url", "")
            if url:
                typer.echo(f"URL: {url}")

        run_with_error_tolerance(mamplans, _deploy, throw_error=throw_error)

    # I7
    def stop(
        self,
        mamplan_path: Path,
        selection: list[str] | None = None,
        regex_selection: list[str] | None = None,
        throw_error: bool = False,
        yes: bool = False,
        download_before_stop: bool = False,
        download_output_dir: Path | None = None,
    ) -> None:
        """Stop one or more deployments (removes K8s resources, S3 remains).

        Args:
            mamplan_path: Path to Mamplan file or directory.
            selection: Key-value selection filters.
            regex_selection: Regex selection filters.
            throw_error: If True, disable error tolerance.
            yes: If True, skip confirmation prompt.
            download_before_stop: If True, download S3 data before stopping.
            download_output_dir: Destination for download (required if download_before_stop=True).
        """
        mamplans, mamplates = self._load(mamplan_path)
        mamplans = apply_selection(mamplans, selection or [], regex_selection or [])

        if not _confirm_mamplans(mamplans, "stopped", yes):
            return

        config = self.config

        def _stop(mamplan: Mamplan) -> None:
            mampok = create_mampok_instance(config, mamplan, mamplates)
            p = _Printer()
            if download_before_stop:
                for event in mampok.download(download_output_dir):
                    status = event.get("status")
                    if status == "starting":
                        p.echo(f"  downloading {event['total']} objects from s3 ...")
                    elif status == "done":
                        p.echo(f"  downloaded: {event['key']}")
                    elif status == "complete":
                        p.echo(f"  Download complete -> {event['dest']}")
            _handle_stop_events(mampok.stop(config), p)
            p.end()
            mamplan.write(mamplan.source_path)
            typer.echo(f"Stopped: {mamplan.data['project']['project_id']}")

        run_with_error_tolerance(mamplans, _stop, throw_error=throw_error)

    # I7b
    def download(
        self,
        mamplan_path: Path,
        output_dir: Path,
        selection: list[str] | None = None,
        regex_selection: list[str] | None = None,
        throw_error: bool = False,
        yes: bool = False,
    ) -> None:
        """Download all persistent S3 data for one or more projects to the local filesystem.

        Args:
            mamplan_path: Path to Mamplan file or directory.
            output_dir: Local destination directory. A subdirectory per project_id is created.
            selection: Key-value selection filters.
            regex_selection: Regex selection filters.
            throw_error: If True, disable error tolerance.
            yes: If True, skip confirmation prompt.
        """
        mamplans, mamplates = self._load(mamplan_path)
        mamplans = apply_selection(mamplans, selection or [], regex_selection or [])

        if not _confirm_mamplans(mamplans, "downloaded", yes):
            return

        config = self.config

        def _download(mamplan: Mamplan) -> None:
            mampok = create_mampok_instance(config, mamplan, mamplates)
            project_id = mamplan.data["project"]["project_id"]
            for event in mampok.download(output_dir):
                status = event.get("status")
                if status == "starting":
                    typer.echo(f"  downloading {event['total']} objects from s3 ...")
                elif status == "done":
                    typer.echo(f"  downloaded: {event['key']}")
                elif status == "complete":
                    typer.echo(f"Downloaded: {project_id} -> {event['dest']}")

        run_with_error_tolerance(mamplans, _download, throw_error=throw_error)

    # I8
    def stop_expired(
        self,
        repository: Path,
        yes: bool = False,
        throw_error: bool = False,
        selection: list[str] | None = None,
        regex_selection: list[str] | None = None,
    ) -> None:
        """Stop all expired active deployments in a repository.

        Args:
            repository: Path to Mamplan repository directory.
            yes: If True, skip confirmation prompt.
            throw_error: If True, disable error tolerance.
            selection: Key-value filters (AND-combined).
            regex_selection: Regex filters (AND-combined).
        """
        all_mamplans = load_mamplans(repository)
        all_mamplans = apply_selection(all_mamplans, selection or [], regex_selection or [])
        expired = [m for m in all_mamplans if m.is_expired]

        if not expired:
            typer.echo("No expired deployments found.")
            return

        if not _confirm_mamplans(expired, "stopped (expired)", yes):
            return

        mamplates = load_mamplates(self.config.mamplates_path)
        config = self.config

        def _stop(mamplan: Mamplan) -> None:
            mampok = create_mampok_instance(config, mamplan, mamplates)
            p = _Printer()
            _handle_stop_events(mampok.stop(config), p)
            p.end()
            mamplan.write(mamplan.source_path)
            typer.echo(f"Stopped: {mamplan.data['project']['project_id']}")

        run_with_error_tolerance(expired, _stop, throw_error=throw_error)

    def list_expiring(
        self,
        repository: Path,
        within: timedelta = timedelta(days=7),
    ) -> None:
        """List active deployments expiring within a given window.

        Args:
            repository: Path to Mamplan repository directory.
            within: Time window as timedelta. Default: 7 days.
        """
        all_mamplans = load_mamplans(repository)
        rows = [r for m in all_mamplans if (r := _mamplan_expiry_info(m, within))]

        window_str = f"{within.days}d"
        if not rows:
            typer.echo(f"No deployments expiring within {window_str}.")
            return

        col_id = max(max(len(r["project_id"]) for r in rows), len("Project ID"))
        header = f"{'Project ID':<{col_id}}  {'Lifetime':<26}  Days Remaining"
        typer.echo(header)
        typer.echo("-" * len(header))
        for row in rows:
            typer.echo(f"{row['project_id']:<{col_id}}  {row['lifetime']:<26}  {row['days_remaining']}")

    # I9
    def redeploy(
        self,
        mamplan_path: Path,
        selection: list[str] | None = None,
        regex_selection: list[str] | None = None,
        timeout: int = 300,
        throw_error: bool = False,
        yes: bool = False,
        reupload: bool = False,
    ) -> None:
        """Stop and redeploy one or more projects.

        Args:
            mamplan_path: Path to Mamplan file or directory.
            selection: Key-value selection filters.
            regex_selection: Regex selection filters.
            timeout: Wait-for-ready timeout in seconds.
            throw_error: If True, disable error tolerance.
            yes: If True, skip confirmation prompt.
            reupload: If True, force re-upload of all files to S3.
        """
        mamplans, mamplates = self._load(mamplan_path)
        mamplans = apply_selection(mamplans, selection or [], regex_selection or [])

        if not _confirm_mamplans(mamplans, "redeployed (stop + deploy)", yes):
            return

        config = self.config

        def _redeploy(mamplan: Mamplan) -> None:
            mampok = create_mampok_instance(config, mamplan, mamplates)
            project_id = mamplan.data["project"]["project_id"]
            p = _Printer()
            _handle_stop_events(mampok.stop(config), p)
            p.end()
            mamplan.write(mamplan.source_path)
            typer.echo(f"Stopped: {project_id}")
            _handle_deploy_events(mampok.deploy(config, timeout=timeout, reupload=reupload), p)
            p.end()
            mamplan.write(mamplan.source_path)
            typer.echo(f"Redeployed: {project_id}")

        run_with_error_tolerance(mamplans, _redeploy, throw_error=throw_error)

    # I10
    def edit_mamplan(
        self,
        mamplan_path: Path,
        fields: list[str] | None = None,
        redeploy: bool = False,
        timeout: int = 300,
        throw_error: bool = False,
        yes: bool = False,
    ) -> None:
        """Edit Mamplan fields and optionally redeploy.

        Args:
            mamplan_path: Path to a single Mamplan file.
            fields: Edit tokens as ``section:key:value`` strings.
            redeploy: If True, redeploy after editing.
            timeout: Wait-for-ready timeout (used when redeploy=True).
            throw_error: If True, disable error tolerance.
            yes: If True, skip confirmation prompt.
        """
        mamplan = Mamplan.read_in(mamplan_path)
        expanded_fields = _expand_relative_lifetime(fields or [], mamplan)

        typer.echo(f"Mamplan: {mamplan.data['project']['project_id']}")
        typer.echo("Planned changes:")
        for token in expanded_fields:
            parts = token.split(":", 2)
            if len(parts) == 3:
                section, key, new_value = parts
                old_value = mamplan.data.get(section, {}).get(key, "(not set)")
                typer.echo(f"  {section}.{key}: {old_value!r} → {new_value!r}")
        if redeploy:
            typer.echo("  (will be redeployed after the change)")

        if not yes:
            confirmed = typer.confirm("Continue?")
            if not confirmed:
                typer.echo("Aborted.")
                return

        kwargs = _parse_edit_args(expanded_fields)
        mamplan.edit(**kwargs)
        mamplan.write(mamplan_path)
        typer.echo(f"Saved: {mamplan_path}")

        if redeploy:
            mamplates = load_mamplates(self.config.mamplates_path)
            config = self.config

            def _redeploy(m: Mamplan) -> None:
                mampok = create_mampok_instance(config, m, mamplates)
                p = _Printer()
                _handle_stop_events(mampok.stop(config), p)
                p.end()
                typer.echo(f"Stopped: {m.data['project']['project_id']}")
                _handle_deploy_events(mampok.deploy(config, timeout=timeout), p)
                p.end()
                m.write(mamplan_path)
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
        yes: bool = False,
        selection: list[str] | None = None,
        regex_selection: list[str] | None = None,
    ) -> None:
        """Update the auth secret for one or more projects.

        Derives the user list from service.organization + service.user.
        If 'public' is in organization, uses ['public'].

        Args:
            mamplan_path: Path to Mamplan file or directory.
            throw_error: If True, disable error tolerance.
            yes: If True, skip confirmation prompt.
            selection: Key-value filters (AND-combined).
            regex_selection: Regex filters (AND-combined).
        """
        mamplans, mamplates = self._load(mamplan_path)
        mamplans = apply_selection(mamplans, selection or [], regex_selection or [])

        if not _confirm_mamplans(mamplans, "auth-updated", yes):
            return

        config = self.config

        def _update(mamplan: Mamplan) -> None:
            users = _derive_users(mamplan)
            mampok = create_mampok_instance(config, mamplan, mamplates)
            token_url = mampok.update_auth_secret(users, config)
            typer.echo(
                f"Updated auth: {mamplan.data['project']['project_id']} "
                f"({len(users)} user(s))\nToken URL: {token_url}"
            )

        run_with_error_tolerance(mamplans, _update, throw_error=throw_error)


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
        return parse_lifetime(value).strftime("%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        raise typer.BadParameter(
            f"Invalid lifetime '{value}'. Use relative (30d, 4w, 3m) or ISO 8601 (2026-12-31T00:00:00Z)."
        )


# ---------------------------------------------------------------------------
# Expiring-window helpers
# ---------------------------------------------------------------------------


def _parse_within(value: str) -> timedelta:
    """Parse a relative window string ('7d', '2w', '1m') into a timedelta.

    Args:
        value: Relative string like '7d', '2w', '1m'.

    Returns:
        timedelta corresponding to the window.

    Raises:
        typer.BadParameter: If not a valid relative format.
    """
    match = _RELATIVE_LIFETIME_RE.match(value)
    if not match:
        raise typer.BadParameter(
            f"Invalid --within value '{value}'. Use relative format: 7d, 2w, 1m."
        )
    amount = int(match.group(1))
    unit = match.group(2).lower()
    if unit == "d":
        return timedelta(days=amount)
    elif unit == "w":
        return timedelta(weeks=amount)
    else:
        return timedelta(days=amount * 30)


def _mamplan_expiry_info(mamplan: Mamplan, within: timedelta) -> dict | None:
    """Return expiry info if mamplan is active and expiring within ``within``, else None.

    Args:
        mamplan: Mamplan to inspect.
        within: Window within which the mamplan must expire to be included.

    Returns:
        Dict with project_id, lifetime, days_remaining, or None if not relevant.
    """
    deployment = mamplan.data["deployment"]
    if not deployment.get("status", False):
        return None
    lifetime_str = deployment["lifetime"]
    lifetime = parse_lifetime(lifetime_str)
    delta = lifetime - datetime.now(timezone.utc)
    if timedelta(0) < delta <= within:
        return {
            "project_id": mamplan.data["project"]["project_id"],
            "lifetime": lifetime_str,
            "days_remaining": delta.days,
        }
    return None


# ---------------------------------------------------------------------------
# Typer commands (thin wrappers, I6–I14)
# ---------------------------------------------------------------------------


@app.command(context_settings={"help_option_names": ["--help", "-h"]})
def deploy(
    mamplan: Annotated[Path, typer.Argument(help="Path to mamplan file or directory.")],
    config: Annotated[Path, _OPT_CONFIG],
    selection: Annotated[list[str], _OPT_SELECTION] = [],
    regex_selection: Annotated[list[str], _OPT_REGEX_SELECTION] = [],
    timeout: Annotated[int, _OPT_TIMEOUT] = 300,
    dry_run: Annotated[bool, _OPT_DRY_RUN] = False,
    throw_error: Annotated[bool, _OPT_THROW_ERROR] = False,
    no_cleanup: Annotated[bool, _OPT_NO_CLEANUP] = False,
    yes: Annotated[bool, _OPT_YES] = False,
) -> None:
    """Deploy a project to Kubernetes."""
    logger.info(
        "deploy: mamplan=%s, config=%s, selection=%s, regex_selection=%s, timeout=%s, dry_run=%s, throw_error=%s, no_cleanup=%s, yes=%s",
        mamplan, config, selection, regex_selection, timeout, dry_run, throw_error, no_cleanup, yes,
    )
    cfg = MampokConfig.from_file(config.expanduser())
    CLI(cfg).deploy(
        mamplan,
        selection=selection,
        regex_selection=regex_selection,
        timeout=timeout,
        dry_run=dry_run,
        throw_error=throw_error,
        no_cleanup=no_cleanup,
        yes=yes,
    )


@app.command(context_settings={"help_option_names": ["--help", "-h"]})
def stop(
    mamplan: Annotated[Path, typer.Argument(help="Path to mamplan file or directory.")],
    config: Annotated[Path, _OPT_CONFIG],
    selection: Annotated[list[str], _OPT_SELECTION] = [],
    regex_selection: Annotated[list[str], _OPT_REGEX_SELECTION] = [],
    throw_error: Annotated[bool, _OPT_THROW_ERROR] = False,
    yes: Annotated[bool, _OPT_YES] = False,
    download: Annotated[bool, typer.Option("--download", help="Download S3 data before stopping.")] = False,
    output_dir: Annotated[Optional[Path], typer.Option("--output-dir", "-o", help="Download destination (required when --download is used).")] = None,
) -> None:
    """Stop a deployment (removes K8s resources, S3 remains)."""
    if download and output_dir is None:
        typer.echo("Error: --output-dir is required when --download is set.", err=True)
        raise typer.Exit(code=1)
    logger.info(
        "stop: mamplan=%s, config=%s, selection=%s, regex_selection=%s, throw_error=%s, yes=%s, download=%s, output_dir=%s",
        mamplan, config, selection, regex_selection, throw_error, yes, download, output_dir,
    )
    cfg = MampokConfig.from_file(config.expanduser())
    CLI(cfg).stop(
        mamplan,
        selection=selection,
        regex_selection=regex_selection,
        throw_error=throw_error,
        yes=yes,
        download_before_stop=download,
        download_output_dir=output_dir.expanduser() if output_dir else None,
    )


@app.command(context_settings={"help_option_names": ["--help", "-h"]})
def download(
    mamplan: Annotated[Path, typer.Argument(help="Path to mamplan file or directory.")],
    config: Annotated[Path, _OPT_CONFIG],
    output_dir: Annotated[Path, typer.Option("--output-dir", "-o", help="Download destination directory.")],
    selection: Annotated[list[str], _OPT_SELECTION] = [],
    regex_selection: Annotated[list[str], _OPT_REGEX_SELECTION] = [],
    throw_error: Annotated[bool, _OPT_THROW_ERROR] = False,
    yes: Annotated[bool, _OPT_YES] = False,
) -> None:
    """Download all persistent S3 data for a project to the local filesystem."""
    logger.info(
        "download: mamplan=%s, config=%s, output_dir=%s, selection=%s, regex_selection=%s, throw_error=%s, yes=%s",
        mamplan, config, output_dir, selection, regex_selection, throw_error, yes,
    )
    cfg = MampokConfig.from_file(config.expanduser())
    CLI(cfg).download(
        mamplan,
        output_dir=output_dir.expanduser(),
        selection=selection,
        regex_selection=regex_selection,
        throw_error=throw_error,
        yes=yes,
    )


@app.command(name="stop-expired", context_settings={"help_option_names": ["--help", "-h"]})
def stop_expired(
    repository: Annotated[Path, typer.Argument(help="Path to mamplan repository directory.")],
    config: Annotated[Path, _OPT_CONFIG],
    selection: Annotated[list[str], _OPT_SELECTION] = [],
    regex_selection: Annotated[list[str], _OPT_REGEX_SELECTION] = [],
    yes: Annotated[bool, _OPT_YES] = False,
    throw_error: Annotated[bool, _OPT_THROW_ERROR] = False,
) -> None:
    """Stop all expired active deployments in a repository."""
    logger.info(
        "stop-expired: repository=%s, config=%s, selection=%s, regex_selection=%s, yes=%s, throw_error=%s",
        repository, config, selection, regex_selection, yes, throw_error,
    )
    cfg = MampokConfig.from_file(config.expanduser())
    CLI(cfg).stop_expired(repository, yes=yes, throw_error=throw_error, selection=selection, regex_selection=regex_selection)


@app.command(name="list-expiring", context_settings={"help_option_names": ["--help", "-h"]})
def list_expiring(
    repository: Annotated[Path, typer.Argument(help="Path to mamplan repository directory.")],
    config: Annotated[Path, _OPT_CONFIG],
    within: Annotated[str, typer.Option("--within", help="Alert window: relative (7d, 2w, 1m). Default: 7d.")] = "7d",
) -> None:
    """List active deployments expiring within a given window."""
    logger.info("list-expiring: repository=%s, config=%s, within=%s", repository, config, within)
    cfg = MampokConfig.from_file(config.expanduser())
    CLI(cfg).list_expiring(repository, within=_parse_within(within))


@app.command(context_settings={"help_option_names": ["--help", "-h"]})
def redeploy(
    mamplan: Annotated[Path, typer.Argument(help="Path to mamplan file or directory.")],
    config: Annotated[Path, _OPT_CONFIG],
    selection: Annotated[list[str], _OPT_SELECTION] = [],
    regex_selection: Annotated[list[str], _OPT_REGEX_SELECTION] = [],
    timeout: Annotated[int, _OPT_TIMEOUT] = 300,
    throw_error: Annotated[bool, _OPT_THROW_ERROR] = False,
    yes: Annotated[bool, _OPT_YES] = False,
    reupload: Annotated[bool, _OPT_REUPLOAD] = False,
) -> None:
    """Stop and redeploy a project."""
    logger.info(
        "redeploy: mamplan=%s, config=%s, selection=%s, regex_selection=%s, timeout=%s, throw_error=%s, yes=%s, reupload=%s",
        mamplan, config, selection, regex_selection, timeout, throw_error, yes, reupload,
    )
    cfg = MampokConfig.from_file(config.expanduser())
    CLI(cfg).redeploy(
        mamplan,
        selection=selection,
        regex_selection=regex_selection,
        timeout=timeout,
        throw_error=throw_error,
        yes=yes,
        reupload=reupload,
    )


@app.command(name="edit-mamplan", context_settings={"help_option_names": ["--help", "-h"]})
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
    yes: Annotated[bool, _OPT_YES] = False,
) -> None:
    """Edit mamplan fields and optionally redeploy."""
    logger.info(
        "edit-mamplan: mamplan=%s, config=%s, fields=%s, redeploy=%s, timeout=%s, throw_error=%s, yes=%s",
        mamplan, config, fields, redeploy_after, timeout, throw_error, yes,
    )
    cfg = MampokConfig.from_file(config.expanduser())
    CLI(cfg).edit_mamplan(
        mamplan,
        fields=fields,
        redeploy=redeploy_after,
        timeout=timeout,
        throw_error=throw_error,
        yes=yes,
    )


@app.command(name="create-mamplan", context_settings={"help_option_names": ["--help", "-h"]})
def create_mamplan(
    project_id: Annotated[str, typer.Option(help="Unique project ID.")],
    tool: Annotated[str, typer.Option(help="Tool name (must match a mamplate).")],
    cluster: Annotated[str, typer.Option(help="Target cluster identifier.")],
    output: Annotated[Path, typer.Option(help="Output path (file or directory).")],
    config: Annotated[Path, _OPT_CONFIG],
    owner: Annotated[str | None, typer.Option(help="Project owner username. Required if no --metadata-file with owner is given.")] = None,
    datatype: Annotated[list[str], typer.Option(help="Data types (repeatable). Required if no --metadata-file with datatype is given.")] = [],
    files: Annotated[list[str], typer.Option(help="Files to upload (repeatable).")] = [],
    analyst: Annotated[list[str], typer.Option(help="Analyst usernames (repeatable).")] = [],
    organization: Annotated[list[str], typer.Option(help="Organizations (repeatable).")] = [],
    user: Annotated[list[str], typer.Option(help="User access list (repeatable).")] = [],
    metadata: Annotated[list[str], typer.Option(help="Metadata IDs (repeatable).")] = [],
    metadata_file: Annotated[list[Path], typer.Option(help="YAML metadata file(s) to populate the service section (repeatable).")] = [],
    bucket: Annotated[str, typer.Option(help="S3 bucket name (auto-generated if empty).")] = "",
    auth: Annotated[bool, typer.Option(help="Enable login protection.")] = False,
    custom_url_id: Annotated[Optional[str], typer.Option(help="Custom URL path segment replacing project-id in the deployment URL. If omitted, project-id is used.")] = None,
) -> None:
    """Create a new mamplan file."""
    yaml_svc = parse_metadata_files(metadata_file) if metadata_file else {}

    resolved_owner = owner or yaml_svc.get("owner", "")
    if not resolved_owner:
        raise typer.BadParameter(
            "Provide either --owner or a --metadata-file with an owner field.",
            param_hint="'--owner'",
        )

    resolved_datatype = _merge_unique(datatype, yaml_svc.get("datatype", []))
    if not resolved_datatype:
        raise typer.BadParameter(
            "Provide either --datatype or a --metadata-file with a datatype field.",
            param_hint="'--datatype'",
        )

    logger.info(
        "create-mamplan: project_id=%s, tool=%s, cluster=%s, output=%s, "
        "owner=%s, datatype=%s, auth=%s, metadata_file=%s",
        project_id, tool, cluster, output, resolved_owner, resolved_datatype, auth, metadata_file,
    )
    cfg = MampokConfig.from_file(config.expanduser())

    mamplates = load_mamplates(cfg.mamplates_path)
    if tool not in mamplates:
        raise typer.BadParameter(
            f"No Mamplate found for tool '{tool}' in {cfg.mamplates_path}. "
            f"Available: {sorted(mamplates)}",
            param_hint="'--tool'",
        )
    if cluster not in cfg.clusters:
        raise typer.BadParameter(
            f"Cluster '{cluster}' not in config. "
            f"Available: {sorted(cfg.clusters)}",
            param_hint="'--cluster'",
        )

    creation_date = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
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
            "lifetime": creation_date,  # placeholder; deploy overwrites with now + lifetime_days
            "bucket": bucket,
            "url": "",
            "auth": auth,
            **({"custom_url_id": custom_url_id} if custom_url_id else {}),
        },
        service={
            "analyst": _merge_unique(analyst, yaml_svc.get("analyst", [])) or [resolved_owner],
            "owner": resolved_owner,
            "organization": _merge_unique(organization, yaml_svc.get("organization", [])),
            "user": user,
            "datatype": resolved_datatype,
            "metadata": _merge_unique(metadata, yaml_svc.get("metadata", [])),
        },
    )


@app.command(name="check-status", context_settings={"help_option_names": ["--help", "-h"]})
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


@app.command(name="update-auth", context_settings={"help_option_names": ["--help", "-h"]})
def update_auth(
    mamplan: Annotated[Path, typer.Argument(help="Path to mamplan file or directory.")],
    config: Annotated[Path, _OPT_CONFIG],
    selection: Annotated[list[str], _OPT_SELECTION] = [],
    regex_selection: Annotated[list[str], _OPT_REGEX_SELECTION] = [],
    throw_error: Annotated[bool, _OPT_THROW_ERROR] = False,
    yes: Annotated[bool, _OPT_YES] = False,
) -> None:
    """Update the auth secret for a project."""
    logger.info(
        "update-auth: mamplan=%s, config=%s, selection=%s, regex_selection=%s, throw_error=%s, yes=%s",
        mamplan, config, selection, regex_selection, throw_error, yes,
    )
    cfg = MampokConfig.from_file(config.expanduser())
    CLI(cfg).update_auth(mamplan, throw_error=throw_error, yes=yes, selection=selection, regex_selection=regex_selection)


