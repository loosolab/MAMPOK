"""DeploymentConfig — Schicht 2: typisierte Deployment-Konfiguration."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DeploymentConfig:
    """Beschreibt alle Parameter eines Mampok-Deployments.

    Dient als typisierte Zwischenschicht zwischen Mamplan (dict) und
    Kubernetes-Manifesten. Wird von ManifestBuilder konsumiert.

    Naming-Schema der K8s-Ressourcen:
        Deployment: {project_id}-dpl-{tool}
        Service:    {project_id}-svc-{tool}
        Ingress:    {project_id}-ing-{tool}
        Secret:     {project_id}-sc-{tool}
        Auth-Secret:{project_id}-sc-{tool}-auth
    """

    project_id: str
    """Eindeutige Projekt-ID (lowercase, keine Underscores)."""

    tool: str
    """Tool-Name (z.B. cellxgene, nginx)."""

    image: str
    """Docker-Image URI des Containers."""

    namespace: str
    """Kubernetes-Namespace."""

    replicas: int = 1
    """Anzahl der Pod-Replicas."""

    cpu: str = "1"
    """CPU-Limit (z.B. '1', '500m')."""

    memory: str = "2Gi"
    """Memory-Limit (z.B. '2Gi', '4Gi')."""

    ports: list[int] = field(default_factory=list)
    """Exposed Container-Ports."""

    env: list[dict] = field(default_factory=list)
    """Umgebungsvariablen: [{name, value}] oder [{key, name, secretname}]."""

    url: str = ""
    """Externe URL des Deployments (leer = kein Ingress)."""

    generate_url: bool = True
    """Ob Mampok die URL automatisch generiert."""

    auth: bool = False
    """Ob Basic-Auth aktiviert ist."""

    autoscaling: bool = False
    """Ob HorizontalPodAutoscaler erstellt werden soll."""

    labels: dict = field(default_factory=dict)
    """Zusätzliche K8s-Labels (werden zu Standard-Labels gemergt)."""

    volume_mounts: list[dict] = field(default_factory=list)
    """Volume-Mount-Definitionen."""

    ingress_annotations: dict = field(default_factory=dict)
    """Cluster-spezifische Ingress-Annotations."""

    ingress_class: str = ""
    """Kubernetes Ingress-Class-Name."""

    tls_issuer: str = ""
    """Cert-Issuer für TLS (dnsissuer)."""

    tls_secret: str = ""
    """DNS-Secret für ACME-Challenge (dnssecret)."""

    s3_secret_name: str = ""
    """Name des K8s-Secrets mit S3-Credentials."""

    init_container: dict | None = None
    """Init-Container-Konfiguration (None = kein Init-Container)."""
