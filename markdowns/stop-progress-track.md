# Plan: Mampok Stop Progress Tracking → MongoDB

## Context

Beim `mampok stop` gibt es aktuell **kein Fortschritts-Logging in MongoDB**. Deploy-Jobs haben bereits ein `deploy_log`-Feld mit Schritt-für-Schritt-Fortschritt — Stop-Jobs haben nur Status-Codes (0/1/2/3/-1).

Das Ziel:

1. **Stop-Lifecycle-Fortschritt** in MongoDB schreiben (analog zu `deploy_log`)
2. **Letzten Bisync-Stand** aus dem Sidecar-Log auslesen und mit in den Stop-Log schreiben (wie viel ist bereits gesynct, wie viel steht noch aus)
3. **Final-Sync-Output** (rclone copy beim Stop) parsen und strukturiert speichern

---

## Kompletter Mampok Stop Lifecycle (aktuell + neu)

```
[Flask API]
  POST /stopProject
    → MongoDB job erstellt: {job_task: "stop", status: 0}
    → Redis enqueue
    → MongoDB update: {status: 1, job_id: <rq-id>}

[RQ Worker: stop_project_process()]
  → MongoDB: {status: 2, started_at: now}
  → mampok_service.stop_project()

    [mampok_v2: mampok.stop()]
      → kube.delete(cfg)

        [manager.delete()]
          ① Wenn container_data_paths: _final_sync_before_delete()
             → yield {"stage": "s3_final_sync", "status": "starting", "pod": ...}
             → exec_in_pod_stream() — alle 10s partial output
               (rclone copy --stats 10s --log-level INFO)
             → alle 10s: _parse_rclone_stats() → yield "progress"-Event
               {"stage": "s3_final_sync", "status": "progress",
                "transferred_files": 4, "total_files": 12, "transferred_pct": 33}
             → nach Abschluss: yield "done"-Event mit Endwerten

          ② K8s Ressourcen löschen (Reihenfolge):
             Deployment → Service → Ingress → Secret → Auth-Secret
             → yield {"stage": "k8s_delete", "status": "done", "resource": "Kind/name"}

      → mamplan.edit(deployment__status=False)

  NEU: Jedes yield-Event → stop_log["steps"].append(step) → MongoDB flush

  → MongoDB: {status: 3, finished_at: now}
  → Bei Fehler: {status: -1, error: "...", finished_at: now}
```

---

## Implementierung

### Schritt 1 — KubeClient: Streaming-Exec

**Datei:** `mampok_v2/src/mampok/kubernetes/client.py`

Neue Methode `exec_in_pod_stream()` neben dem bestehenden `exec_in_pod()`. Statt `ws.run_forever()` wird `ws.update(timeout=poll_interval)` in einer Schleife aufgerufen. Das gibt uns alle `poll_interval` Sekunden den akkumulierten Output — passend zu rclone's `--stats 10s`.

```python
def exec_in_pod_stream(
    self,
    pod_name: str,
    container: str,
    command: list[str],
    timeout: int = 300,
    poll_interval: int = 10,
) -> Iterator[str]:
    """Wie exec_in_pod(), aber yieldet alle poll_interval Sekunden den
    akkumulierten stdout+stderr — ermöglicht Echtzeit-Fortschritts-Updates.

    Yields:
        Jeweils der vollständige Output bis zum aktuellen Zeitpunkt (kumulativ).
    """
    import time
    import kubernetes.client
    import kubernetes.stream

    v1 = kubernetes.client.CoreV1Api(api_client=self._api_client)
    ws = kubernetes.stream.stream(
        v1.connect_get_namespaced_pod_exec,
        pod_name,
        self._namespace,
        container=container,
        command=command,
        stderr=True, stdin=False, stdout=True, tty=False,
        _preload_content=False,
    )
    parts: list[str] = []
    deadline = time.monotonic() + timeout
    while ws.is_open() and time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        ws.update(timeout=min(poll_interval, remaining))
        if ws.peek_stdout():
            parts.append(ws.read_stdout())
        if ws.peek_stderr():
            parts.append(ws.read_stderr())
        if parts:
            yield "".join(parts)
    # Abschließend restlichen Output einsammeln
    if ws.peek_stdout():
        parts.append(ws.read_stdout())
    if ws.peek_stderr():
        parts.append(ws.read_stderr())
    if parts:
        yield "".join(parts)
```

### Schritt 2 — Rclone-Stats parsen + Streaming Final-Sync

**Datei:** `mampok_v2/src/mampok/kubernetes/manager.py`

**2a. Statische Parse-Hilfsfunktion** (Modul-Ebene, nach den Imports):

```python
import re

def _parse_rclone_stats(output: str) -> dict:
    """Extrahiert Datei-Fortschritt, Bytes, Speed und Elapsed aus rclone --stats-Output."""
    result = {}
    # Dateianzahl-Zeile: "Transferred:    50 / 100, 50%"  (keine Einheit nach den Zahlen)
    m = re.search(r'Transferred:\s+(\d+)\s*/\s*(\d+),\s*(\d+)%\s*(?:\n|$)', output)
    if m:
        result["transferred_files"] = int(m.group(1))
        result["total_files"] = int(m.group(2))
        result["transferred_pct"] = int(m.group(3))
    # Byte-Zeile: "Transferred:    512.0 MiB / 1.024 GiB, 50%, 51.2 MiB/s, ETA 10s"
    m = re.search(
        r'Transferred:\s+([\d.]+\s*\S+)\s*/\s*([\d.]+\s*\S+),\s*\d+%,\s*([\d.]+\s*\S+/s)',
        output,
    )
    if m:
        result["transferred_bytes_human"] = m.group(1)
        result["total_bytes_human"] = m.group(2)
        result["speed"] = m.group(3)
    # "Elapsed time:   30.0s"
    m = re.search(r'Elapsed time:\s+([\d.]+\S+)', output)
    if m:
        result["elapsed"] = m.group(1)
    return result
```

**2b. `_final_sync_before_delete()` umstellen auf Streaming:**

```python
yield {"stage": "s3_final_sync", "status": "starting", "pod": pod_name}
sync_cmd = ["/bin/sh", "-c",
    "rclone copy /sync/ S3:$s3bucket/container_data/ "
    "--transfers 4 --retries 3 --stats 10s --log-level INFO"]
try:
    last_pct = -1
    accumulated = ""
    for accumulated in self._kube.exec_in_pod_stream(
        pod_name=pod_name,
        container=_S3SYNC_SIDECAR_NAME,
        command=sync_cmd,
        timeout=cfg.container_data_sync_timeout,
        poll_interval=10,
    ):
        stats = _parse_rclone_stats(accumulated)
        pct = stats.get("transferred_pct", -1)
        if stats and pct != last_pct:  # nur yielden wenn sich Fortschritt ändert
            last_pct = pct
            yield {"stage": "s3_final_sync", "status": "progress", "pod": pod_name, **stats}

    if accumulated:
        logger.info("final_sync output: %s", accumulated.strip())
    final_stats = _parse_rclone_stats(accumulated)
    yield {"stage": "s3_final_sync", "status": "done", "pod": pod_name, **final_stats}
except Exception as e:
    logger.warning("final_sync: exec failed for %s: %s", cfg.project_id, e)
    yield {"stage": "s3_final_sync", "status": "failed", "reason": str(e)}
```

### Schritt 3 — Stop-Log in Worker schreiben

**Datei:** `bcu-backend-worker/mampok_service.py`

`stop_project()` erhält einen `mongo_db_id`-Parameter und iteriert die Events analog zu `deploy_project()`:

```python
def stop_project(mamplan_path, mongo_db_id, queue_name):
    mamplan_path = os.path.join(mamplan_path)
    config_path = QUEUE_CONFIG_MAP.get(queue_name)
    if not config_path:
        raise RuntimeError(f"No mampok config registered for queue {queue_name}")

    api = MampokAPI(Path(config_path))
    stop_log = {"steps": [], "status": "running"}

    def _flush():
        try:
            mongo_service.update_job_status(
                mongo_db_id, {"stop_log": stop_log}, queue_name
            )
        except Exception as e:
            logger.warning("Failed to update stop_log in MongoDB: %s", e)

    _flush()
    try:
        for step in api.stop(Path(mamplan_path)):
            stop_log["steps"].append(step)
            _flush()
        stop_log["status"] = "done"
        _flush()
    except Exception as e:
        logger.exception("Stop failed for %s: %s", mamplan_path, e)
        stop_log["status"] = "error"
        stop_log["error_message"] = str(e)
        _flush()
        raise
    return "Stopped"
```

**Datei:** `bcu-backend-worker/worker_service.py`

`stop_project_process()` übergibt `mongo_db_id` an `stop_project()`:

```python
def stop_project_process(data, mongo_db_id):
    mamplan_path, project_id = data
    job = get_current_job()
    queue_name = job.origin if job else None
    mongo_service.update_job_status(
        mongo_db_id, {"status": 2, "started_at": datetime.datetime.now()}, queue_name
    )
    mampok_service.stop_project(mamplan_path, mongo_db_id, queue_name)  # mongo_db_id NEU
    mongo_service.update_job_status(
        mongo_db_id, {"status": 3, "finished_at": datetime.datetime.now()}, queue_name
    )
    return "project stopped"
```

Keine Änderungen an `mongo_service.py` nötig — `update_job_status` mit `{"stop_log": ...}` funktioniert mit dem vorhandenen `$set`-Mechanismus.

---

## Neues MongoDB-Dokument-Schema (jobs-Collection, stop-Job)

```json
{
	"job_task": "stop",
	"status": 3,
	"created_at": "...",
	"started_at": "...",
	"finished_at": "...",
	"stop_log": {
		"status": "done",
		"steps": [
			{
				"stage": "s3_final_sync",
				"status": "starting",
				"pod": "my-project-abc123"
			},
			{
				"stage": "s3_final_sync",
				"status": "progress",
				"pod": "my-project-abc123",
				"transferred_files": 4,
				"total_files": 12,
				"transferred_pct": 33,
				"speed": "25.6 MiB/s",
				"elapsed": "10.0s"
			},
			{
				"stage": "s3_final_sync",
				"status": "progress",
				"pod": "my-project-abc123",
				"transferred_files": 8,
				"total_files": 12,
				"transferred_pct": 66,
				"speed": "25.6 MiB/s",
				"elapsed": "20.0s"
			},
			{
				"stage": "s3_final_sync",
				"status": "done",
				"pod": "my-project-abc123",
				"transferred_files": 12,
				"total_files": 12,
				"transferred_pct": 100,
				"transferred_bytes_human": "256 MiB",
				"total_bytes_human": "256 MiB",
				"speed": "25.6 MiB/s",
				"elapsed": "10.0s"
			},
			{
				"stage": "k8s_delete",
				"status": "done",
				"resource": "Deployment/my-project"
			},
			{
				"stage": "k8s_delete",
				"status": "done",
				"resource": "Service/my-project"
			},
			{
				"stage": "k8s_delete",
				"status": "done",
				"resource": "Ingress/my-project"
			},
			{
				"stage": "k8s_delete",
				"status": "done",
				"resource": "Secret/my-project"
			},
			{
				"stage": "k8s_delete",
				"status": "done",
				"resource": "Secret/my-project-auth"
			}
		]
	}
}
```

---

## Kritische Dateien

| Datei                                        | Änderung                                                                       |
| -------------------------------------------- | ------------------------------------------------------------------------------ |
| `mampok_v2/src/mampok/kubernetes/client.py`  | Neue Methode `exec_in_pod_stream()` mit Poll-Schleife                          |
| `mampok_v2/src/mampok/kubernetes/manager.py` | `_parse_rclone_stats()`, `_final_sync_before_delete()` auf Streaming umstellen |
| `bcu-backend-worker/mampok_service.py`       | `stop_project()` mit `mongo_db_id` + Stop-Log-Sammlung                         |
| `bcu-backend-worker/worker_service.py`       | `mongo_db_id` an `stop_project()` übergeben                                    |

---

## Verifikation

1. **Unit-Tests `manager.py`**: Prüfen ob `delete()` ein `s3_bisync_progress`-Event yieldet; Mock `read_pod_logs()` mit rclone-Beispielausgabe, verifizieren parsed dict.
2. **Unit-Tests `mampok_service.py`**: Mock `api.stop()` mit Test-Events, prüfen ob `stop_log["steps"]` korrekt befüllt wird und `update_job_status` aufgerufen wird.
3. **Integration**: Stop-Job ausführen, MongoDB-Dokument prüfen:
   ```python
   db["jobs"].find_one({"job_task": "stop"}, {"stop_log": 1})
   ```
4. **Rclone-Log-Parsing**: Sidecar-Logs nach Stop prüfen — mit `--log-level INFO` sollten "Copied"/"Bisync successful"-Zeilen erscheinen.
