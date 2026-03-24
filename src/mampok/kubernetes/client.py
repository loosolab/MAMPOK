"""Kubernetes client — Schicht 1: generischer K8s-Wrapper ohne Mampok-Logik."""

from __future__ import annotations

from typing import Any


class KubeClient:
    """Dünner Wrapper um den offiziellen kubernetes-Python-Client.

    Kennt keine Mampok-Logik und ist vollständig wiederverwendbar.
    Routet anhand des `kind`-Feldes im Manifest zur richtigen K8s-API-Gruppe.

    Args:
        namespace: Kubernetes-Namespace für alle Operationen.
        api_client: Optionaler vorkonfigurierter ApiClient. Wenn None, wird
            die Standard-Kube-Config geladen.
    """

    def __init__(self, namespace: str, api_client: Any | None = None) -> None:
        """Initialisiert KubeClient.

        Args:
            namespace: Kubernetes-Namespace für alle Operationen.
            api_client: Optionaler vorkonfigurierter ApiClient (kubernetes.client.ApiClient).
        """
        raise NotImplementedError

    def apply(self, manifest: dict) -> dict:
        """Wendet ein Kubernetes-Manifest an (create or update).

        Verhält sich wie `kubectl apply`: Existiert die Ressource, wird sie
        aktualisiert; existiert sie nicht, wird sie erstellt.

        Args:
            manifest: Vollständiges K8s-Manifest als dict (mit apiVersion, kind,
                metadata, spec).

        Returns:
            Das erstellte/aktualisierte Ressourcen-Objekt als dict.
        """
        raise NotImplementedError

    def apply_many(self, manifests: list[dict]) -> list[dict]:
        """Wendet mehrere Kubernetes-Manifeste an.

        Args:
            manifests: Liste von K8s-Manifesten. None-Einträge werden übersprungen.

        Returns:
            Liste der erstellten/aktualisierten Ressourcen-Objekte.
        """
        raise NotImplementedError

    def delete(self, kind: str, name: str) -> None:
        """Löscht eine Kubernetes-Ressource.

        Args:
            kind: Ressourcentyp (z.B. "Deployment", "Service", "Ingress", "Secret").
            name: Name der Ressource im konfigurierten Namespace.
        """
        raise NotImplementedError

    def exists(self, kind: str, name: str) -> bool:
        """Prüft ob eine Kubernetes-Ressource existiert.

        Args:
            kind: Ressourcentyp (z.B. "Deployment", "Service").
            name: Name der Ressource im konfigurierten Namespace.

        Returns:
            True wenn die Ressource existiert, sonst False.
        """
        raise NotImplementedError
