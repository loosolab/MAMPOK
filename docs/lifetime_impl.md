# Plan: Mamplan Lifetime Improvements

## Context

The `deployment.lifetime` field exists in every Mamplan but is only passively enforced via a manual `mampok stop-expired` command. Analysis (see `docs/lifetime_analysis.md`) revealed 10 gaps. This plan addresses 6 of them.

**Key design decision (clarified):** Lifetime is meaningless on a created-but-undeployed Mamplan. Every `deploy` call should **reset** `lifetime = now() + config.lifetime_days` — a "lease renewal" model. This ensures deployments always have a fresh, config-driven expiry window regardless of what was written at creation time.

---

## Implementation Order

### 1. Feature C — Deduplicate Expiration Logic (foundation)

**Problem:** `_is_mamplan_expired()` is copy-pasted identically in `cli.py:776` and `api.py:394`. `Mampok.is_expired` (mampok.py:62) has the same logic a third time.

**Changes:**

`src/mampok/mamplan/mamplan.py` — add `is_expired` property to `Mamplan` class (requires adding `from datetime import datetime, timezone`):

```python
@property
def is_expired(self) -> bool:
    deployment = self.data["deployment"]
    if not deployment.get("status", False):
        return False
    lifetime = datetime.fromisoformat(deployment["lifetime"])
    if lifetime.tzinfo is None:
        lifetime = lifetime.replace(tzinfo=timezone.utc)
    return lifetime < datetime.now(timezone.utc)
```

`src/mampok/mampok/mampok.py:62` — delegate to `self.mamplan.is_expired`:

```python
@property
def is_expired(self) -> bool:
    return self.mamplan.is_expired
```

`src/mampok/interfaces/cli.py` — delete `_is_mamplan_expired()` (line 776–791); replace call at line 535 with `m.is_expired`

`src/mampok/interfaces/api.py` — delete `_is_mamplan_expired()` (line 394–409); replace call at line 151 with `m.is_expired`; remove now-unused `datetime`/`timezone` import if no other usages remain

**Tests:**

- `tests/test_mamplan/test_mamplan.py`: new `TestMamplanIsExpired` — 5 cases: expired+active→True, not-expired+active→False, inactive+past→False, tz-naive→True, tz-aware future→False
- `tests/test_mampok/test_mampok.py`: replace `TestIsExpired` with 2 delegation tests (set `mampok.mamplan.is_expired = True/False`, assert `mampok.is_expired` matches)
- `tests/test_interfaces/test_api.py`: fix import if `_is_mamplan_expired` was directly imported

---

### 2. Feature B (revised) — Deploy Always Resets Lifetime from Config

**Design:** Every successful deploy sets `deployment.lifetime = now() + config.lifetime_days`. Lifetime written at create time is irrelevant and gets overwritten. This is a lease-renewal model.

**Change location:** `src/mampok/mampok/mampok.py:deploy()` — the final `mamplan.edit()` call at end of method (line ~167):

Current:

```python
self.mamplan.edit(deployment__status=True, deployment__url=cfg.url)
```

New:

```python
new_lifetime = datetime.now(timezone.utc) + timedelta(days=config.lifetime_days)
self.mamplan.edit(
    deployment__status=True,
    deployment__url=cfg.url,
    deployment__lifetime=new_lifetime.strftime("%Y-%m-%dT%H:%M:%SZ"),
)
```

`config.lifetime_days` is always valid (required in config schema with `minimum: 1`). `timedelta` must be imported in `mampok.py` — check existing imports; if missing, add `from datetime import datetime, timedelta, timezone`.

The `config` parameter (`MampokConfig`) is already passed into `deploy()` — no signature change needed.

**Tests:**

- `tests/test_mampok/test_mampok.py`: add to `TestDeploy` — after `list(mampok.deploy(mock_config))`, verify `mamplan.edit` was called with `deployment__lifetime` key; parsed lifetime is in the future; parsed lifetime is approximately `now() + config.lifetime_days`

---

### 3. Feature A — Remove `--lifetime` from `create-mamplan`

**Design:** Lifetime has no effect on an undeployed Mamplan (deploy always resets it from config). Remove the `--lifetime` parameter entirely — no optional, no fallback.

**Context from new commit (`60906a4`):** The commit added tool/cluster validation in the CLI command body. The `--lifetime` parameter and `_parse_lifetime(lifetime)` call are still present and must be removed as part of this feature.

**Changes:**

`src/mampok/interfaces/cli.py:create_mamplan` command (~line 955) — remove the `lifetime` parameter from the command signature entirely.

`src/mampok/interfaces/cli.py:create_mamplan` command body (~line 1012) — replace:

```python
creation_date = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
lifetime = _parse_lifetime(lifetime)
CLI(cfg).create_mamplan(
    ...
    deployment={..., "lifetime": lifetime, ...},
    ...
)
```

With:

```python
creation_date = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
CLI(cfg).create_mamplan(
    ...
    deployment={..., "lifetime": creation_date, ...},  # placeholder; deploy overwrites
    ...
)
```

Using `creation_date` (= `now()`) as the placeholder makes it immediately "expired" — clearly not an intentional expiry. Deploy will overwrite with `now() + config.lifetime_days` on first run.

`src/mampok/interfaces/api.py:create_mamplan()` — check if `lifetime` is accepted as part of the `deployment` kwarg; if the API caller omits it, set `deployment["lifetime"]` to `datetime.now(UTC).strftime(...)` in the method before calling `Mamplan.create()`. This keeps the API callable without requiring the caller to supply a meaningful lifetime.

Note: `_parse_lifetime()` itself is NOT removed — it is still needed for Feature F (relative offset parsing in `edit-mamplan`).

**Tests:**

- `tests/test_interfaces/test_cli.py`: test that `create-mamplan` succeeds without a `--lifetime` flag; verify the created mamplan has a valid ISO datetime in `deployment.lifetime`

---

### 4. Feature E — `list-expiring` Command

**New read-only command showing active deployments expiring within a window.**

**New helpers** in `src/mampok/interfaces/cli.py` (insert near other `_parse_*` helpers):

```python
def _parse_within(value: str) -> timedelta:
    """Parse '7d', '2w', '1m' into a timedelta for the --within window."""
    match = _RELATIVE_LIFETIME_RE.match(value)
    if not match:
        raise typer.BadParameter(f"Invalid --within '{value}'. Use: 7d, 2w, 1m.")
    amount = int(match.group(1))
    unit = match.group(2).lower()
    if unit == "d": return timedelta(days=amount)
    if unit == "w": return timedelta(weeks=amount)
    return timedelta(days=amount * 30)

def _mamplan_expiry_info(mamplan: Mamplan, within: timedelta) -> dict | None:
    """Return expiry info if mamplan is active and expiring within `within`, else None."""
    deployment = mamplan.data["deployment"]
    if not deployment.get("status", False):
        return None
    lifetime_str = deployment["lifetime"]
    lifetime = datetime.fromisoformat(lifetime_str)
    if lifetime.tzinfo is None:
        lifetime = lifetime.replace(tzinfo=timezone.utc)
    delta = lifetime - datetime.now(timezone.utc)
    if timedelta(0) < delta <= within:
        return {
            "project_id": mamplan.data["project"]["project_id"],
            "lifetime": lifetime_str,
            "days_remaining": delta.days,
        }
    return None
```

**New `CLI.list_expiring()` method** (after `CLI.stop_expired`):

```python
def list_expiring(self, repository: Path, within: timedelta = timedelta(days=7)) -> None:
    all_mamplans = load_mamplans(repository)
    rows = [r for m in all_mamplans if (r := _mamplan_expiry_info(m, within))]
    if not rows:
        typer.echo(f"No deployments expiring within {within.days}d.")
        return
    col_id = max(max(len(r["project_id"]) for r in rows), len("Project ID"))
    header = f"{'Project ID':<{col_id}}  {'Lifetime':<26}  Days Remaining"
    typer.echo(header)
    typer.echo("-" * len(header))
    for row in rows:
        typer.echo(f"{row['project_id']:<{col_id}}  {row['lifetime']:<26}  {row['days_remaining']}")
```

**New typer command** (after `stop-expired` command, ~line 899):

```python
@app.command(name="list-expiring")
def list_expiring(
    repository: Annotated[Path, typer.Argument(help="Path to mamplan repository directory.")],
    config: Annotated[Path, _OPT_CONFIG],
    within: Annotated[str, typer.Option("--within", help="Window: 7d, 2w, 1m. Default: 7d.")] = "7d",
) -> None:
    """List active deployments expiring within a given window."""
    logger.info("list-expiring: repository=%s, config=%s, within=%s", repository, config, within)
    cfg = MampokConfig.from_file(config.expanduser())
    CLI(cfg).list_expiring(repository, within=_parse_within(within))
```

**New `API.list_expiring()`** in `src/mampok/interfaces/api.py`:

```python
def list_expiring(self, repository: Path, within_days: int = 7) -> list[dict]:
    """Return active deployments expiring within within_days days.

    Returns list of dicts: [{"project_id": str, "lifetime": str, "days_remaining": int}]
    """
    from mampok.interfaces.cli import _mamplan_expiry_info, load_mamplans
    within = timedelta(days=within_days)
    return [r for m in load_mamplans(Path(repository)) if (r := _mamplan_expiry_info(m, within))]
```

**Filter logic boundaries:**

- `delta <= 0` → already expired → excluded (belongs to `stop-expired`)
- `delta > within` → too far out → excluded
- `status=False` → inactive → excluded

**Tests:**

- `tests/test_interfaces/test_api.py`: new `TestAPIListExpiring` — active/expiring-soon included; inactive excluded; already-expired excluded; beyond-window excluded; empty repo returns `[]`
- `tests/test_interfaces/test_cli.py`: new `TestMamplanExpiryInfo` — unit tests for the helper

---

### 5. Feature F — Relative Lifetime Extension in `edit-mamplan`

**Syntax:** `mampok edit-mamplan <path> -e deployment:lifetime:+14d`
**Design:** The offset is added to the **existing** `deployment.lifetime` (not `now()`). The API always receives an ISO string — relative parsing is CLI-only.

**New regex + helper** in `src/mampok/interfaces/cli.py` (after `_parse_edit_args`, ~line 380):

```python
_RELATIVE_OFFSET_RE = re.compile(r"^\+(\d+)([dwm])$", re.IGNORECASE)

def _expand_relative_lifetime(fields: list[str], mamplan: Mamplan) -> list[str]:
    """Expand '+Nd/w/m' offset tokens in deployment:lifetime to absolute ISO 8601."""
    result = []
    for token in fields:
        parts = token.split(":", 2)
        if len(parts) == 3 and parts[0] == "deployment" and parts[1] == "lifetime":
            match = _RELATIVE_OFFSET_RE.match(parts[2])
            if match:
                amount = int(match.group(1))
                unit = match.group(2).lower()
                delta = {"d": timedelta(days=amount), "w": timedelta(weeks=amount),
                         "m": timedelta(days=amount * 30)}[unit]
                existing = datetime.fromisoformat(
                    mamplan.data["deployment"]["lifetime"].replace("Z", "+00:00")
                )
                new_iso = (existing + delta).strftime("%Y-%m-%dT%H:%M:%SZ")
                result.append(f"deployment:lifetime:{new_iso}")
                continue
        result.append(token)
    return result
```

`src/mampok/interfaces/cli.py:CLI.edit_mamplan()` (line ~608) — insert one line before `_parse_edit_args`:

```python
mamplan = Mamplan.read_in(mamplan_path)
expanded_fields = _expand_relative_lifetime(fields or [], mamplan)  # ← new
kwargs = _parse_edit_args(expanded_fields)
mamplan.edit(**kwargs)
mamplan.write(mamplan_path)
```

**API layer:** `API.edit_lifetime()` already exists and accepts an ISO string. No new API method needed — callers compute the absolute datetime themselves before calling. The existing `API.edit_mamplan(path, deployment__lifetime="2026-12-31T00:00:00Z")` pattern is sufficient.

**Tests:**

- `tests/test_interfaces/test_cli.py`: new `TestExpandRelativeLifetime` — `+14d` extends existing lifetime by 14 days (not from now); `+2w` correct; non-lifetime token passes through; absolute ISO token passes through; mixed list only transforms the lifetime token

---

### 6. Feature I — Transactional Stop (Better Error Handling)

**Problem:** `DeploymentManager.delete()` fails fast on the first error, leaving remaining K8s resources (Service, Ingress, Secrets) undeleted and giving no detail about which resource failed.

**Change:** `src/mampok/kubernetes/manager.py:DeploymentManager.delete()` (line 60) — attempt all resources, collect failures, raise composite:

```python
def delete(self, cfg: DeploymentConfig) -> None:
    logger.debug("delete: project_id=%s", cfg.project_id)
    resources = [
        ("Deployment", cfg.deployment_name),
        ("Service", cfg.service_name),
        ("Ingress", cfg.ingress_name),
        ("Secret", cfg.secret_name),
        ("Secret", cfg.auth_secret_name),
    ]
    failures = []
    for kind, name in resources:
        try:
            self._kube.delete(kind, name)
        except Exception as exc:
            logger.warning("failed to delete %s/%s: %s", kind, name, exc)
            failures.append((kind, name, exc))
    if failures:
        details = "; ".join(f"{k}/{n}: {e}" for k, n, e in failures)
        raise RuntimeError(
            f"Failed to delete {len(failures)} resource(s) for '{cfg.project_id}': {details}"
        )
```

`src/mampok/mampok/mampok.py:stop()` — add explicit try/except to document the invariant:

```python
def stop(self, config: MampokConfig) -> None:
    cfg = self._build_deployment_config(config)
    logger.debug("stop: project_id=%s, namespace=%s", cfg.project_id, cfg.namespace)
    try:
        self.kube.delete(cfg)
    except Exception:
        logger.error("stop failed for '%s' — mamplan status NOT updated", cfg.project_id)
        raise
    self.mamplan.edit(deployment__status=False)
```

Mamplan status stays `True` on delete failure — preserving the accurate reflection of actual K8s state.

**Tests:**

- `tests/test_kubernetes/test_manager.py`: new `TestDeploymentManagerDelete` — all 5 resources attempted even when first fails; `RuntimeError` lists failure count; success case no raise
- `tests/test_mampok/test_mampok.py`: new `TestStopTransactional` — `mamplan.edit` NOT called when delete fails; IS called when delete succeeds; exception re-raised

---

## Recent Commit Context

Commit `60906a4` ("update create-mamplan") added:

- Tool/cluster validation in both `CLI.create_mamplan` command and `API.create_mamplan()` — plan must not break these
- `bucket` schema pattern changed to `^[^A-Z_]*$` (empty string now valid)
- `metadata.py`: `nerd` field is now a list of dicts (unrelated to lifetime)

The `--lifetime` parameter is still present and required in the current CLI — Feature A removes it.

---

## Critical Files Summary

| File                                    | Features                                                                                                     |
| --------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| `src/mampok/mamplan/mamplan.py`         | C (add `is_expired`)                                                                                         |
| `src/mampok/mampok/mampok.py`           | C (delegate `is_expired`), B (lifetime reset on deploy), I (stop error handling)                             |
| `src/mampok/interfaces/cli.py`          | C (remove duplicate), A (`--lifetime` optional), E (new command+helpers), F (new helper+edit_mamplan change) |
| `src/mampok/interfaces/api.py`          | C (remove duplicate), E (`list_expiring`)                                                                    |
| `src/mampok/kubernetes/manager.py`      | I (continue-on-error delete)                                                                                 |
| `tests/test_mamplan/test_mamplan.py`    | C                                                                                                            |
| `tests/test_mampok/test_mampok.py`      | C, B, I                                                                                                      |
| `tests/test_interfaces/test_api.py`     | C, E                                                                                                         |
| `tests/test_interfaces/test_cli.py`     | A, E, F                                                                                                      |
| `tests/test_kubernetes/test_manager.py` | I                                                                                                            |

---

## Verification

```bash
# Run full test suite
pytest tests/ -v

# Deploy resets lifetime from config
mampok deploy /data/mamplans/proj-mamplan.json --config config.json
# → mamplan file: deployment.lifetime = now + config.lifetime_days

# Create without --lifetime
mampok create-mamplan --project-id test-proj --tool cellxgene --cluster BN \
  --output /tmp/ --owner jdoe --datatype scRNA-seq --config config.json

# List expiring deployments
mampok list-expiring /data/mamplans/ --within 7d --config config.json

# Extend lifetime by relative offset
mampok edit-mamplan /data/mamplans/proj-mamplan.json -e deployment:lifetime:+14d --config config.json
# → adds 14 days to existing deployment.lifetime

# Stop-expired still works as before
mampok stop-expired /data/mamplans/ -Y --config config.json
```
