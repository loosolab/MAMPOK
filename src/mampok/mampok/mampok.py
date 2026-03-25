"""Mampok — zentraler Orchestrator für Kubernetes-Deployments."""

from __future__ import annotations

import logging
import secrets
import string
from datetime import datetime, timezone
from pathlib import Path

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
    ) -> None:
        """Initialisiert Mampok.

        Args:
            mamplan: Geladene und validierte Mamplan-Instanz.
            mamplate: Passendes Mamplate für das Tool im Mamplan.
            kube: Konfigurierter DeploymentManager für den Ziel-Cluster.
            s3: Konfigurierter S3-Client für den Projekt-Bucket.
        """
        self.mamplan = mamplan
        self.mamplate = mamplate
        self.kube = kube
        self.s3 = s3

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

    def deploy(self, config: MampokConfig, timeout: int = 300) -> None:
        """Deployt das Projekt auf Kubernetes.

        Ablauf:
        1. DeploymentConfig aus Mamplan + Mamplate + ClusterConfig ableiten
        2. S3-Bucket erstellen
        3. Dateien hochladen (nur wenn nicht bereits vorhanden mit gleicher Größe)
        4. Kubernetes-Ressourcen erstellen
        5. Warten bis alle Pods ready sind
        6. Mamplan aktualisieren (status=True, url)

        Args:
            config: Konfiguration mit Cluster- und S3-Credentials.
            timeout: Maximale Wartezeit in Sekunden bis Pods ready sind.
        """
        cfg = self._build_deployment_config(config)

        self.s3.create_bucket()
        for file_path in self.mamplan.data["project"]["files"]:
            local = Path(file_path)
            key = local.name
            if not self.s3.compare_size(key, local):
                self.s3.upload(local, key)

        s3_credentials = {
            "s3_endpoint": config.s3.endpoint,
            "s3_key": config.s3.access_key,
            "s3_secret": config.s3.secret_key,
            "s3_files": ",".join(
                Path(f).name for f in self.mamplan.data["project"]["files"]
            ),
        }

        self.kube.deploy(cfg, s3_credentials)
        self.kube.wait_for_ready(cfg, timeout=timeout)

        self.mamplan.edit(deployment__status=True, deployment__url=cfg.url)

    def stop(self, config: MampokConfig) -> None:
        """Stoppt das Deployment — entfernt K8s-Ressourcen, S3-Bucket bleibt erhalten.

        Args:
            config: Konfiguration mit Cluster-Credentials.
        """
        cfg = self._build_deployment_config(config)
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
        return {
            "project_id": cfg.project_id,
            "expected_active": expected_active,
            "actually_deployed": actually_deployed,
            "healthy": expected_active == actually_deployed,
        }

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

        merged = self.mamplan.merge_container_config(self.mamplate)
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

        init_container = merged.get("init")

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
            init_container=init_container,
            auth_proxy_image=auth_proxy.auth_proxy_image if auth_proxy else "",
            proxy_port=auth_proxy.proxy_port if auth_proxy else 8080,
            auth_annotations=auth_proxy.auth_annotations if auth_proxy else {},
            image_pull_secrets=auth_proxy.image_pull_secrets if auth_proxy else [],
        )


def _transform_env(
    env_items: list, project_secret_name: str, cluster_secret_name: str
) -> list:
    """Transformiert Mamplate-env-Einträge in K8s-natives Format.

    secretname: 0 → Projekt-Secret ({project_id}-sc-{tool}, von Mampok erstellt)
    secretname: 1 → Cluster-Secret (config.s3.secretname, pre-existing in K8s)
    secretname: str → Custom Secret-Name

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
            # SecretEnvVar: {key, name, secretname}
            secretname = item["secretname"]
            if secretname == 0:
                secret_name = project_secret_name
            elif secretname == 1:
                secret_name = cluster_secret_name
            else:
                secret_name = str(secretname)
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
