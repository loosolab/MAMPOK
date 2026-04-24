"""DeploymentConfig — layer 2: typed deployment configuration."""

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

    auth: bool = False
    """Whether basic auth is enabled."""

    auth_proxy_image: str = ""
    """Docker image of the Gatekeeper sidecar container."""

    proxy_port: int = 8080
    """Port on which the Gatekeeper listens."""

    proxy_cpu: str = "100m"
    """CPU limit for the Gatekeeper sidecar."""

    proxy_memory: str = "128Mi"
    """Memory limit for the Gatekeeper sidecar."""

    auth_annotations: dict = field(default_factory=dict)
    """Extra Ingress annotations, added only when auth=True."""

    image_pull_secrets: list[str] = field(default_factory=list)
    """Pull secret names — set as imagePullSecrets at pod level."""

    auth_config_mount_path: str = "/etc/config"
    """Mount path of the auth secret volume in the Gatekeeper container."""

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

    init_containers: list[dict] = field(default_factory=list)
    """Custom init container configurations (Mamplate-format, transformed by builder)."""

    include_s3download: bool = False
    """Whether to prepend the hardcoded s3download init container."""

    bucket: str = ""
    """S3 bucket name — injected as env var into the s3download init container."""

    endpoint: str = ""
    """S3 endpoint URL — used in rclone RCLONE_CONFIG_S3_ENDPOINT for all S3 containers."""

    s3_provider: str = "Minio"
    """rclone S3 provider (RCLONE_CONFIG_S3_PROVIDER). Use 'Minio' for MinIO/Ceph
    compatible stores, 'AWS' for native AWS S3. Controls ETag behavior and
    provider-specific optimisations."""

    is_bucket_overwrite: bool = False
    """True when the mamplate uses 'bucket_overwrite'. Syncs container_data_paths[0]
    directly to/from the bucket (or bucket subpath). Requires exactly one entry in
    container_data_paths."""

    container_data_s3_subpath: str = ""
    """S3 subpath when is_bucket_overwrite=True.
    Empty = sync from bucket root. Set (e.g. 'user_data') = sync from S3:$bucket/{subpath}/."""

    container_data_paths: list[str] = field(default_factory=list)
    """Container paths to sync to s3://bucket/container_data/ (e.g. '/app/.cellxgene/annotations/')."""

    container_data_restore: bool = False
    """If True, download container_data/ from S3 back into the container on deploy (round-trip)."""

    container_data_sync_interval: int = 60
    """Sidecar sync interval in seconds."""

    container_data_sync_timeout: int = 3600
    """Timeout in seconds Mampok waits for the pre-delete S3 sync (exec into sidecar).
    Mampok proceeds with deletion after this timeout even if sync is incomplete."""

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
