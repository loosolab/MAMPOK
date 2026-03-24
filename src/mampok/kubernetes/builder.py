"""ManifestBuilder — Schicht 2: reine Datentransformation Config → K8s-Manifest."""

from __future__ import annotations

from mampok.kubernetes.config import DeploymentConfig


class ManifestBuilder:
    """Erzeugt Kubernetes-Manifeste aus einer DeploymentConfig.

    Kein State, keine API-Calls — rein funktional und vollständig unit-testbar.
    Gibt None zurück wenn eine Ressource für diese Config nicht benötigt wird
    (z.B. kein Ingress wenn keine URL gesetzt).
    """

    def build_secret(self, cfg: DeploymentConfig) -> dict:
        """Erzeugt das S3-Credentials-Secret-Manifest.

        Name: {project_id}-sc-{tool}

        Args:
            cfg: Deployment-Konfiguration.

        Returns:
            Vollständiges K8s-Secret-Manifest (type: Opaque).
        """
        raise NotImplementedError

    def build_auth_secret(self, cfg: DeploymentConfig, htpasswd_content: str) -> dict:
        """Erzeugt das Basic-Auth-Secret-Manifest.

        Name: {project_id}-sc-{tool}-auth. Wird nur erstellt wenn cfg.auth=True.

        Args:
            cfg: Deployment-Konfiguration.
            htpasswd_content: Inhalt der htpasswd-Datei (bcrypt-gehashte Passwörter).

        Returns:
            Vollständiges K8s-Secret-Manifest (type: kubernetes.io/basic-auth).
        """
        raise NotImplementedError

    def build_deployment(self, cfg: DeploymentConfig) -> dict:
        """Erzeugt das Deployment-Manifest.

        Name: {project_id}-dpl-{tool}
        Labels: app={project_id}-mampok-{tool}

        Args:
            cfg: Deployment-Konfiguration.

        Returns:
            Vollständiges K8s-Deployment-Manifest (apps/v1).
        """
        raise NotImplementedError

    def build_service(self, cfg: DeploymentConfig) -> dict | None:
        """Erzeugt das Service-Manifest.

        Name: {project_id}-svc-{tool}

        Args:
            cfg: Deployment-Konfiguration.

        Returns:
            Vollständiges K8s-Service-Manifest oder None wenn cfg.ports leer.
        """
        raise NotImplementedError

    def build_ingress(self, cfg: DeploymentConfig) -> dict | None:
        """Erzeugt das Ingress-Manifest.

        Name: {project_id}-ing-{tool}
        Wird nur erstellt wenn URL gesetzt und Cluster-TLS-Config vorhanden.

        Args:
            cfg: Deployment-Konfiguration.

        Returns:
            Vollständiges K8s-Ingress-Manifest oder None wenn keine URL/TLS-Config.
        """
        raise NotImplementedError

    def build_all(self, cfg: DeploymentConfig) -> list[dict]:
        """Erzeugt alle benötigten Manifeste für dieses Deployment.

        Ruft alle build_*-Methoden auf und filtert None-Werte heraus.
        Reihenfolge: Secret, Deployment, Service, Ingress.

        Args:
            cfg: Deployment-Konfiguration.

        Returns:
            Liste aller K8s-Manifeste (keine None-Einträge).
        """
        raise NotImplementedError
