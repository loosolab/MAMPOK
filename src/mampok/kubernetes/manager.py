"""DeploymentManager — Schicht 3: Orchestrierung von KubeClient und ManifestBuilder."""

from __future__ import annotations

from mampok.kubernetes.client import KubeClient
from mampok.kubernetes.config import DeploymentConfig


class DeploymentManager:
    """Verbindet KubeClient (Schicht 1) und ManifestBuilder (Schicht 2).

    Orchestriert Deploy/Delete-Zyklen für ein Mampok-Deployment.

    Args:
        kube: Konfigurierter KubeClient für den Ziel-Namespace.
    """

    def __init__(self, kube: KubeClient) -> None:
        """Initialisiert DeploymentManager.

        Args:
            kube: Konfigurierter KubeClient für den Ziel-Namespace.
        """
        raise NotImplementedError

    def deploy(self, cfg: DeploymentConfig) -> None:
        """Deployt alle Kubernetes-Ressourcen für eine DeploymentConfig.

        Erzeugt Manifeste via ManifestBuilder und wendet sie via KubeClient an.
        Reihenfolge: Secret → Deployment → Service → Ingress.

        Args:
            cfg: Deployment-Konfiguration.
        """
        raise NotImplementedError

    def delete(self, cfg: DeploymentConfig) -> None:
        """Löscht alle Kubernetes-Ressourcen eines Deployments.

        Löscht in Reihenfolge: Deployment → Service → Ingress → Secret(s).
        Existiert eine Ressource nicht, wird der Fehler ignoriert.

        Args:
            cfg: Deployment-Konfiguration.
        """
        raise NotImplementedError

    def redeploy(self, cfg: DeploymentConfig) -> None:
        """Löscht und deployt ein Deployment neu.

        Args:
            cfg: Deployment-Konfiguration.
        """
        raise NotImplementedError

    def rollout_status(self, cfg: DeploymentConfig) -> dict:
        """Gibt den aktuellen Rollout-Status des Deployments zurück.

        Args:
            cfg: Deployment-Konfiguration.

        Returns:
            Dict mit Status-Informationen (ready_replicas, available_replicas, etc.).
        """
        raise NotImplementedError

    def update_image(self, cfg: DeploymentConfig, image: str) -> None:
        """Aktualisiert das Container-Image eines laufenden Deployments.

        Patcht das Deployment — Kubernetes rollt neue Pods automatisch aus.

        Args:
            cfg: Deployment-Konfiguration (für Deployment-Name und Namespace).
            image: Neues Docker-Image URI.
        """
        raise NotImplementedError
