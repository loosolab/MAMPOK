# Plan: `direct_s3_access` → `full_bucket_overwrite` — Vollständige Implementierung

## Context

`direct_s3_access: true` in Mamplaten hatte zwei historische Rollen:
1. **S3-FUSE-Mount**: Injizierte `AWS_*`-Credentials → **obsolet seit rclone-Sidecar**
2. **Capability-Marker**: Signalisiert SHMamplan-Workflow

**Neues Design:** `full_bucket_overwrite: "<container-pfad>"` — Wert = Mount-Pfad.
Wirkt auf **beide** Deployment-Typen (Mamplan + SHMamplan).
Schließt sich mit `container_data` gegenseitig aus (Schema-Constraint).

```json
// ALT:
"direct_s3_access": true

// NEU:
"full_bucket_overwrite": "/home/appuser/"
```

**Was `full_bucket_overwrite` bewirkt:**
- **Restore** (Init-Container): `rclone copy S3:bucket/ <mountpath>/` — ganzer Bucket → Container
- **Sidecar-Sync**: `rclone bisync /sync/{sub}/ S3:$s3bucket/` — bidirektional, kein `container_data/`-Präfix
- **`include_s3download = False`**: Kein separater `analysis_data/`-Download (Bucket-Sync deckt alles ab)
- **`container_data_restore = True`**: Wird automatisch gesetzt

---

## Entscheidender Unterschied: Sync-Pfade

| | Normaler Mamplan | `full_bucket_overwrite` gesetzt |
|---|---|---|
| Eingangsdaten | `S3:bucket/analysis_data/` → `/analysis_data/` | entfällt |
| Restore | `S3:bucket/container_data/{sub}/` → Container | `S3:bucket/` → `<mountpath>/` |
| Sidecar | `rclone bisync /sync/ S3:$s3bucket/container_data/` | `rclone bisync /sync/{sub}/ S3:$s3bucket/` |

**Mounting-Beispiel** (`full_bucket_overwrite: "/home/appuser/"`):
```
emptyDir "mampok-sync-home-appuser":
  main-container: /home/appuser      ← Jupyter arbeitet hier
  sidecar:        /sync/home-appuser ← rclone sieht denselben Inhalt

rclone bisync /sync/home-appuser/ S3:$s3bucket/
# → /home/appuser/file.txt ↔ S3:bucket/file.txt  ✓ (Bucket-Root)
```

---

## Betroffene Dateien

| Datei | Änderungstyp |
|---|---|
| `mamplan/schemas/mamplate_schema.json` | `direct_s3_access` → `full_bucket_overwrite` (string) + Schema-Constraint |
| `kubernetes/config.py` | `direct_s3_access` → `container_data_s3_root: bool` |
| `kubernetes/builder.py` | AWS_*-Block löschen; Sidecar + Restore parametrisieren |
| `mampok/mampok.py` | `full_bucket_overwrite` lesen; `container_data_s3_root` setzen |
| `new_mampok_dummy_repo/mamplates/jpt-ss-mamplate.json` | Key + Wert anpassen |

`mamplan_schema.json`: **keine eigene Änderung** (erbt `MamplateProperties` via `$ref`).

---

## Schritt-für-Schritt-Implementierung

### Schritt 1 — `mamplate_schema.json`: Key umbenennen + Typ ändern + Constraint

**Datei:** `mampok_v2/src/mampok/mamplan/schemas/mamplate_schema.json`

#### 1a — Key ersetzen (im `properties`-Block):

```json
// ENTFERNEN:
"direct_s3_access": {
  "type": "boolean",
  "description": "If true, injects AWS_ACCESS_KEY_ID, ...",
  "default": false
},

// HINZUFÜGEN:
"full_bucket_overwrite": {
  "type": "string",
  "pattern": "^/",
  "description": "If set, the entire S3 bucket root is synced bidirectionally into this container path (no 'container_data/' prefix). Value is the absolute container path (e.g. '/home/appuser/'). On pod start, the whole bucket is downloaded to this path (overwrite/restore). During runtime, rclone bisync keeps the path and S3 bucket in sync bidirectionally. Mutually exclusive with 'container_data'."
},
```

#### 1b — Mutual-Exclusivity-Constraint (in `allOf` des Schemas):

```json
// Im top-level allOf von mamplate_schema.json hinzufügen:
{
  "if": {
    "required": ["full_bucket_overwrite"]
  },
  "then": {
    "not": {
      "required": ["container_data"]
    }
  }
}
```

### Schritt 2 — `jpt-ss-mamplate.json`: Key + Wert aktualisieren

**Datei:** `new_mampok_dummy_repo/mamplates/jpt-ss-mamplate.json`

```json
// VORHER (Zeile 11):
  "direct_s3_access": true,

// NACHHER (Pfad aus dem Jupyter-Command: --notebook-dir=/home/appuser/):
  "full_bucket_overwrite": "/home/appuser/",
```

### Schritt 3 — `config.py`: `direct_s3_access` → `container_data_s3_root`

**Datei:** `mampok_v2/src/mampok/kubernetes/config.py`

```python
# ENTFERNEN (Zeilen 137–139):
    direct_s3_access: bool = False
    """If True, inject AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY and AWS_ENDPOINT_URL
    from the project secret into the main container."""

# endpoint-Docstring bereinigen (Zeile 129–130):
# VORHER:
    """S3 endpoint URL — as literal value in the s3download init container and
    injected into the main container when direct_s3_access is True."""
# NACHHER:
    """S3 endpoint URL — used in rclone RCLONE_CONFIG_S3_ENDPOINT for all S3 containers."""

# HINZUFÜGEN (nach container_data_restore, ca. Zeile 145):
    container_data_s3_root: bool = False
    """If True, sync container_data_paths[0] directly to/from the bucket root (no
    'container_data/' prefix). Set by the builder when the mamplate defines
    'full_bucket_overwrite'. Requires exactly one entry in container_data_paths."""
```

### Schritt 4 — `mampok.py`: `full_bucket_overwrite` verarbeiten

**Datei:** `mampok_v2/src/mampok/mampok/mampok.py`

```python
# VORHER (Zeilen 367–386):
        files = self.mamplan.data["project"].get("files", [])
        include_s3download = bool(files)
        ...
        container_data = main.get("container_data", {})
        container_data_paths = container_data.get("paths", [])
        container_data_restore = bool(container_data.get("restore_on_deploy", False))
        container_data_sync_interval = int(container_data.get("sync_interval_seconds", 300))
        container_data_sync_timeout = int(container_data.get("sync_timeout_seconds", 300))

# NACHHER:
        files = self.mamplan.data["project"].get("files", [])
        include_s3download = bool(files)
        ...
        container_data = main.get("container_data", {})
        container_data_paths = container_data.get("paths", [])
        container_data_restore = bool(container_data.get("restore_on_deploy", False))
        container_data_sync_interval = int(container_data.get("sync_interval_seconds", 300))
        container_data_sync_timeout = int(container_data.get("sync_timeout_seconds", 300))
        container_data_s3_root = False                          # NEU

        full_bucket_overwrite = main.get("full_bucket_overwrite")  # NEU
        if full_bucket_overwrite:
            container_data_paths = [full_bucket_overwrite]
            container_data_restore = True
            container_data_s3_root = True
            include_s3download = False  # Bucket-Sync deckt alle Daten ab
```

```python
# In DeploymentConfig(...) (Zeile ~416):
# ENTFERNEN:
            direct_s3_access=bool(main.get("direct_s3_access", False)),
# HINZUFÜGEN:
            container_data_s3_root=container_data_s3_root,
```

### Schritt 5 — `builder.py`: AWS_*-Block entfernen + rclone-Befehle parametrisieren

**Datei:** `mampok_v2/src/mampok/kubernetes/builder.py`

#### 5a — AWS_*-Injektionsblock löschen (Zeilen 144–159)

```python
# VORHER:
        env = [{"name": "MAMPOK_BASE_PATH", "value": urlparse(cfg.url).path}] + list(cfg.env)
        if cfg.direct_s3_access:
            env = [
                {"name": "AWS_ACCESS_KEY_ID", "valueFrom": ...},
                {"name": "AWS_SECRET_ACCESS_KEY", "valueFrom": ...},
                {"name": "AWS_ENDPOINT_URL", "value": cfg.endpoint},
            ] + env

# NACHHER:
        env = [{"name": "MAMPOK_BASE_PATH", "value": urlparse(cfg.url).path}] + list(cfg.env)
```

#### 5b — Restore-Init-Container (Zeilen ~205–209)

```python
# VORHER:
                restore_cmd_parts = " && ".join(
                    f"rclone copy S3:$(s3bucket)/container_data/{_sync_sidecar_subpath(p)}/ "
                    f"{p.rstrip('/')}/ --ignore-errors --retries 3 --log-level ERROR"
                    for p in cfg.container_data_paths
                )

# NACHHER:
                if cfg.container_data_s3_root:
                    # full_bucket_overwrite: ganzer Bucket → einziger Container-Pfad
                    target = cfg.container_data_paths[0].rstrip("/")
                    restore_cmd_parts = (
                        f"rclone copy S3:$(s3bucket)/ {target}/ "
                        "--ignore-errors --retries 3 --log-level ERROR"
                    )
                else:
                    restore_cmd_parts = " && ".join(
                        f"rclone copy S3:$(s3bucket)/container_data/{_sync_sidecar_subpath(p)}/ "
                        f"{p.rstrip('/')}/ --ignore-errors --retries 3 --log-level ERROR"
                        for p in cfg.container_data_paths
                    )
```

#### 5c — Sidecar-Command parametrisieren (Zeilen ~331–345)

```python
# VORHER:
            sync_cmd = (
                "mkdir -p /tmp/bisync-state && "
                "rclone bisync /sync/ S3:$s3bucket/container_data/ "
                ...
            )

# NACHHER:
            if cfg.container_data_s3_root:
                # full_bucket_overwrite: Bucket-Root ↔ spezifischer Sidecar-Subpfad
                subpath = _sync_sidecar_subpath(cfg.container_data_paths[0])
                local_path = f"/sync/{subpath}/"
                s3_path = "S3:$s3bucket/"
            else:
                # Normaler Mamplan: alle Pfade unter container_data/
                local_path = "/sync/"
                s3_path = "S3:$s3bucket/container_data/"

            sync_cmd = (
                "mkdir -p /tmp/bisync-state && "
                f"rclone bisync {local_path} {s3_path}"
                "--resync --workdir /tmp/bisync-state/ "
                "--transfers 4 --log-level ERROR && "
                "while true; do "
                f"rclone bisync {local_path} {s3_path}"
                "--conflict-resolve newer --workdir /tmp/bisync-state/ "
                "--transfers 4 --log-level ERROR "
                f"|| rclone bisync {local_path} {s3_path}"
                "--resync --workdir /tmp/bisync-state/ "
                "--transfers 4 --log-level ERROR; "
                "sleep $MAMPOK_SYNC_INTERVAL; "
                "done"
            )
```

---

## Pod-Struktur im Vergleich

### Normaler Mamplan (unverändert)
```
├── init-container        rclone copy S3:bucket/analysis_data/ /analysis_data/
├── init-container-restore  rclone copy S3:bucket/container_data/{sub}/ /app/results/
├── main-container        /analysis_data/ (ro) + /app/results/ (rw)
└── mampok-s3-sync        rclone bisync /sync/ S3:$s3bucket/container_data/
```

### `full_bucket_overwrite: "/home/appuser/"` (Mamplan oder SHMamplan)
```
├── init-container-restore  rclone copy S3:$(s3bucket)/ /home/appuser/   ← ganzer Bucket
├── main-container (Jupyter)  /home/appuser/ (emptyDir)
└── mampok-s3-sync            rclone bisync /sync/home-appuser/ S3:$s3bucket/  ← Bucket-Root
```
*(kein `init-container` für `analysis_data/` — `include_s3download=False`)*

---

## Edge Cases: Gültige und ungültige Mamplate-Kombinationen

| Mamplate-Konfiguration | Mamplan | SHMamplan |
|---|---|---|
| kein `full_bucket_overwrite`, kein `container_data` | ✓ kein Sync | ✓ kein Sync (z.B. IGV) |
| `full_bucket_overwrite` gesetzt | ✓ Bucket-Root Sync | ✓ Bucket-Root Sync |
| `container_data` gesetzt | ✓ `container_data/` Sync | ✗ **ungültig** |
| `full_bucket_overwrite` + `container_data` | ✗ Schema-Fehler | ✗ Schema-Fehler |

**Schema-Constraint** (`mamplate_schema.json`): `full_bucket_overwrite` + `container_data`
zusammen → Schema-Fehler (gilt für beide Deployment-Typen).

**SHMamplan-Builder-Validierung**: `container_data` ohne `full_bucket_overwrite` →
Laufzeitfehler im SHMamplan-Builder (das JSON-Schema allein kann Deployment-Typ-spezifische
Regeln nicht durchsetzen):

```python
# Pseudocode SHMamplan-Builder:
if mamplate.get("container_data") and not mamplate.get("full_bucket_overwrite"):
    raise MamplateIncompatibleError(
        f"Mamplate '{mamplate['tool']}' verwendet 'container_data' — "
        "nicht erlaubt in SHMamplan-Deployments. "
        "Verwende 'full_bucket_overwrite' für Bucket-Sync oder entferne 'container_data'."
    )
```

**Fehlen von `full_bucket_overwrite` ist valide**: Tools wie IGV ohne Daten-Workflow
können in SHMamplans eingesetzt werden — sie haben dann einfach keinen Sidecar/Sync.

---

## Verifikation

### Unit-Tests (`tests/test_kubernetes/test_builder.py`)

Aktuell keine Tests für `direct_s3_access` vorhanden — neue Tests:

```python
def test_no_aws_env_in_main_container(minimal_cfg):
    """Main-Container darf keine AWS_*-Credentials mehr enthalten."""
    deployment = ManifestBuilder().build_deployment(minimal_cfg)
    env_names = [e["name"] for e in
                 deployment["spec"]["template"]["spec"]["containers"][0].get("env", [])]
    assert not any(n.startswith("AWS_") for n in env_names)

def test_normal_sidecar_uses_container_data_prefix(cfg_with_container_data):
    """Normaler Mamplan: Sidecar synct nach container_data/."""
    deployment = ManifestBuilder().build_deployment(cfg_with_container_data)
    sidecar_args = _get_sidecar_args(deployment)
    assert "S3:$s3bucket/container_data/" in sidecar_args
    assert sidecar_args.startswith("...") or "/sync/ " in sidecar_args

def test_full_bucket_overwrite_sidecar_uses_bucket_root():
    """full_bucket_overwrite: Sidecar synct zum Bucket-Root, kein container_data/."""
    cfg = DeploymentConfig(
        ...,
        container_data_paths=["/home/appuser/"],
        container_data_restore=True,
        container_data_s3_root=True,
    )
    deployment = ManifestBuilder().build_deployment(cfg)
    sidecar_args = _get_sidecar_args(deployment)
    assert "S3:$s3bucket/ " in sidecar_args
    assert "/sync/home-appuser/" in sidecar_args
    assert "container_data" not in sidecar_args

def test_full_bucket_overwrite_restore_uses_bucket_root():
    """full_bucket_overwrite: Restore kopiert ganzen Bucket, kein container_data/."""
    deployment = ManifestBuilder().build_deployment(cfg_shmamplan)
    restore_args = _get_restore_args(deployment)
    assert "S3:$(s3bucket)/ " in restore_args
    assert "container_data" not in restore_args
```

### Schema-Validierung

```
"full_bucket_overwrite": "/home/appuser/"               → valide ✓
"full_bucket_overwrite": "no-leading-slash"             → Schema-Fehler (pattern: ^/) ✗
"full_bucket_overwrite" + "container_data" gemeinsam    → Schema-Fehler (Constraint) ✗
"direct_s3_access": true                                → Schema-Fehler (additionalProperties) ✗
```

### Manuell (End-to-End)

```bash
# Kein AWS_* im Main-Container
kubectl exec <pod> -c main-container -- env | grep AWS      # → leer ✓

# Sidecar hat rclone-Config
kubectl exec <pod> -c mampok-s3-sync -- env | grep RCLONE  # → konfiguriert ✓

# Bidirektionaler Sync (S3 → Container)
aws s3 cp local.txt s3://bucket/remote.txt
# → nach MAMPOK_SYNC_INTERVAL: /home/appuser/remote.txt im Container ✓

# Bidirektionaler Sync (Container → S3)
kubectl exec <pod> -c main-container -- touch /home/appuser/new.txt
# → nach Sync-Intervall: S3:bucket/new.txt erscheint ✓
```
