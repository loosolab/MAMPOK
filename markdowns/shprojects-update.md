# Plan: Separate `projects` und `shprojects` MongoDB Collections

## Kontext / Motivation

Der Backend-Worker (`bcu-backend-worker`) wurde bereits aktualisiert (Commit `shprojects db`,
2026-04-16). Vorher wurden sowohl SDOA-Mamplans (`*-mamplan.json`) als auch SSS-Shmamplans
(`*-shmamplan.json`) in **einer einzigen** MongoDB-Collection `projects` gespeichert. Die Flask API
musste daher alle Projekte laden und per `filter_info_json()` mithilfe von Namenskonventionen
(Prüfung auf `-ss` im `project_id` oder Username im `project_id`) trennen.

Der Worker schreibt jetzt in zwei separate Collections:

-   `db["projects"]` → SDOA-Mamplans
-   `db["shprojects"]` → SSS-Shmamplans

**Ziel:** Die Flask API so anpassen, dass sie die richtigen Collections direkt abfragt und die
fragile, ID-basierte Runtime-Filterung entfällt.

---

## Architektur: Vorher vs. Nachher

### Vorher (aktueller Stand Flask API)

```
MongoDB (eine DB, eine Collection)
└── projects          ← SDOA-Mamplans + SSS-Shmamplans gemischt

Flask API
├── get_all_projects()              → db["projects"].find({})
├── filter_info_json(all, user, groups)
│   ├── Prüft: "-ss" in project_id  → SSS
│   ├── Prüft: username in project_id → SSS
│   └── Rest → SDOA (public/private/shared)
├── genSdoaInfoCached → ruft filter_info_json, gibt sdoa_data zurück
├── genSSSInfoCached  → ruft filter_info_json, gibt sss_data zurück
└── change_stream_handler_projects → emittiert sdoa_info_update + sss_info_update
```

### Nachher (Zielstand)

```
MongoDB (eine DB, zwei Collections)
├── projects          ← nur SDOA-Mamplans
└── shprojects        ← nur SSS-Shmamplans

Flask API
├── get_all_projects()    → db["projects"].find({})
├── get_all_shprojects()  → db["shprojects"].find({})  [NEU]
├── filter_info_json(sdoa_projects, user, groups)
│   └── nur noch public/private/shared – keine SSS-Logik mehr
├── filter_sss_projects(shprojects, username)   [NEU]
│   └── nur eigene Container zurückgeben
├── genSdoaInfoCached → get_all_projects() + filter_info_json()
├── genSSSInfoCached  → get_all_shprojects() + filter_sss_projects()  [GEÄNDERT]
├── change_stream_handler_projects  → nur sdoa_info_update  [VEREINFACHT]
└── change_stream_handler_shprojects → nur sss_info_update  [NEU]
```

---

## Betroffene Dateien

| Datei              | Art der Änderung                                                      |
| ------------------ | --------------------------------------------------------------------- |
| `mongo_service.py` | 3 neue Funktionen, 1 Funktion erweitert                               |
| `mampok_calls.py`  | 1 neue Funktion, `filter_info_json` vereinfacht                       |
| `gateway_api.py`   | 2 Endpoints angepasst, 1 Handler vereinfacht, 1 Handler + Watcher neu |

---

## Detaillierter Implementierungsplan

### Schritt 1 – `mongo_service.py`

**1a. `get_all_shprojects()` hinzufügen** (analog zu `get_all_projects()`, ab Zeile 36):

```python
def get_all_shprojects():
    res = list(db["shprojects"].find({}))
    for project in res:
        project["_id"] = str(project["_id"])
        for key, val in list(project.items()):
            if isinstance(val, datetime.datetime):
                project[key] = val.isoformat()
    return res
```

**1b. `get_single_project_data()` (Zeile 122) erweitern** – Fallback auf `shprojects`, damit die
Endpoints `/deployProject`, `/stopProject`, `/shareProject`, `/updateLifetime` weiterhin für SSS-
Container funktionieren (die rufen alle `get_single_project_data()` auf):

```python
def get_single_project_data(db_id):
    res = db["projects"].find_one(ObjectId(db_id))
    if res is None:
        res = db["shprojects"].find_one(ObjectId(db_id))
    if res:
        res["_id"] = str(res["_id"])
    return res
```

**1c. `watch_shproject_changes()` hinzufügen** (nach `watch_project_changes`, ab Zeile 89):

```python
def watch_shproject_changes(handle_change_stream):
    try:
        with db["shprojects"].watch(full_document="updateLookup") as stream:
            for change in stream:
                handle_change_stream(change)
    except PyMongoError as e:
        print(f"Error watching MongoDB shprojects changes: {e}")
```

---

### Schritt 2 – `mampok_calls.py`

**2a. `filter_sss_projects()` hinzufügen** (nach `filter_info_json`, ~ab Zeile 110):

```python
def filter_sss_projects(shprojects, username):
    """Return only SSS containers owned by the requesting user."""
    return [p for p in shprojects if p.get("owner") == username]
```

**2b. `filter_info_json()` vereinfachen** (Zeile 78–109):

Die SSS-Erkennung über `project_id`-Muster entfernen. Die Funktion gibt jetzt nur noch ein Dict
zurück (kein Tuple mehr):

```python
def filter_info_json(info_json, username, groups):
    info_json_usercontext = {"public": [], "private": [], "shared": []}
    for project in info_json:
        if "public" in project["organization"]:
            info_json_usercontext["public"].append(project)
        if username == project["owner"]:
            info_json_usercontext["private"].append(project)
        elif (project["user"] and username in project["user"]) or set(groups).intersection(
            set(project["organization"])
        ):
            info_json_usercontext["shared"].append(project)
    return {
        "public": info_json_usercontext["public"],
        "private": info_json_usercontext["private"],
        "shared": info_json_usercontext["shared"],
    }
```

> **Wichtig:** `filter_info_json` gibt jetzt einen **dict** statt einem **tuple** zurück.
> Es gibt genau **3 Call-Sites** in `gateway_api.py`, die alle angepasst werden müssen:
>
> | Call-Site                        | Zeile     | Maßnahme                                                                                       |
> | -------------------------------- | --------- | ---------------------------------------------------------------------------------------------- |
> | `genSSSInfoCached`               | 653–655   | Gesamte Funktion wird umgeschrieben (Schritt 3a) – `filter_info_json`-Aufruf entfällt komplett |
> | `genSdoaInfoCached`              | 1640–1642 | Tuple-Zuweisung `sdoa_data, sss_data = ...` → `sdoa_data = ...` (Schritt 3b)                   |
> | `change_stream_handler_projects` | 1782–1784 | Tuple-Zuweisung `sdoa_data, sss_data = ...` → `sdoa_data = ...` (Schritt 3c)                   |

---

### Schritt 3 – `gateway_api.py`

**3a. `genSSSInfoCached` (Zeile 619–672) umschreiben:**

Vorher: `get_all_projects()` + `filter_info_json()` → `sss_data`  
Nachher: `get_all_shprojects()` + `filter_sss_projects()` → `sss_data`

```python
@app.route("/genSSSInfoCached", methods=["GET"])
@requires_auth
def genSSSInfoCached():
    unfiltered_shprojects = mongo_service.get_all_shprojects()
    userdata = requires_userdata()
    username = userdata["username"]

    open_jobs = mongo_service.get_open_jobs()
    all_shprojects_inc_jobs, deploy_logs = mampok_calls.integrate_projects_jobs(
        open_jobs, unfiltered_shprojects
    )
    sss_data = mampok_calls.filter_sss_projects(all_shprojects_inc_jobs, username)
    sss_configs = mampok_calls.load_sss_container_config()

    return {
        "sss_containers": sss_data,
        "sss_configs": sss_configs,
        "deploy_logs": deploy_logs,
    }
```

**3b. `genSdoaInfoCached` (Zeile 1597–1651) anpassen:**

`filter_info_json` gibt jetzt nur noch ein dict zurück (kein Tuple):

```python
# Vorher:
sdoa_data, sss_data = mampok_calls.filter_info_json(all_projects_inc_jobs, username, groups)

# Nachher:
sdoa_data = mampok_calls.filter_info_json(all_projects_inc_jobs, username, groups)
```

Return-Statement bleibt gleich: `return {"sdoa_data": sdoa_data, "deploy_logs": deploy_logs}`

**3c. `change_stream_handler_projects` (Zeile 1741–1794) vereinfachen:**

`sss_info_update` Emission entfernen, `filter_info_json` Tuple-Aufruf anpassen:

```python
def change_stream_handler_projects(change):
    active_connections = rDB.get("active_connections")
    if (
        change["ns"]["db"] == app.config["MONGODB_DB_NAME"]
        and change["ns"]["coll"] == "projects"
    ):
        unfiltered_info_json = mongo_service.get_all_projects()
        open_jobs = mongo_service.get_open_jobs()
        all_projects_inc_jobs, deploy_logs = mampok_calls.integrate_projects_jobs(
            open_jobs, unfiltered_info_json
        )
        active_connections = decode_redis_dict(active_connections) if active_connections else {}
        for connection_id, userdata in active_connections.items():
            try:
                username = userdata["username"]
                groups = userdata["groups"]
                sdoa_data = mampok_calls.filter_info_json(
                    all_projects_inc_jobs, username, groups
                )
                sdoa_data_clean = json.loads(json.dumps(sdoa_data, default=str))
                socketio.emit("sdoa_info_update", sdoa_data_clean, to=connection_id)
                # sss_info_update wird jetzt von change_stream_handler_shprojects übernommen
            except KeyError:
                continue
```

**3d. `change_stream_handler_shprojects` neu hinzufügen** (nach `change_stream_handler_projects`):

```python
def change_stream_handler_shprojects(change):
    active_connections = rDB.get("active_connections")
    if (
        change["ns"]["db"] == app.config["MONGODB_DB_NAME"]
        and change["ns"]["coll"] == "shprojects"
    ):
        all_shprojects = mongo_service.get_all_shprojects()
        open_jobs = mongo_service.get_open_jobs()
        all_shprojects_inc_jobs, deploy_logs = mampok_calls.integrate_projects_jobs(
            open_jobs, all_shprojects
        )
        active_connections = decode_redis_dict(active_connections) if active_connections else {}
        for connection_id, userdata in active_connections.items():
            try:
                username = userdata["username"]
                sss_data = mampok_calls.filter_sss_projects(all_shprojects_inc_jobs, username)
                sss_data_clean = json.loads(json.dumps(sss_data, default=str))
                socketio.emit("sss_info_update", sss_data_clean, to=connection_id)
            except KeyError:
                continue
```

**3e. `watch_shprojects_now()` hinzufügen** (nach `watch_projects_now`, Zeile 1931):

```python
def watch_shprojects_now():
    gevent.sleep(10)
    while True:
        try:
            mongo_service.watch_shproject_changes(change_stream_handler_shprojects)
            logger.warning("shprojects changestream ended unexpectedly, restarting...")
        except Exception as e:
            logger.error("shprojects changestream error, restarting in 5s: %s", e)
        gevent.sleep(5)
```

**3f. Background-Task registrieren** (Zeile 2019, im `if hostname.split("-")[-1] == "0"` Block):

```python
gevent.spawn(watch_shprojects_now)
```

---

## Frontend (Folgeschritt – separater Agent)

Das Angular-Frontend unter `C:\Users\nknoppi\Documents\angular_frontend\src` muss **nicht**
grundlegend umgebaut werden. Die WebSocket-Events und API-Endpoints bleiben gleich benannt.

**Aber:** Die Response-Shape von `/genSdoaInfoCached` ändert sich geringfügig:

### Response-Änderung `/genSdoaInfoCached`

**Vorher:**

```json
{
  "sdoa_data": { "public": [...], "private": [...], "shared": [...] },
  "deploy_logs": { ... }
}
```

**Nachher:** Identisch – keine Änderung für das Frontend.

### Response-Änderung `sdoa_info_update` (WebSocket)

**Vorher:** Payload war `{ "public": [...], "shared": [...], "private": [...] }`  
**Nachher:** Identisch – keine Änderung für das Frontend.

### Response-Änderung `sss_info_update` (WebSocket)

**Vorher:** Payload war eine flache Liste aller SSS-Projekte des Users.  
**Nachher:** Weiterhin eine flache Liste – aber nun direkt aus `shprojects` Collection gefiltert
statt als Nebenprodukt von `filter_info_json`.  
**Frontend-Impact: keine Änderung nötig**, solange die Dokumente in `shprojects` die gleichen
Felder enthalten wie die alten SSS-Dokumente in `projects`.

### Relevante Frontend-Dateien (für den nächsten Agent)

| Datei                                       | Zeilen  | Zweck                                        |
| ------------------------------------------- | ------- | -------------------------------------------- |
| `src/app/services/api.service.ts`           | 221–232 | `genSdoaProjectInfo()` – REST-Aufruf         |
| `src/app/services/api.service.ts`           | 577–590 | `genandGetToolContainerList()` – REST-Aufruf |
| `src/app/services/websocket-api.service.ts` | 228–235 | `getRepoChanges()` – `sdoa_info_update`      |
| `src/app/services/websocket-api.service.ts` | 237–244 | `getSSSRepoChanges()` – `sss_info_update`    |
| `src/app/sdoa/sdoa.component.ts`            | 131–157 | SDOA-Komponente, verarbeitet Updates         |
| `src/app/sss/sss.component.ts`              | 76–107  | SSS-Komponente, verarbeitet Updates          |

### WebSocket-Watcher im Frontend – Status

Beide WebSocket-Events existieren auf dem Frontend bereits und müssen **nicht neu hinzugefügt**
werden:

| Event              | Frontend-Listener     | Datei / Zeile                  | Verarbeitung                                                   |
| ------------------ | --------------------- | ------------------------------ | -------------------------------------------------------------- |
| `sdoa_info_update` | `getRepoChanges()`    | `websocket-api.service.ts:228` | `sdoa.component.ts:131` → `apiService.sdoa_projects.next(...)` |
| `sss_info_update`  | `getSSSRepoChanges()` | `websocket-api.service.ts:237` | `sss.component.ts:76` → `apiService.sss_containers.next(...)`  |

Die Events heißen nach der Umstellung unverändert gleich. Der einzige Unterschied: `sss_info_update`
wird jetzt vom neuen `change_stream_handler_shprojects` (statt als Nebenprodukt von
`change_stream_handler_projects`) ausgelöst. Das Frontend merkt davon nichts.

**Möglicher Frontend-Bedarf** (wenn Felder fehlen oder sich umbenennen):

-   `sss.component.ts` nutzt `formatToolContainerList()` – prüfen ob alle erwarteten Felder
    (`_id`, `project_id`, `tool`, `lifetime`, `status`, `preset`, `job_status`) in den
    `shprojects`-Dokumenten vorhanden sind.
-   `sdoa.component.ts` nutzt `formatSdoaProjectList()` – prüfen ob alle erwarteten Felder
    weiterhin in `projects`-Dokumenten vorhanden sind.

---

## Verifikation

1. Flask API starten, `/genSdoaInfoCached` aufrufen → Response enthält nur SDOA-Mamplans (keine
   shmamplans)
2. `/genSSSInfoCached` aufrufen → Response enthält nur SSS-Container des anfragenden Users
3. SSS-Container deployen/stoppen via `/deployProject` / `/stopProject` → funktioniert weiterhin
   (durch den Fallback in `get_single_project_data`)
4. Neues Mamplan-Dokument in `db["projects"]` einfügen → WebSocket-Event `sdoa_info_update`
   wird an alle verbundenen Clients gesendet
5. Neues Shmamplan-Dokument in `db["shprojects"]` einfügen → WebSocket-Event `sss_info_update`
   wird an alle verbundenen Clients gesendet
6. Prüfen dass `sdoa_info_update` **kein** SSS-Projekt mehr enthält
