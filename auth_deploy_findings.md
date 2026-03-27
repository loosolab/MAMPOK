# Auth-Deploy Findings — Planungsgrundlage

> Analyse: Deploy mit `auth: true` schlägt fehl, während `auth: false` funktioniert.
> Basis: Code-Review + `~/new_mampok_dummy_repo/config.json`

---

## 1. Hauptursache: Auth-Secret wird beim Deploy nicht erstellt (KRITISCH)

**Das ist der Bug, der das Deployment zum Scheitern bringt.**

### Was passiert

Die Deployment-Manifest-Generierung in [builder.py:322-348](src/mampok/kubernetes/builder.py#L322) enthält einen expliziten Kommentar:

> `"Note: build_auth_secret is NOT called here (managed separately)."`

Das bedeutet: `build_all()` erstellt das K8s-Secret `{project_id}-sc-{tool}-auth` **nicht**.

### Warum das ein Problem ist

Das Deployment-Manifest referenziert das Auth-Secret als Volume-Mount ([builder.py:195-197](src/mampok/kubernetes/builder.py#L195)):

```yaml
volumes:
  - name: {project_id}-sc-{tool}-auth-volume
    secret:
      secretName: {project_id}-sc-{tool}-auth   # ← dieses Secret existiert nicht!
```

Kubernetes versucht beim Pod-Start das Secret zu mounten → Secret nicht vorhanden → **Pod startet nicht** → `wait_for_ready()` läuft in den Timeout.

### Wo das Secret eigentlich erstellt wird

`update_auth_secret()` in [mampok.py:211-232](src/mampok/mampok/mampok.py#L211) erstellt das Secret — aber diese Methode wird im `deploy()`-Flow ([mampok.py:71-169](src/mampok/mampok/mampok.py#L71)) **nirgends aufgerufen**.

`update_auth_secret()` ist nur erreichbar über:
- CLI: `mampok update-auth` — manuell, nach dem Deploy
- API: `edit_sharing()` — nur wenn `auth=True AND status=True` (also ebenfalls post-deploy)

### Fix-Ansatz

In `deploy()` ([mampok.py:71](src/mampok/mampok/mampok.py#L71)) muss `update_auth_secret()` **vor** `kube.deploy()` bzw. unmittelbar danach aufgerufen werden, damit das Secret beim Pod-Start schon existiert.

Benutzer ableiten analog zu `_derive_users()` in [cli.py:429](src/mampok/interfaces/cli.py#L429) (aus `tags.organization` + `tags.user` im Mamplan).

---

## 2. Auth-Annotation-Duplizierung in der Config

**config.json** (`~/new_mampok_dummy_repo/config.json:15-17`):

```json
"auth_annotations": {
  "kubernetes.io/ingress.class": "nginx"
}
```

Das ist eine **Legacy-Annotation** (deprecated seit K8s 1.18). Gleichzeitig setzt der Code aus `ingress_class: "nginx"` in der Cluster-Config das moderne `ingressClassName`-Feld im Ingress-Spec ([builder.py:312-313](src/mampok/kubernetes/builder.py#L312)).

**Resultat im Ingress-Manifest:**
```yaml
metadata:
  annotations:
    kubernetes.io/ingress.class: nginx   # ← aus auth_annotations
spec:
  ingressClassName: nginx                 # ← aus ingress_class
```

Beides gleichzeitig gesetzt — in älteren nginx-Ingress-Versionen kann das zu unerwartetem Verhalten führen (doppelte Verarbeitung oder Ignorieren einer der beiden Angaben). Aktuell nicht der unmittelbare Blocker, aber aufräumen.

---

## 3. proxy_port: 8080 — Kollisionsrisiko

Die Config setzt `proxy_port: 8080`. Der Gatekeeper-Sidecar läuft auf diesem Port.

Viele Tools (z.B. Jupyter, diverse Webapps) nutzen ebenfalls **Port 8080** als App-Port. Wenn das der Fall ist, greift die Validierung in [config.py:131-136](src/mampok/kubernetes/config.py#L131):

```python
if self.auth and self.proxy_port in self.ports:
    raise ValueError("proxy_port conflicts with app ports")
```

Das Deployment schlägt dann mit einem `ValueError` während `_build_deployment_config()` fehl — bevor überhaupt etwas auf K8s angewendet wird. Fehlermeldung ist klar, aber der User muss dann `proxy_port` in der config.json anpassen (z.B. auf `9090`).

**Empfehlung:** Standard-Port auf etwas Ungewöhnlicheres setzen (z.B. `9090`) oder zumindest in der Doku darauf hinweisen.

---

## 4. REDIRECT_HOST hardcoded auf `https://`

Der Gatekeeper-Sidecar erhält `REDIRECT_HOST = https://{cfg.host}` ([builder.py:183](src/mampok/kubernetes/builder.py#L183)).

Das Dummy-Config enthält **kein TLS-Setup** (`dnsissuer`/`dnssecret` fehlen). Falls der Cluster kein HTTPS hat, stimmt der Redirect-Host nicht und der Gatekeeper kann nach erfolgreicher Auth nicht korrekt weiterleiten. Für Produktion kein Problem (BN-Cluster hat TLS), aber relevant für lokale Tests/Dev-Setups.

---

## 5. REDIRECT_URL — Abhängigkeit von auth_annotations

Die Redirect-URL des Gatekeepers wird in [builder.py:167-171](src/mampok/kubernetes/builder.py#L167) so bestimmt:

```python
redirect_url = (
    "/"
    if "nginx.ingress.kubernetes.io/proxy-redirect-to" in cfg.auth_annotations
    else f"/{cfg.project_id}/{cfg.tool}/"
)
```

Die aktuelle `config.json` enthält **nicht** `nginx.ingress.kubernetes.io/proxy-redirect-to` in `auth_annotations`, also wird `/{project_id}/{tool}/` verwendet. Das ist für die URL-Generierung korrekt, aber es fehlt ein Rewrite in den `auth_annotations`. Bei nginx-Ingress mit Sub-Path-Routing könnte nach dem Login eine falsche Weiterleitungs-URL entstehen. Zu testen.

---

## 6. build_all() — Reihenfolge und fehlende Auth-Secret-Integration

Die aktuelle Deploy-Reihenfolge in [manager.py:49-58](src/mampok/kubernetes/manager.py#L49):

```
Secret → Deployment → Service → Ingress
```

Das Auth-Secret fehlt komplett in dieser Sequenz. Die Delete-Reihenfolge in [manager.py:75-81](src/mampok/kubernetes/manager.py#L75) kennt das Auth-Secret bereits:

```
Deployment → Service → Ingress → Secret → Auth-Secret
```

→ Delete ist korrekt, Deploy ist unvollständig.

---

## Zusammenfassung: Was muss gefixt werden

| # | Problem | Schwere | Fix-Aufwand |
|---|---------|---------|-------------|
| 1 | Auth-Secret wird beim Deploy nicht erstellt | **KRITISCH** (Blocker) | `update_auth_secret()` in `deploy()` integrieren |
| 2 | Legacy-Annotation + `ingressClassName` gleichzeitig | Mittel | `auth_annotations` in config.json bereinigen |
| 3 | `proxy_port: 8080` kollidiert mit vielen App-Ports | Mittel | Port ändern oder besser dokumentieren |
| 4 | `REDIRECT_HOST: https://` ohne TLS-Config | Niedrig (nur Dev) | Für Tests irrelevant, für Prod OK |
| 5 | Fehlendes Rewrite nach Auth-Redirect | Niedrig | In auth_annotations prüfen |

---

## Relevante Dateien

- [src/mampok/mampok/mampok.py](src/mampok/mampok/mampok.py) — `deploy()`, `update_auth_secret()`, `_build_deployment_config()`
- [src/mampok/kubernetes/builder.py](src/mampok/kubernetes/builder.py) — `build_all()`, `build_auth_secret()`, `build_deployment()`
- [src/mampok/kubernetes/manager.py](src/mampok/kubernetes/manager.py) — `deploy()`, `delete()`
- [src/mampok/kubernetes/config.py](src/mampok/kubernetes/config.py) — `DeploymentConfig`, `__post_init__`
- [src/mampok/interfaces/cli.py](src/mampok/interfaces/cli.py) — `_derive_users()`, `update_auth()`
- `~/new_mampok_dummy_repo/config.json` — Cluster-Config mit `auth_proxy`
