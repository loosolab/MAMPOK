"""MampokConfig — typisierte Konfiguration für Mampok v2."""

from __future__ import annotations

import importlib.resources
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

import jsonschema

if TYPE_CHECKING:
    from mampok.kubernetes.manager import DeploymentManager
    from mampok.s3.s3 import S3

logger = logging.getLogger(__name__)


@dataclass
class AuthProxyConfig:
    """Auth-Proxy-Konfiguration für den Gatekeeper-Sidecar.

    Args:
        auth_proxy_image: Docker-Image des Gatekeeper-Containers.
        proxy_port: Port, auf dem der Gatekeeper lauscht.
        auth_annotations: Extra Ingress-Annotations bei auth=True.
        image_pull_secrets: Pull-Secrets für das Proxy-Image.
    """

    auth_proxy_image: str
    proxy_port: int = 8080
    auth_annotations: dict = field(default_factory=dict)
    image_pull_secrets: list[str] = field(default_factory=list)


@dataclass
class ClusterConfig:
    """Configuration for a single Kubernetes cluster profile.

    Args:
        host: Ingress host for this cluster.
        namespace: Kubernetes namespace for deployments.
        kubeconfig_path: Path to the kubeconfig file for this cluster.
        annotations: Kubernetes Ingress annotations.
        ingress_class: Ingress class name.
        dnsissuer: Cert-manager issuer name for TLS.
        dnssecret: DNS secret name for ACME challenge.
    """

    host: str
    namespace: str
    kubeconfig_path: str
    annotations: dict = field(default_factory=dict)
    ingress_class: str = ""
    dnsissuer: str = ""
    dnssecret: str = ""
    auth_proxy: AuthProxyConfig | None = None
    """Gatekeeper-Proxy-Konfiguration. Erforderlich wenn Deployments auth=True nutzen."""


@dataclass
class S3Config:
    """S3-compatible storage credentials.

    Args:
        endpoint: S3 endpoint URL.
        access_key: S3 access key ID.
        secret_key: S3 secret access key.
        secretname: Name of the pre-existing K8s Secret holding S3 credentials.
        prefix: Optional prefix for S3 bucket names.
    """

    endpoint: str
    access_key: str
    secret_key: str
    secretname: str
    prefix: str = ""


@dataclass
class MampokConfig:
    """Typed configuration for Mampok v2.

    Loaded from a JSON file and validated against the config schema.
    Provides factory methods to create Kubernetes and S3 clients.

    Args:
        clusters: Named cluster profiles (e.g. {'BN': ClusterConfig(...)}).
        s3: S3 storage credentials.
        mamplan_repo: Path to the Mamplan repository directory.
        mamplates_path: Path to the Mamplates directory.
        lifetime_days: Default deployment lifetime in days.
    """

    clusters: dict[str, ClusterConfig]
    s3: S3Config
    mamplan_repo: Path
    mamplates_path: Path
    lifetime_days: int

    _schema_cache: ClassVar[dict | None] = None

    def get_cluster(self, name: str) -> ClusterConfig:
        """Return the named cluster profile.

        Args:
            name: Cluster name as used in the config and Mamplan.

        Returns:
            The ClusterConfig for the given name.

        Raises:
            KeyError: If the cluster name is not found in the config.
        """
        if name not in self.clusters:
            raise KeyError(
                f"Unknown cluster: {name!r}. Available: {list(self.clusters)}"
            )
        return self.clusters[name]

    def build_deployment_manager(self, cluster_name: str) -> "DeploymentManager":
        """Create a DeploymentManager for the named cluster profile.

        Loads the kubeconfig, creates a Kubernetes ApiClient, wraps it in a
        KubeClient, and returns a DeploymentManager. Used by interface layers.

        Args:
            cluster_name: Name of the cluster profile to connect to.

        Returns:
            Configured DeploymentManager for the cluster.
        """
        import kubernetes
        from mampok.kubernetes.client import KubeClient
        from mampok.kubernetes.manager import DeploymentManager

        cluster = self.get_cluster(cluster_name)
        kubernetes.config.load_kube_config(config_file=cluster.kubeconfig_path)
        api_client = kubernetes.client.ApiClient()
        kube_client = KubeClient(namespace=cluster.namespace, api_client=api_client)
        return DeploymentManager(kube_client)

    def build_s3_client(self, bucket: str) -> "S3":
        """Create an S3 client with the configured credentials.

        Used by interface layers to create the S3 dependency for Mampok.

        Args:
            bucket: S3 bucket name for this deployment.

        Returns:
            Configured S3 client.
        """
        from mampok.s3.s3 import S3

        return S3(
            bucket=bucket,
            endpoint_url=self.s3.endpoint,
            access_key=self.s3.access_key,
            secret_key=self.s3.secret_key,
        )

    @classmethod
    def from_dict(cls, data: dict) -> "MampokConfig":
        """Create a MampokConfig from a dict, validated against the JSON schema.

        Args:
            data: Configuration dict (as loaded from JSON).

        Returns:
            Validated MampokConfig instance.

        Raises:
            jsonschema.ValidationError: If the data violates the schema.
        """
        if cls._schema_cache is None:
            schema_ref = (
                importlib.resources.files("mampok.config")
                .joinpath("schemas")
                .joinpath("config_schema.json")
            )
            with schema_ref.open("r", encoding="utf-8") as f:
                cls._schema_cache = json.load(f)

        jsonschema.validate(data, cls._schema_cache)

        clusters = {
            name: ClusterConfig(
                host=cluster_data["host"],
                namespace=cluster_data["namespace"],
                kubeconfig_path=cluster_data["kubeconfig_path"],
                annotations=cluster_data.get("annotations", {}),
                ingress_class=cluster_data.get("ingress_class", ""),
                dnsissuer=cluster_data.get("dnsissuer", ""),
                dnssecret=cluster_data.get("dnssecret", ""),
                auth_proxy=(
                    AuthProxyConfig(
                        auth_proxy_image=_ap["auth_proxy_image"],
                        proxy_port=_ap.get("proxy_port", 8080),
                        auth_annotations=_ap.get("auth_annotations", {}),
                        image_pull_secrets=_ap.get("image_pull_secrets", []),
                    )
                    if (_ap := cluster_data.get("auth_proxy")) is not None
                    else None
                ),
            )
            for name, cluster_data in data["cluster"].items()
        }

        s3_data = data["s3"]
        s3 = S3Config(
            endpoint=s3_data["endpoint"],
            access_key=s3_data["access_key"],
            secret_key=s3_data["secret_key"],
            secretname=s3_data["secretname"],
            prefix=s3_data.get("prefix", ""),
        )

        return cls(
            clusters=clusters,
            s3=s3,
            mamplan_repo=Path(data["mamplan_repo"]),
            mamplates_path=Path(data["mamplates_path"]),
            lifetime_days=data["lifetime_days"],
        )

    @classmethod
    def from_file(cls, path: Path) -> "MampokConfig":
        """Load a MampokConfig from a JSON file.

        Args:
            path: Path to the JSON config file.

        Returns:
            Validated MampokConfig instance.

        Raises:
            FileNotFoundError: If the file does not exist.
            json.JSONDecodeError: If the file is not valid JSON.
            jsonschema.ValidationError: If the content violates the schema.
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")
        logger.info("loading config: %s", path)
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data)
