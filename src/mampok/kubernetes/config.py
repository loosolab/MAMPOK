"""DeploymentConfig — Schicht 2: typisierte Deployment-Konfiguration."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DeploymentConfig:
    """Describes all parameters of a Mampok deployment.

    Serves as a typed intermediate layer between Mamplan (dict) and
    Kubernetes manifests. Consumed by ManifestBuilder.

    Resource naming scheme:
        Deployment: {project_id}-dpl-{tool}
        Service:    {project_id}-svc-{tool}
        Ingress:    {project_id}-ing-{tool}
        Secret:     {project_id}-sc-{tool}
        Auth-Secret:{project_id}-sc-{tool}-auth
    """

    project_id: str
    """Unique project ID (lowercase, no underscores)."""

    tool: str
    """Tool name (e.g. cellxgene, nginx)."""

    image: str
    """Docker image URI."""

    namespace: str
    """Kubernetes namespace."""

    replicas: int = 1
    """Number of pod replicas."""

    cpu: str = "1"
    """CPU limit (e.g. '1', '500m')."""

    memory: str = "2Gi"
    """Memory limit (e.g. '2Gi', '4Gi')."""

    request_cpu: str = ""
    """CPU request (empty = same as limit)."""

    request_memory: str = ""
    """Memory request (empty = same as limit)."""

    ports: list[int] = field(default_factory=list)
    """Exposed container ports."""

    env: list[dict] = field(default_factory=list)
    """Environment variables: [{name, value}] or [{name, valueFrom: {secretKeyRef: ...}}]."""

    args: list[str] = field(default_factory=list)
    """Container arguments."""

    command: list[str] = field(default_factory=list)
    """Container command (entrypoint override)."""

    url: str = ""
    """External URL of the deployment (empty = no Ingress)."""

    host: str = ""
    """Ingress host (from ClusterConfig)."""

    generate_url: bool = True
    """Whether Mampok auto-generates the URL."""

    auth: bool = False
    """Whether basic auth is enabled."""

    auth_proxy_image: str = ""
    """Docker-Image des Gatekeeper-Sidecar-Containers."""

    proxy_port: int = 8080
    """Port, auf dem der Gatekeeper lauscht."""

    proxy_cpu: str = "100m"
    """CPU-Limit für den Gatekeeper-Sidecar."""

    proxy_memory: str = "128Mi"
    """Memory-Limit für den Gatekeeper-Sidecar."""

    auth_annotations: dict = field(default_factory=dict)
    """Extra Ingress-Annotations, nur bei auth=True hinzugefügt."""

    image_pull_secrets: list[str] = field(default_factory=list)
    """Pull-Secret-Namen — als imagePullSecrets auf Pod-Ebene gesetzt."""

    auth_config_mount_path: str = "/etc/config"
    """Mount-Pfad des Auth-Secret-Volumes im Gatekeeper-Container."""

    labels: dict = field(default_factory=dict)
    """Additional K8s labels (merged with standard labels)."""

    volume_mounts: list[dict] = field(default_factory=list)
    """Container-level volume mount definitions."""

    volumes: list[dict] = field(default_factory=list)
    """Pod-level volume definitions."""

    readiness_probe: dict | None = None
    """Readiness probe configuration (K8s-native format)."""

    ingress_annotations: dict = field(default_factory=dict)
    """Cluster-specific Ingress annotations."""

    ingress_class: str = ""
    """Kubernetes Ingress class name."""

    tls_issuer: str = ""
    """Cert issuer for TLS (dnsissuer)."""

    tls_secret: str = ""
    """DNS secret for ACME challenge (dnssecret)."""

    s3_secret_name: str = ""
    """Name of the K8s secret containing S3 credentials."""

    init_container: dict | None = None
    """Init container configuration (None = no init container)."""

    def __post_init__(self) -> None:
        if self.auth and self.proxy_port in self.ports:
            raise ValueError(
                f"proxy_port {self.proxy_port} conflicts with app ports {self.ports}. "
                "Set a different proxy_port in the cluster auth_proxy config."
            )

    @property
    def deployment_name(self) -> str:
        """K8s Deployment resource name."""
        return f"{self.project_id}-dpl-{self.tool}"

    @property
    def service_name(self) -> str:
        """K8s Service resource name."""
        return f"{self.project_id}-svc-{self.tool}"

    @property
    def ingress_name(self) -> str:
        """K8s Ingress resource name."""
        return f"{self.project_id}-ing-{self.tool}"

    @property
    def secret_name(self) -> str:
        """K8s Secret resource name (S3 credentials)."""
        return f"{self.project_id}-sc-{self.tool}"

    @property
    def auth_secret_name(self) -> str:
        """K8s Secret resource name (basic auth)."""
        return f"{self.project_id}-sc-{self.tool}-auth"

    @property
    def app_label(self) -> str:
        """Standard app label value."""
        return f"{self.project_id}-mampok-{self.tool}"

    @property
    def effective_request_cpu(self) -> str:
        """CPU request, falling back to CPU limit if empty."""
        return self.request_cpu or self.cpu

    @property
    def effective_request_memory(self) -> str:
        """Memory request, falling back to memory limit if empty."""
        return self.request_memory or self.memory
