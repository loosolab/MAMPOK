"""Python-API — programmatische Schnittstelle für andere Tools."""

from __future__ import annotations

from pathlib import Path

from mampok.interfaces.base import MampokInterface


class API(MampokInterface):
    """Importierbare Python-API für programmatischen Mampok-Zugriff.

    Für jede Operation wird pro Mamplan eine Mampok-Instanz erstellt
    und die Operation delegiert.

    Im Gegensatz zur CLI:
    - Kein interaktiver User-Input
    - edit_mamplan() nimmt direkte Dict-Argumente (kein String-Parsing)
    - Zusätzliche Methoden: create_info_json(), download(), create_mamplan_writer()
    """

    def deploy(self, mamplan_path: Path) -> None:
        """Deployt ein Projekt auf Kubernetes.

        Args:
            mamplan_path: Pfad zur Mamplan-Datei.
        """
        raise NotImplementedError

    def stop(self, mamplan_path: Path) -> None:
        """Stoppt ein Deployment (K8s-Ressourcen entfernen, S3 bleibt).

        Args:
            mamplan_path: Pfad zur Mamplan-Datei.
        """
        raise NotImplementedError

    def stop_expired(self, repository: Path) -> None:
        """Stoppt alle abgelaufenen Deployments in einem Repository.

        Args:
            repository: Pfad zum Mamplan-Repository-Verzeichnis.
        """
        raise NotImplementedError

    def create_mamplan(self, **kwargs) -> None:
        """Erstellt einen neuen Mamplan programmatisch.

        Args:
            **kwargs: Mamplan-Konfigurationsfelder.
        """
        raise NotImplementedError

    def edit_mamplan(self, mamplan_path: Path, **kwargs) -> None:
        """Bearbeitet einen Mamplan mit direkten Dict-Argumenten.

        Spezifischer als die CLI-Version: Nimmt geparste Felder entgegen
        statt "key:key:value"-Strings.

        Args:
            mamplan_path: Pfad zur Mamplan-Datei.
            **kwargs: Zu ändernde Felder (direkt, kein String-Parsing).
        """
        raise NotImplementedError

    def check_status_report(self, repository: Path) -> None:
        """Erstellt einen Status-Report aller Mamplans im Repository.

        Args:
            repository: Pfad zum Mamplan-Repository-Verzeichnis.
        """
        raise NotImplementedError

    def redeploy(self, mamplan_path: Path) -> None:
        """Stoppt und deployt ein Projekt neu.

        Args:
            mamplan_path: Pfad zur Mamplan-Datei.
        """
        raise NotImplementedError

    def create_info_json(
        self,
        repository: Path,
        output: Path | None = None,
    ) -> dict:
        """Erzeugt eine Info-JSON mit Metadaten aller Projekte im Repository.

        Args:
            repository: Pfad zum Mamplan-Repository-Verzeichnis.
            output: Optionaler Pfad zum Speichern der JSON-Datei.

        Returns:
            Dict mit Projekt-Metadaten:
            {"projects": {project_id: {mamplan, tags, url, status, ...}}}
        """
        raise NotImplementedError

    def download(self, mamplan_path: Path, output: Path) -> None:
        """Lädt Dateien aus einem laufenden Container herunter.

        Nutzt `downloadpaths` aus dem Mamplate/Mamplan um Dateipfade im
        Container zu bestimmen und kopiert sie via kubectl cp.

        Args:
            mamplan_path: Pfad zur Mamplan-Datei.
            output: Lokales Zielverzeichnis für die heruntergeladenen Dateien.
        """
        raise NotImplementedError

    def create_mamplan_writer(
        self,
        project_id: str,
        tool: str,
        cluster: str,
        output: Path,
    ) -> None:
        """Erstellt einen Mamplan für Self-Service-Deployments.

        Args:
            project_id: Eindeutige Projekt-ID.
            tool: Tool-Name (muss in Mamplates vorhanden sein).
            cluster: Ziel-Cluster-Identifier.
            output: Ausgabepfad für den generierten Mamplan.
        """
        raise NotImplementedError
