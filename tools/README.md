# migrate_mamplans.py

Migriert alte YAML-Mamplans (`*_MaMPlan.yaml/yml`) in das neue mampok v2 JSON-Format.

## Voraussetzungen

```bash
pip install pyyaml jsonschema referencing
```

## Grundprinzip

**Default = Dry-Run.** Ohne `--migrate` werden keine Dateien geschrieben — das Skript analysiert nur und zeigt einen Report.

## Verwendung

### 1. Report anzeigen (Dry-Run)

```bash
python tools/migrate_mamplans.py /pfad/zu/mamplans/
```

Durchsucht das Verzeichnis rekursiv, zeigt eine Tabelle mit Status, Fehlern und Hinweisen. Nichts wird geschrieben.

### 2. Report in Datei speichern

```bash
python tools/migrate_mamplans.py /pfad/zu/mamplans/ -o report.txt
```

### 3. Migration in ein Zielverzeichnis

```bash
python tools/migrate_mamplans.py --migrate /pfad/zu/mamplans/ /pfad/zum/output/
```

Zeigt zuerst den Report, fragt dann `Jetzt migrieren? [y/N]` bevor Dateien geschrieben werden. Dateien mit `ERROR` werden übersprungen.

### 4. Migration neben den Quelldateien (`--keep-path`)

```bash
python tools/migrate_mamplans.py --migrate --keep-path /pfad/zu/mamplans/
```

Schreibt die neuen JSON-Dateien in dasselbe Verzeichnis wie die jeweilige YAML-Quelldatei.

### 5. Alte YAML-Dateien nach Migration löschen

```bash
python tools/migrate_mamplans.py --migrate --keep-path --cleanup /pfad/zu/mamplans/
```

Löscht die YAML-Quelldateien nach erfolgreicher Migration (nur Dateien ohne ERROR). Fragt vorher nochmal nach.

### 6. Jede Datei mit WARNING/ERROR einzeln bestätigen

```bash
python tools/migrate_mamplans.py --migrate --keep-path --interactive /pfad/zu/mamplans/
```

Bei jeder Datei mit `WARNING` oder `ERROR` wird `Migrieren? [y/N]` gefragt. Default ist `N` (sicherer).

### 7. Report auf bestimmte Status-Level filtern

```bash
# Nur Warnings und Errors anzeigen
python tools/migrate_mamplans.py /pfad/zu/mamplans/ --show warning error

# Nur Errors
python tools/migrate_mamplans.py /pfad/zu/mamplans/ --show error

# Nur erfolgreich konvertierbare (OK)
python tools/migrate_mamplans.py /pfad/zu/mamplans/ --show ok
```

Die Gesamtzahl aller Dateien bleibt immer in der Zusammenfassung sichtbar.

## Report-Spalten

| Spalte | Bedeutung |
|---|---|
| Datei | Name der YAML-Quelldatei |
| Status | `OK`, `WARNING` oder `ERROR` |
| Fehler/Warnung | Validierungsfehler oder automatisch angewandte Fallbacks |
| Hinweise | Informationen für manuellen Review (`auth: false`, `keine Metadaten`) |

## Status-Bedeutung

| Status | Bedeutung |
|---|---|
| `OK` | Vollständig konvertierbar, besteht Schema-Validierung |
| `WARNING` | Konvertierbar, aber mit Fallback (z.B. fehlendes `creation_date` → Datei-mtime) |
| `ERROR` | Schema-Validierung schlägt fehl (z.B. Unterstriche in URL/Bucket) — wird beim Migrieren übersprungen |

## Automatische Transformationen

| Alt (YAML) | Neu (JSON) | Hinweis |
|---|---|---|
| `project.id` | `project.project_id` | |
| `project.init_container: s3download` | *(weggelassen)* | `s3download` ist v2-Default |
| `deployment.active` | `deployment.status` | |
| `deployment.mampok_url` | `deployment.generate_url` | |
| `deployment.random` | `deployment.random_url_suffix` | |
| `deployment.lifetime: DD/MM/YYYY` | ISO 8601 datetime | |
| `tags.creationdate: DD/MM/YY` | `project.creation_date` ISO 8601 | fehlt → mtime als Fallback |
| `tags.total_project_size` | `project.project_size` | Bytes → Kilobytes |
| `tags.analyst/owner/user/...` | `service.*` | eigene Section |
| `container.main.extra_args` | *(weggelassen)* | kein v2-Pendant |

## Ausgabe-Dateinamen

```
{project_id}-mamplan.json
```

Beispiel: `test-cellx-2_MaMPlan.yaml` → `test-cellx-2-mamplan.json`

## Alle Flags im Überblick

```
positional arguments:
  input_dir             Verzeichnis mit alten YAML-Mamplans (rekursiv)
  output_dir            Zielverzeichnis für neue JSON-Dateien (nicht nötig mit --keep-path)

options:
  --migrate             Schreibmodus aktivieren (nach Bestätigung)
  --keep-path           JSON neben der Quelldatei ablegen statt in OUTPUT_DIR
  --interactive         Bei WARNING/ERROR jede Datei einzeln bestätigen
  --cleanup             Alte YAML-Dateien nach Migration löschen (erfordert --migrate)
  --show LEVEL [...]    Angezeigte Status-Level: ok warning error (Standard: alle)
  -o REPORT_FILE        Report zusätzlich als Textdatei speichern
```
