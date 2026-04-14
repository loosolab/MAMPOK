# AWS-CLI vs. rclone in Kubernetes-Pods (mampok_v2)

## Einsatzgebiet

Betrifft ausschließlich die S3-Operationen *innerhalb* der Kubernetes-Pods:

| Rolle | Container | Befehl (aws-cli) |
|---|---|---|
| Download `analysis_data/` beim Pod-Start | `init-container` | `aws s3 cp … --recursive` |
| Restore `container_data/` beim Pod-Start | `init-container-restore` | `aws s3 cp … --recursive \|\| true` |
| Periodischer bidirektionaler Sync | `mampok-s3-sync` Sidecar | `aws s3 sync /sync/ …` (Loop) |
| Letzter Upload vor Stop | exec in Sidecar | `aws s3 sync /sync/ …` (einmalig) |

Die Python-seitige S3-Nutzung (boto3 für Bucket-Management, Upload der Quelldaten)
ist **nicht** Bestandteil dieses Vergleichs.

---

## Volume-Architektur

```
Pod
├── init-container         S3:analysis_data/ → /analysis_data/  (emptyDir)
├── init-container-restore S3:container_data/{path}/ → /app/path/ (emptyDir)
├── main-container         liest /analysis_data/ + schreibt /app/path/ (native Pfade)
└── mampok-s3-sync         /sync/app-path/ ↔ S3:container_data/
                           (selbe emptyDir, gemountet unter /sync/ im Sidecar)
```

---

## Vergleichstabelle: aws-cli vs. rclone copy vs. rclone bisync

| Kriterium | aws-cli | rclone copy | rclone bisync |
|---|---|---|---|
| Image-Größe | ~580 MB | ~25 MB | ~25 MB |
| Checksum-Vergleich (non-AWS S3) | ✗ (nur Größe/Datum) | ✅ `--checksum` | ✅ `--checksum` |
| Retry-Steuerung | minimal | `--retries N --low-level-retries N` | gleich |
| Parallele Transfers | intern, unkontrolliert | `--transfers N` | gleich |
| Bandbreitenlimit | ✗ | `--bwlimit` | gleich |
| Löscht Zieldateien | nein | nein | nein (Konfliktstrategie) |
| Bidirektional | ✗ | ✗ | ✅ |
| Konflikterkennung | ✗ | ✗ | ✅ (State-File) |
| Fortschritt im Log | ✗ | `--stats Ns --log-level INFO` | gleich |
| Symlink-Unterstützung | ✗ (ignoriert) | ✅ `--copy-links` | gleich |
| Concurrent Pods (shared bucket) | ✅ sicher | ✅ sicher | ✗ State-Lock nicht verteilt |
| Multi-Part ETag (> 5 GB) | ✗ (Fehlverhalten mögl.) | ✅ graceful fallback | gleich |
| Non-AWS S3 (MinIO, Ceph) | `--endpoint-url` | `RCLONE_CONFIG_*` | gleich |
| State-File-Risiko | ✅ kein State | ✅ kein State | ✗ (mitigierbar) |
| Wartungszustand | stabil | aktiv | aktiv |

---

## Detaillierte Vor- und Nachteile

### aws-cli — Vorteile

**Erprobte Stabilität**  
`aws s3 sync` und `aws s3 cp` sind jahrelang produktionserprobt. Verhalten bei
Standardfällen ist gut dokumentiert und vorhersagbar.

**`aws s3 sync` löscht standardmäßig nicht**  
Ohne `--delete` werden Zieldateien nie gelöscht. Schützt vor unbeabsichtigtem Datenverlust.

**Kein State-File**  
Vergleicht Größe/Datum ohne State. Kein korrupter State möglich. Jeder Run ist
idempotent ohne Vorwissen über vergangene Syncs.

---

### aws-cli — Nachteile und Edge Cases

**Image-Größe ~580 MB**  
Beim ersten Pull auf einem neuen Node langsam (Spot-Instances, Autoscaling, Node-Cycling).

**Kein Checksum-basierter Vergleich mit non-AWS S3**  
`aws s3 sync` vergleicht nur `LastModified + Size`. Mit MinIO/Ceph:
- Single-Part-Uploads (≤ 5 GB): ETag = MD5 → passt
- Multi-Part-Uploads (> 5 GB): ETag = `{md5_of_parts}-{N}` → aws-cli und MinIO
  uneinig: Datei wird ggf. erneut hochgeladen oder übersprungen obwohl geändert

**Keine Retry-Granularität**  
`--retry` ist auf Hochebene, keine Low-Level-TCP-Retries. Bei kurzem Netzwerkausreißer
(< 1 s) kann ein Transfer scheitern ohne sinnvollen Retry.

**Kein Fortschritt im Log**  
`--only-show-errors` unterdrückt alles außer Fehlern. Diagnose bei hängenden
Init-Containern (großer Download) schwierig.

**Keine Parallelitätskontrolle**  
Kein `--transfers N` Flag. aws-cli entscheidet intern, was bei vielen kleinen Dateien
vs. wenigen großen suboptimal sein kann.

**Unidirektional**  
`aws s3 sync local → S3` überschreibt S3-Objekte immer mit lokalem Stand.
S3-seitige Änderungen während der Pod-Laufzeit gehen beim nächsten Sync verloren.

**Edge Case: Dateinamen mit Sonderzeichen**  
Bekannte Probleme mit `+`, `%`, `#` und Leerzeichen in URL-Encoding-Kontexten.

**Edge Case: Symlinks**  
`aws s3 cp --recursive` folgt Symlinks standardmäßig nicht (Fehler oder stilles
Ignorieren). App-Verzeichnisse mit Symlinks werden unvollständig übertragen.

---

### rclone — Vorteile

**Image ~25 MB (20× kleiner als aws-cli)**  
Relevant bei häufigem Node-Pull oder Image-Registry-Bandbreite-Limits.

**Echter Checksum-Vergleich: `--checksum`**  
MD5/SHA1-Checksums werden verglichen. Bei Multi-Part-Uploads (> 5 GB) fällt rclone
automatisch auf `Size+ModTime` zurück (korrekt, kein Fehler). Zuverlässiger als
`LastModified + Size`.

**Granulare Retry-Kontrolle**  
`--retries 5 --low-level-retries 10`:
- `--retries`: Versuche pro Datei (Anwendungsebene)
- `--low-level-retries`: TCP/HTTP-Level-Retries bei kurzem Netzwerkausfall

**Parallele Transfers: `--transfers N`**  
Präzise Kontrolle über gleichzeitige Verbindungen:
- Viele kleine Dateien: `--transfers 8`
- Wenige große Dateien (Stabilität): `--transfers 2`

**Bandbreitenlimit: `--bwlimit`**  
Verhindert Cluster-Netz-Sättigung wenn viele Pods gleichzeitig starten/syncen.

**Fortschritt im Log: `--stats Ns`**  
Gibt alle N Sekunden Transferrate, übertragene Bytes und verbleibende Dateien aus.
Bei Final-Sync via `kubectl exec` wird diese Ausgabe captured und geloggt.

**`rclone bisync` — Bidirektionale Synchronisation**  
Einzige Option, die S3-seitige Änderungen in den Container zieht. Verhindert
versehentliches Überschreiben durch externe Uploads.

**`--resilient`: Fortsetzung nach Teilfehlern**  
Markiert fehlgeschlagene Dateien als "pending" statt Sync abzubrechen. Nächster
Run versucht diese erneut.

**Symlinks: `--copy-links`**  
Folgt Symlinks explizit und lädt den Inhalt hoch. Nicht stillschweigend ignoriert.

**MinIO als expliziter Provider**  
`RCLONE_CONFIG_S3_PROVIDER=Minio` aktiviert MinIO-spezifische Optimierungen:
korrektes ETag-Handling bei Multi-Part-Uploads, keine AWS-only Features (accelerate
endpoint). Konfigurierbarer Provider in der Mampok-Config (`s3_provider`).

---

### rclone — Nachteile und Edge Cases

**bisync State-File — Korruption bei Pod-Kill**  
Bei gewaltsamen Pod-Abbruch (OOMKill, Force-Delete) während bisync kann der
State-File inkonsistent werden. Nächster Run mit `--workdir /tmp/bisync-state/`
(in `/tmp/`) erkennt das; da `/tmp/` bei Pod-Restart weg ist, startet jeder neue
Pod mit leerem State → `--force` nötig, aber sicher.

**bisync Konflikte — Datenverlust möglich**  
Wenn dieselbe Datei auf beiden Seiten gleichzeitig geändert wurde:
- Default: Fehler-Log, Datei wird nicht übertragen
- Konfigurierbar: `--conflict-resolve newer` (jüngere Datei gewinnt) — empfohlen

**bisync erster Run `--force` — kein echtes Merge-Risiko**  
`--force` ist technisch nötig (bisync verweigert Start ohne State-File). Kein
"Force-Merge": Der Sidecar startet nach dem Restore-Init-Container, d.h. lokal == S3.
Der Container hat noch keine eigenen Dateien geschrieben → `--force` erstellt nur
den initialen State-File.

**rclone Checksum-Fallback bei Multi-Part-Uploads**  
Bei `--checksum` fällt rclone bei Multi-Part-ETags auf `Size+ModTime` zurück —
korrekt. Nur `--checksum-only` (ohne `-only` ist sicher) kann Fehler produzieren.

**Kein eingebautes `--interval`-Flag**  
rclone hat keinen Daemon/Interval-Mode für bisync. Shell-While-Schleife ist der
Standard-Ansatz. `rclone rcd` (Remote-Control-Daemon) existiert, ist aber für
diesen Use Case überdimensioniert.

**Concurrent Pods auf demselben Bucket/Prefix**  
rclone bisync ist nicht concurrency-safe wenn mehrere Pods denselben S3-Prefix
synchronisieren (kein verteiltes Locking). In mampok_v2 kein Problem: 1 Deployment
= 1 Bucket. Bei Shared-Bucket-Architektur wäre bisync nicht einsetzbar.

**State-File nicht im synced Pfad**  
Der State-File (`--workdir /tmp/bisync-state/`) darf nicht innerhalb von `/sync/`
liegen, sonst werden `.lst`-Listing-Dateien nach S3 hochgeladen.

**Edge Case: Sehr viele kleine Dateien (> 100k)**  
Beim ersten `--force`-Run muss rclone alle Dateien auf beiden Seiten auflisten.
Bei > 100k Dateien kann das S3-Listing mehrere Minuten dauern. aws-cli hat
dasselbe Problem.

---

## s3fs / rclone mount — Theoretischer Vergleich

Betrifft Anwendungsfälle, in denen ein S3-Bucket transparent als Dateisystem
gemountet werden soll (z.B. sehr große Datensätze, die nicht vollständig
heruntergeladen werden können).

### Warum FUSE `privileged: true` braucht

FUSE-Mounts benötigen den Linux-Kernel-Aufruf `mount()`. Kubernetes sperrt das
standardmäßig:
- `securityContext.privileged: true` — maximale Rechte (nicht empfohlen)
- `capabilities.add: [SYS_ADMIN]` + `/dev/fuse` device — minimal weniger riskant,
  aber immer noch erhebliche Angriffsfläche

### Vergleich der Ansätze

| Ansatz | `privileged` | Transparentes FS | Große Datensätze | Latenz |
|---|---|---|---|---|
| s3fs (FUSE) | ✅ erforderlich | ✅ | ✅ lazy load | FUSE-Overhead |
| rclone mount (FUSE) | ✅ erforderlich | ✅ | ✅ VFS-Cache | besser als s3fs |
| rclone / aws-cli Sidecar | ✗ nicht nötig | ✗ (lokal) | ✗ vollst. Download | Sync-Intervall |

**Sidecar-Ansatz ersetzt FUSE** in den meisten SHMamplan-Anwendungsfällen:
- App schreibt in lokales Verzeichnis (kein Live-S3-Zugriff nötig)
- Datenmenge ist beim Start downloadbar
- Periodischer Sync-Delay akzeptabel

**Wann FUSE trotzdem nötig ist:**
- Datenmenge nicht vollständig downloadbar (Multi-TB Live-Datensätze)
- App benötigt POSIX-Semantik (`flock`, `rename()` über Prozessgrenzen)
- Live-Konsistenz zwischen S3 und Container erforderlich

**rclone mount vs. s3fs** (falls FUSE unumgänglich): rclone mount ist vorzuziehen —
besser gewartet, `--vfs-cache-mode full` für echtes lokales Caching, bessere
non-AWS-S3-Kompatibilität.

---

## Implementierungshinweise

### rclone Konfiguration in Pods

Alle Container verwenden `RCLONE_CONFIG_*` Env-Vars (zentralisiert via
`ManifestBuilder._build_rclone_env()`):

```
RCLONE_CONFIG_S3_TYPE=s3
RCLONE_CONFIG_S3_PROVIDER=Minio       # oder AWS für echtes AWS S3
RCLONE_CONFIG_S3_ENDPOINT=<endpoint>  # aus mampok config
RCLONE_CONFIG_S3_ACCESS_KEY_ID        # aus K8s Secret
RCLONE_CONFIG_S3_SECRET_ACCESS_KEY    # aus K8s Secret
```

### Sidecar-Command (rclone bisync)

```bash
# erster Run: State-File anlegen (--force nötig ohne State, --workdir außerhalb /sync/)
rclone bisync /sync/ S3:$s3bucket/container_data/ \
  --force --resilient --workdir /tmp/bisync-state/ \
  --transfers 4 --log-level ERROR

# Loop: delta-Sync
while true; do
  rclone bisync /sync/ S3:$s3bucket/container_data/ \
    --resilient --conflict-resolve newer --workdir /tmp/bisync-state/ \
    --transfers 4 --log-level ERROR
  sleep $MAMPOK_SYNC_INTERVAL
done
```

### Final-Sync vor Stop (via kubectl exec)

```bash
rclone copy /sync/ S3:$s3bucket/container_data/ \
  --transfers 4 --retries 3 --stats 10s --log-level INFO
```

`rclone copy` statt `bisync` beim Stop: sicherer, kein bidirektionales Überschreiben
im fragilen Zeitfenster. `--stats 10s` gibt Fortschritt aus, der via `kubectl exec`
output-capture und `logger.info()` sichtbar ist. Timeout (`container_data_sync_timeout`)
dient als reines Sicherheitsnetz und kann großzügig dimensioniert werden.
