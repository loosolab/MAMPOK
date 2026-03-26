"""Mampok — zentraler Orchestrator für Kubernetes-Deployments."""

from __future__ import annotations

import logging
import secrets
import string
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

import bcrypt

from mampok.config.config import MampokConfig
from mampok.kubernetes.builder import ManifestBuilder
from mampok.kubernetes.config import DeploymentConfig
from mampok.kubernetes.manager import DeploymentManager
from mampok.mamplan.mamplan import Mamplan
from mampok.mamplan.mamplate import Mamplate
from mampok.s3.s3 import S3

logger = logging.getLogger(__name__)


class Mampok:
    """Zentraler Orchestrator — verbindet alle Mampok-Module.

    Wird von den Interfaces (CLI, API) instanziiert und delegiert Operationen
    an die zuständigen Module (DeploymentManager, S3, Mamplan, Mamplate).
    MampokConfig wird nicht gespeichert, sondern an Methoden übergeben.

    Args:
        mamplan: Geladene und validierte Mamplan-Instanz.
        mamplate: Passendes Mamplate für das Tool im Mamplan.
        kube: Konfigurierter DeploymentManager für den Ziel-Cluster.
        s3: Konfigurierter S3-Client für den Projekt-Bucket.
    """

    def __init__(
        self,
        mamplan: Mamplan,
        mamplate: Mamplate,
        kube: DeploymentManager,
        s3: S3,
        init_mamplates: list[Mamplate] | None = None,
    ) -> None:
        """Initialisiert Mampok.

        Args:
            mamplan: Geladene und validierte Mamplan-Instanz.
            mamplate: Passendes Mamplate für das Tool im Mamplan.
            kube: Konfigurierter DeploymentManager für den Ziel-Cluster.
            s3: Konfigurierter S3-Client für den Projekt-Bucket.
            init_mamplates: Optionale Liste von Mamplates für custom Init-Container.
        """
        self.mamplan = mamplan
        self.mamplate = mamplate
        self.kube = kube
        self.s3 = s3
        self.init_mamplates: list[Mamplate] = init_mamplates or []

    @property
    def is_expired(self) -> bool:
        """True wenn deployment.lifetime abgelaufen UND deployment.status=True.

        Returns:
            True wenn das Deployment aktiv und abgelaufen ist.
        """
        deployment = self.mamplan.data["deployment"]
        if not deployment["status"]:
            return False
        lifetime = datetime.fromisoformat(deployment["lifetime"])
        if lifetime.tzinfo is None:
            lifetime = lifetime.replace(tzinfo=timezone.utc)
        return lifetime < datetime.now(timezone.utc)

    def deploy(self, config: MampokConfig, timeout: int = 300, cleanup: bool = True) -> Iterator[dict]:
        """Deployt das Projekt auf Kubernetes.

        Ablauf:
        1. DeploymentConfig aus Mamplan + Mamplate + ClusterConfig ableiten
        2. S3-Bucket erstellen
        3. Dateien hochladen (nur wenn nicht bereits vorhanden mit gleicher Größe)
        4. Kubernetes-Ressourcen erstellen
        5. Warten bis alle Pods ready sind
        6. Mamplan aktualisieren (status=True, url)

        Bei Fehler während Schritt 4 oder 5 werden bereits erstellte K8s-Ressourcen
        automatisch bereinigt (sofern cleanup=True).

        Args:
            config: Konfiguration mit Cluster- und S3-Credentials.
            timeout: Maximale Wartezeit in Sekunden bis Pods ready sind.
            cleanup: Falls True, werden K8s-Ressourcen bei Fehler automatisch gelöscht.

        Yields:
            Fortschritts-Dicts für jeden Schritt des Deployments:
            - {"stage": "init", "status": "done", "project_id": str}
            - {"stage": "s3_bucket", "status": "created"|"exists"}
            - {"stage": "s3_upload", "status": "done", "file": str}
            - {"stage": "s3_upload", "status": "complete", "total_files": int}
            - {"stage": "k8s_apply", "status": "done", "resource": str}
            - {"stage": "k8s_ready", "status": "running", "ready_replicas": int}
            - {"stage": "k8s_cleanup", "status": "done", "project_id": str}  (nur bei Fehler+cleanup)
            - {"stage": "done", "selfservice": {"url": str, "project_id": str, "auth": bool}}
        """
        cfg = self._build_deployment_config(config)
        project_id = cfg.project_id
        logger.debug("deploy: project_id=%s, namespace=%s, image=%s, replicas=%s, auth=%s, url=%s",
                     cfg.project_id, cfg.namespace, cfg.image, cfg.replicas, cfg.auth, cfg.url)

        step: dict = {"stage": "init", "status": "done", "project_id": project_id}
        logger.debug("step: %s", step)
        yield step

        # S3 bucket
        bucket_existed = self.s3.bucket_exists()
        self.s3.create_bucket()
        step = {"stage": "s3_bucket", "status": "exists" if bucket_existed else "created"}
        logger.debug("step: %s", step)
        yield step

        # S3 upload per file
        files = self.mamplan.data["project"]["files"]
        for file_path in files:
            local = Path(file_path)
            key = local.name
            if not self.s3.compare_size(key, local):
                self.s3.upload(local, key)
            step = {"stage": "s3_upload", "status": "done", "file": key}
            logger.debug("step: %s", step)
            yield step
        step = {"stage": "s3_upload", "status": "complete", "total_files": len(files)}
        logger.debug("step: %s", step)
        yield step

        # K8s deploy
        s3_credentials = {
            "s3_endpoint": config.s3.endpoint,
            "s3_key": config.s3.access_key,
            "s3_secret": config.s3.secret_key,
            "s3_files": ",".join(Path(f).name for f in files),
        }
        logger.debug("s3_credentials: endpoint=%s, key=%s, secret=***, files=%s",
                     s3_credentials["s3_endpoint"], s3_credentials["s3_key"], s3_credentials["s3_files"])
        k8s_started = False
        try:
            for step in self.kube.deploy(cfg, s3_credentials):
                k8s_started = True
                logger.debug("step: %s", step)
                yield step

            # Readiness watch
            for step in self.kube.wait_for_ready(cfg, timeout=timeout):
                logger.debug("step: %s", step)
                yield step
        except Exception:
            if cleanup and k8s_started:
                logger.warning("deploy failed, cleaning up K8s resources: %s", cfg.project_id)
                self.kube.delete(cfg)
                step = {"stage": "k8s_cleanup", "status": "done", "project_id": cfg.project_id}
                logger.debug("step: %s", step)
                yield step
            raise

        # Update mamplan
        self.mamplan.edit(deployment__status=True, deployment__url=cfg.url)
        step = {"stage": "done", "selfservice": {"url": cfg.url, "project_id": project_id, "auth": cfg.auth}}
        logger.debug("step: %s", step)
        yield step

    def stop(self, config: MampokConfig) -> None:
        """Stoppt das Deployment — entfernt K8s-Ressourcen, S3-Bucket bleibt erhalten.

        Args:
            config: Konfiguration mit Cluster-Credentials.
        """
        cfg = self._build_deployment_config(config)
        logger.debug("stop: project_id=%s, namespace=%s", cfg.project_id, cfg.namespace)
        self.kube.delete(cfg)
        self.mamplan.edit(deployment__status=False)

    def check_status(self, config: MampokConfig) -> dict:
        """Vergleicht den lokalen Mamplan-Status mit dem K8s-Realzustand.

        Args:
            config: Konfiguration mit Cluster-Credentials.

        Returns:
            Dict mit project_id, expected_active, actually_deployed, healthy.
        """
        cfg = self._build_deployment_config(config)
        expected_active = self.mamplan.data["deployment"]["status"]
        actually_deployed = self.kube.deployment_exists(cfg)
        result = {
            "project_id": cfg.project_id,
            "expected_active": expected_active,
            "actually_deployed": actually_deployed,
            "healthy": expected_active == actually_deployed,
        }
        logger.debug("check_status: %s", result)
        return result

    def update_auth_secret(self, users: list[str], config: MampokConfig) -> None:
        """Generiert ein neues htpasswd-Secret und aktualisiert es auf dem Cluster.

        Erzeugt bcrypt-gehashte Passwörter für alle übergebenen User und
        ersetzt das bestehende K8s-Basic-Auth-Secret ohne Pod-Neustart.

        Args:
            users: Liste von Usernamen für die neue htpasswd-Datei.
                   Bei ["public"] wird nur ein öffentlicher Zugang erstellt.
            config: Konfiguration mit Cluster-Credentials.
        """
        lines = []
        for user in users:
            password = _generate_password()
            hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
            lines.append(f"{user}:{hashed}")
        htpasswd_content = "\n".join(lines) + "\n"

        cfg = self._build_deployment_config(config)
        builder = ManifestBuilder()
        manifest = builder.build_auth_secret(cfg, htpasswd_content)
        self.kube._kube.apply(manifest)

    def _build_deployment_config(self, config: MampokConfig) -> DeploymentConfig:
        """Leitet eine DeploymentConfig aus Mamplan, Mamplate und ClusterConfig ab.

        Args:
            config: MampokConfig mit Cluster- und S3-Daten.

        Returns:
            Vollständig befüllte DeploymentConfig.
        """
        cluster_name = self.mamplan.data["deployment"]["cluster"]
        cluster_cfg = config.get_cluster(cluster_name)
        auth_proxy = cluster_cfg.auth_proxy

        merged = self.mamplan.merge_container_config(self.mamplate, self.init_mamplates)
        main = merged["main"]

        # ports: Mamplate-Schema verwendet einzelnen int → zu Liste konvertieren
        raw_ports = main.get("ports")
        ports = [raw_ports] if isinstance(raw_ports, int) else (raw_ports or [])

        # resources
        resources = main.get("resources", {})
        limits = resources.get("limits", {})
        requests = resources.get("requests", {})

        # volume: {mountPath, name} → volume_mounts + volumes (emptyDir)
        volume = main.get("volume")
        if volume:
            volume_mounts = [{"name": volume["name"], "mountPath": volume["mountPath"]}]
            volumes = [{"name": volume["name"], "emptyDir": {}}]
        else:
            volume_mounts = []
            volumes = []

        # env: Mamplate-Format → K8s-natives Format
        project_id = self.mamplan.data["project"]["project_id"]
        tool = self.mamplan.data["project"]["tool"]
        project_secret_name = f"{project_id}-sc-{tool}"
        cluster_secret_name = config.s3.secretname
        env = _transform_env(main.get("env", []), project_secret_name, cluster_secret_name)

        raw_init_list = merged.get("init", [])
        init_containers = []
        for ic in raw_init_list:
            if "env" in ic:
                ic = {**ic, "env": _transform_env(ic["env"], project_secret_name, cluster_secret_name)}
            init_containers.append(ic)

        files = self.mamplan.data["project"].get("files", [])
        include_s3download = bool(files)

        return DeploymentConfig(
            project_id=project_id,
            tool=tool,
            image=main["image"],
            namespace=cluster_cfg.namespace,
            cpu=str(limits.get("cpu", "1")),
            memory=str(limits.get("memory", "2Gi")),
            request_cpu=str(requests["cpu"]) if "cpu" in requests else "",
            request_memory=str(requests["memory"]) if "memory" in requests else "",
            ports=ports,
            env=env,
            args=main.get("args", []),
            command=main.get("command", []),
            url=self.mamplan.data["deployment"]["url"],
            host=cluster_cfg.host,
            generate_url=self.mamplan.data["deployment"]["generate_url"],
            auth=self.mamplan.data["deployment"]["auth"],
            volume_mounts=volume_mounts,
            volumes=volumes,
            readiness_probe=main.get("readinessProbe"),
            ingress_annotations=cluster_cfg.annotations,
            ingress_class=cluster_cfg.ingress_class,
            tls_issuer=cluster_cfg.dnsissuer,
            tls_secret=cluster_cfg.dnssecret,
            s3_secret_name=config.s3.secretname,
            init_containers=init_containers,
            include_s3download=include_s3download,
            bucket=self.s3.bucket,
            auth_proxy_image=auth_proxy.auth_proxy_image if auth_proxy else "",
            proxy_port=auth_proxy.proxy_port if auth_proxy else 8080,
            auth_annotations=auth_proxy.auth_annotations if auth_proxy else {},
            image_pull_secrets=auth_proxy.image_pull_secrets if auth_proxy else [],
        )


def _transform_env(
    env_items: list, project_secret_name: str, cluster_secret_name: str
) -> list:
    """Transformiert Mamplate-env-Einträge in K8s-natives Format.

    secret_ref: 'project' → Projekt-Secret ({project_id}-sc-{tool}, von Mampok erstellt)
    secret_ref: 'cluster' → Cluster-Secret (config.s3.secretname, pre-existing in K8s)
    secret_ref: <anderer string> → Custom Secret-Name

    Args:
        env_items: Liste von Mamplate-env-Einträgen.
        project_secret_name: Name des Projekt-Secrets ({project_id}-sc-{tool}).
        cluster_secret_name: Name des Cluster-Secrets (config.s3.secretname).

    Returns:
        Liste von K8s-nativen env-Einträgen.
    """
    result = []
    for item in env_items:
        if "value" in item:
            # DirectEnvVar: {name, value} → bereits K8s-kompatibel
            result.append({"name": item["name"], "value": item["value"]})
        else:
            # SecretEnvVar: {key, name, secret_ref}
            secret_ref = item["secret_ref"]
            if secret_ref == "project":
                secret_name = project_secret_name
            elif secret_ref == "cluster":
                secret_name = cluster_secret_name
            else:
                secret_name = secret_ref
            result.append(
                {
                    "name": item["key"],
                    "valueFrom": {
                        "secretKeyRef": {"name": secret_name, "key": item["name"]}
                    },
                }
            )
    return result


def _generate_password(length: int = 16) -> str:
    """Generiert ein kryptographisch sicheres zufälliges Passwort.

    Args:
        length: Länge des Passworts.

    Returns:
        Zufälliger alphanumerischer String.
    """
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))
