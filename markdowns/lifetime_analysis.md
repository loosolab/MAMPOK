# Mamplan Lifetime — Analysis & Feature Planning

> Date: 2026-03-26
> Branch: dev
> Purpose: Document current lifetime logic, identify gaps, and prepare a planning discussion for improvements.

---

## 1. What is a Mamplan?

A Mamplan is a per-project JSON configuration file (`{project_id}-mamplan.json`) that describes how a bioinformatics tool is deployed on Kubernetes. It has four top-level sections: `project`, `deployment`, `service`, and optionally `container` and `tags`.

**Key deployment fields (relevant to this analysis):**

| Field | Type | Description |
|---|---|---|
| `cluster` | string | Target cluster |
| `status` | boolean | Whether the deployment is currently active |
| `lifetime` | ISO 8601 datetime string | Expiration timestamp for the deployment |
| `bucket` | string | S3 bucket (persists beyond lifetime) |

---

## 2. How Lifetime is Defined

**Schema location:** `src/mampok/mamplan/schemas/mamplan_schema.json`

```json
"lifetime": {
  "type": "string",
  "format": "date-time"
}
```

- Type: ISO 8601 UTC datetime string (e.g. `"2025-12-31T00:00:00Z"`)
- Required in the `deployment` section — no schema-level default
- CLI creation (`mampok create-mamplan`) accepts relative shorthand: `30d`, `4w`, `3m`
- Relative values are converted to absolute UTC datetime at creation time
- `config.lifetime_days` exists in the config (e.g. 30 days) as a reference value — **but it is never automatically applied**

---

## 3. How Expiration is Detected

**Core property:** `Mampok.is_expired` in `src/mampok/mampok/mampok.py:62`

```python
@property
def is_expired(self):
    if not deployment["status"]:
        return False  # inactive deployments are never "expired"
    lifetime = datetime.fromisoformat(deployment["lifetime"])
    if lifetime.tzinfo is None:
        lifetime = lifetime.replace(tzinfo=timezone.utc)
    return lifetime < datetime.now(timezone.utc)
```

**Rule:** A Mamplan is considered expired only if:
1. `deployment.status == True` (currently active), AND
2. `lifetime < datetime.now(UTC)`

The same logic is duplicated in `src/mampok/interfaces/api.py:394` and `src/mampok/interfaces/cli.py:776`.

---

## 4. What Happens When a Deployment Expires

Expiration does **not** trigger automatically. It must be invoked manually or via an external cron job.

### Stopping Flow

1. **Detection:** Scan all Mamplan files in a repository directory, filter by `is_expired`
2. **Confirmation:** User is prompted unless `-Y/--yes` flag is passed
3. **K8s cleanup** (`Mampok.stop()` in `src/mampok/mampok/mampok.py:172`):
   - Deletes Kubernetes Deployment
   - Deletes Kubernetes Service
   - Deletes Kubernetes Ingress
   - Deletes auth Secret (if auth-protected)
4. **Mamplan update:** `deployment.status` is set to `False` and written to disk
5. **S3 data is NOT touched** — bucket and files remain

### Trigger Points

| Interface | Command / Method | Notes |
|---|---|---|
| CLI | `mampok stop-expired <path> [-Y]` | `src/mampok/interfaces/cli.py:521` |
| Python API | `API.stop_expired(repository)` | `src/mampok/interfaces/api.py:144` |
| Recommended external pattern | `cron` calling `mampok stop-expired /data/mamplans/ -Y` | Documented in README |

---

## 5. Where Lifetime Can Be Edited

| Interface | Mechanism | Location |
|---|---|---|
| CLI (at creation) | `--lifetime 30d` | `cli.py:955` |
| CLI (after creation) | `mampok edit-mamplan <path> -e deployment:lifetime:2025-12-31T00:00:00Z` | `cli.py:595` |
| Python API (dedicated) | `API.edit_lifetime(mamplan_path, lifetime="...")` | `api.py:236` |
| Python API (generic) | `API.edit_mamplan(..., deployment__lifetime="...")` | `api.py:195` |

No web UI exists for editing lifetime.

---

## 6. Identified Gaps

### G1 — No Built-in Scheduler (Critical)
Expiration enforcement is entirely passive. If no external cron job is configured, expired deployments run indefinitely. The infrastructure cost impact is real and unmanaged.

### G2 — `config.lifetime_days` is Never Used
A `lifetime_days` value exists in config but is never applied as a default when creating a Mamplan. Users must always provide lifetime explicitly or forget it entirely.

### G3 — No Pre-expiration Warnings
There is no mechanism to warn users (by any channel) that a deployment is approaching its expiration. Deployments silently expire.

### G4 — No Validation: Lifetime in the Past at Deploy Time
A Mamplan can be deployed even if its `lifetime` is already in the past. No warning or error is raised at deploy time.

### G5 — Duplicated Expiration Logic
`_is_mamplan_expired()` is implemented identically in three places: `mampok.py`, `api.py`, `cli.py`. This creates a maintenance risk — future changes could diverge.

### G6 — No Audit Trail
No logging of expiration events. No `stopped_at` timestamp in the Mamplan. No record of who/when triggered a stop-expired run.

### G7 — No S3 Lifecycle Management
`lifetime` only governs K8s resources. S3 buckets and data accumulate indefinitely, independent of deployment lifetime.

### G8 — No Activity-aware Extension
No mechanism to detect that a deployment is actively in use and delay or extend expiration automatically.

### G9 — Potential Status Inconsistency on Stop Failure
If `kube.delete()` fails mid-operation, `mamplan.status` may not be updated. No transactional guarantee between the K8s operation and the Mamplan file write.

### G10 — No Relative Lifetime Editing
`edit-mamplan` and `API.edit_lifetime()` accept only absolute datetimes. There is no shorthand for "extend by 2 weeks" as there is at creation time.

---

## 7. Summary Table

| Area | Status | Notes |
|---|---|---|
| Lifetime field in schema | Implemented | ISO 8601 string, required |
| Expiration detection logic | Implemented | `is_expired` property |
| Manual stop-expired CLI | Implemented | `mampok stop-expired` |
| API for stopping expired | Implemented | `API.stop_expired()` |
| Lifetime editing (CLI/API) | Implemented | Absolute datetime only post-creation |
| Built-in scheduler | **Missing** | Must use external cron |
| Default lifetime from config | **Missing** | `config.lifetime_days` unused |
| Pre-expiration warnings | **Missing** | No notification system |
| Validation at deploy time | **Missing** | Can deploy already-expired mamplan |
| Expiration logic DRY | **Missing** | Tripled across files |
| Audit trail / timestamps | **Missing** | No `stopped_at`, no logs |
| S3 lifecycle management | **Missing** | Buckets never cleaned up |
| Relative lifetime extension | **Missing** | Only available at creation |

---

## 8. Discussion Topics & Feature Ideas

The following are candidates for the planning phase. Each addresses one or more gaps above.

### A. Apply `config.lifetime_days` as Default at Creation (G2)
When `--lifetime` is not provided at `mampok create-mamplan`, fall back to `config.lifetime_days` to compute a default lifetime. Fail explicitly if neither is set.

### B. Warn on Deploy if Lifetime is in the Past (G4)
At `mampok deploy`, check if `deployment.lifetime < now()` and raise a warning (or error with `--force` override).

### C. Deduplicate Expiration Logic (G5)
Move `_is_mamplan_expired` into the `Mamplan` class (already exists as `Mampok.is_expired`) and remove the duplicates in `api.py` and `cli.py`.

### D. Add `stopped_at` Field to Mamplan on Stop (G6)
When stopping a deployment (expired or manual), write a `deployment.stopped_at` ISO 8601 timestamp to the Mamplan. Enables audit, reporting, and "time-since-stopped" queries.

### E. Pre-expiration Warning Command (G3)
Add a `mampok list-expiring [--within 7d]` CLI command that lists active deployments expiring within a given window. Can be called from cron or integrated into a notification pipeline.

### F. Relative Lifetime Extension via CLI (G10)
Allow `mampok edit-mamplan <path> -e deployment:lifetime:+14d` to extend lifetime by a relative offset from the current lifetime value (not from now).

### G. S3 Bucket Expiry Policy (G7)
When stopping a deployment, optionally set an S3 Object Lifecycle policy on the bucket to expire objects after N days (configurable). Could be opt-in per Mamplan.

### H. Built-in Expiry Daemon / Watcher (G1) — larger scope
A background process (`mampok watch --interval 1h`) that periodically runs the expiry check and stops expired deployments without requiring an external cron setup. Could be run as a sidecar or separate service.

### I. Transactional Stop with Rollback (G9)
Ensure that if the K8s delete fails, the Mamplan `status` is not set to `False`. Current implementation may leave inconsistency. Consider checking K8s resource state before writing Mamplan.

---

## 9. Recommended Priority

| Priority | Item | Effort | Impact |
|---|---|---|---|
| High | C — Deduplicate expiration logic | Low | Maintainability |
| High | A — Apply `config.lifetime_days` default | Low | UX / safety |
| High | B — Warn on deploy if lifetime in past | Low | UX / safety |
| High | D — Add `stopped_at` field | Low | Audit |
| Medium | E — `list-expiring` command | Medium | Ops visibility |
| Medium | F — Relative lifetime extension | Medium | UX |
| Medium | I — Transactional stop | Medium | Correctness |
| Low | G — S3 lifecycle policy | Medium | Cost / storage |
| Low | H — Built-in watcher daemon | High | Automation |
