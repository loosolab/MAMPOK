# Auth 503 Bug Analysis (korrigiert)

## Status

- Gatekeeper erreichbar: ✓
- Auth-Check funktioniert: kein Token → "No access", mit Token → geht durch
- MIT Token → 503 (nach erfolgreicher Auth)
- Deploy meldet "done" obwohl 503 beim Zugriff
- Volumes + Dateien im Pod: ✓ (volume override kein Problem in diesem Fall)

---

## Bug 1 (Ursache des 503): REDIRECT_URL fehlt Namespace

**Datei:** `src/mampok/kubernetes/builder.py`, Zeile 167–171

**Code:**
```python
redirect_url = (
    "/"
    if "nginx.ingress.kubernetes.io/proxy-redirect-to" in cfg.auth_annotations
    else f"/{cfg.project_id}/{cfg.tool}/"
)
```

**Problem:**
Der Gatekeeper validiert den Token und redirectet anschließend auf `REDIRECT_HOST + REDIRECT_URL`.
Mit den aktuellen Werten für `test-mampok-v2`:

- `REDIRECT_HOST` = `https://bioinformatics-cluster.mpi-bn.mpg.de`
- `REDIRECT_URL` = `/test-mampok-v2/cxgtest/` ← **Namespace `mampok-dev1` fehlt!**

→ Browser wird zu `https://host/test-mampok-v2/cxgtest/` umgeleitet.
→ nginx hat keine Ingress-Regel für diesen Pfad (Regel gilt für `/mampok-dev1/test-mampok-v2/cxgtest/`) → **503**.

**Fix:**
`urlparse` ist bereits importiert (`from urllib.parse import urlparse`, Zeile 8).
REDIRECT_URL direkt aus `cfg.url` ableiten:

```python
redirect_url = (
    "/"
    if "nginx.ingress.kubernetes.io/proxy-redirect-to" in cfg.auth_annotations
    else urlparse(cfg.url).path
)
```

`urlparse("https://host/mampok-dev1/test-mampok-v2/cxgtest/").path`
→ `/mampok-dev1/test-mampok-v2/cxgtest/` ✓

---

## Bug 2 (deploy meldet "done" obwohl 503): ReadinessProbe prüft nicht die volle Auth-Kette

**Betroffene Dateien:** Mamplate-Definition + `src/mampok/kubernetes/manager.py`

**Problem:**
`wait_for_ready` wartet auf `ready_replicas >= cfg.replicas`. Die Pod-Readiness basiert auf dem
ReadinessProbe des Main-Containers (cellxgene):

```json
"readinessProbe": {
    "httpGet": {"path": "/", "port": 5005},
    "initialDelaySeconds": 10,
    "periodSeconds": 10,
    "failureThreshold": 6
}
```

Dieser Probe prüft cellxgene direkt auf Port 5005 — **ohne** den Gatekeeper. Deploy meldet "done"
sobald cellxgene auf Port 5005 antwortet. Dass der vollständige Zugang via URL+Token
(Gatekeeper → Cellxgene) klappt, wird nicht geprüft.

**Anforderung:**
ReadinessProbe soll immer auf den **Main-Container** zeigen. Ideal wäre eine Prüfung, die
Zugang via URL+Token verifiziert — das erfordert aber einen dynamischen Token im Probe, was
nicht praktikabel ist.

**Praktischer Fix:** Probe-Pfad anpassen auf einen Endpoint, der erst antwortet wenn cellxgene
die Daten vollständig geladen hat (z.B. `/api/config` statt `/`). Damit gilt der Pod erst als
"ready" wenn cellxgene wirklich bedient.

Offen: Welcher Endpoint ist der verlässlichste "Daten geladen"-Indikator für cellxgene 1.0.0?

---

## Randnotiz: Volume-Override (kein Funktionsfehler im aktuellen Fall)

In `build_deployment` (Zeile 155–156) überschreibt `cfg.volumes` alle vorher durch s3download
angesammelten Volumes:

```python
if cfg.volumes:
    pod_spec["volumes"] = cfg.volumes  # ersetzt alle bisherigen Volumes
```

Dies geschieht **vor** dem Auth-Block (Zeile ~194), der das auth-secret-Volume erst danach
anhängt. Im aktuellen Fall kein Problem:
- `cfg.volumes = [{"name": "filedir", "emptyDir": {}}]` (gleicher Inhalt wie s3download hinzufügt)
- Auth-Volume wird korrekt **nach** dem Override angehängt → [filedir, auth-volume] ✓

Latentes Problem: Custom-Init-Container-Volumes, die zwischen s3download und dem Override
hinzugefügt werden, gehen verloren. Langfristig sollte der Override durch einen Merge ersetzt
werden.

---

## Zusammenfassung

| # | Problem | Datei | Ursache | Fix |
|---|---------|-------|---------|-----|
| 1 | **503 nach Token-Auth** | `builder.py:167` | `REDIRECT_URL` ohne Namespace | `urlparse(cfg.url).path` |
| 2 | **deploy → "done" trotz 503** | Mamplate + `manager.py` | ReadinessProbe prüft nicht volle Auth-Kette | Probe-Pfad verbessern |
| 3 | Volume-Override | `builder.py:155` | Replace statt Merge | Minor, kein Fehler im aktuellen Case |
