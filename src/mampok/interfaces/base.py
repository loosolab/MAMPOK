"""MampokInterface — abstrakte Basisklasse für CLI und API."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class MampokInterface(ABC):
    """Abstrakte Basisklasse für alle Mampok-Interfaces.

    Definiert die gemeinsame Schnittstelle für CLI und Python-API.
    Beide Implementierungen delegieren an Mampok-Instanzen.
    """

    @abstractmethod
    def deploy(self, mamplan_path: Path) -> None:
        """Deployt ein Projekt auf Kubernetes.

        Args:
            mamplan_path: Pfad zur Mamplan-Datei oder -Verzeichnis.
        """
        raise NotImplementedError

    @abstractmethod
    def stop(self, mamplan_path: Path) -> None:
        """Stoppt ein Deployment (K8s-Ressourcen entfernen, S3 bleibt).

        Args:
            mamplan_path: Pfad zur Mamplan-Datei oder -Verzeichnis.
        """
        raise NotImplementedError

    @abstractmethod
    def stop_expired(self, repository: Path) -> None:
        """Stoppt alle abgelaufenen Deployments in einem Repository.

        Args:
            repository: Pfad zum Mamplan-Repository-Verzeichnis.
        """
        raise NotImplementedError

    @abstractmethod
    def create_mamplan(self, **kwargs) -> None:
        """Erstellt einen neuen Mamplan.

        Args:
            **kwargs: Mamplan-Konfigurationsfelder.
        """
        raise NotImplementedError

    @abstractmethod
    def edit_mamplan(self, mamplan_path: Path, **kwargs) -> None:
        """Bearbeitet einen bestehenden Mamplan.

        Args:
            mamplan_path: Pfad zur Mamplan-Datei.
            **kwargs: Zu ändernde Felder.
        """
        raise NotImplementedError

    @abstractmethod
    def redeploy(self, mamplan_path: Path) -> None:
        """Stoppt und deployt ein Projekt neu.

        Args:
            mamplan_path: Pfad zur Mamplan-Datei oder -Verzeichnis.
        """
        raise NotImplementedError

    @abstractmethod
    def check_status_report(self, repository: Path) -> None:
        """Erstellt einen Status-Report aller Mamplans im Repository.

        Args:
            repository: Pfad zum Mamplan-Repository-Verzeichnis.
        """
        raise NotImplementedError
