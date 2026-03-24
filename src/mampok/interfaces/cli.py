"""CLI-Interface — Typer-basierte Kommandozeilen-Schnittstelle."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from mampok.interfaces.base import MampokInterface

app = typer.Typer(
    name="mampok",
    help="Kubernetes deployment manager for bioinformatics pipelines.",
    no_args_is_help=True,
)


class CLI(MampokInterface):
    """Typer-basierte CLI für Mampok.

    Iteriert über mehrere Mamplans mit Error Tolerance:
    Schlägt ein Mamplan fehl, wird der Fehler gesammelt und mit dem
    nächsten weitergemacht. Am Ende werden alle Fehler reportiert.

    Args:
        mamplans: Liste von Mamplan-Instanzen die verarbeitet werden sollen.
    """

    def __init__(self, mamplans: list) -> None:
        """Initialisiert CLI.

        Args:
            mamplans: Liste von Mamplan-Instanzen.
        """
        raise NotImplementedError

    def deploy(self, mamplan_path: Path) -> None:
        """Deployt ein oder mehrere Projekte.

        Args:
            mamplan_path: Pfad zur Mamplan-Datei oder -Verzeichnis.
        """
        raise NotImplementedError

    def delete(self, mamplan_path: Path) -> None:
        """Löscht ein oder mehrere Deployments.

        Args:
            mamplan_path: Pfad zur Mamplan-Datei oder -Verzeichnis.
        """
        raise NotImplementedError

    def delete_expired(self, repository: Path) -> None:
        """Löscht alle abgelaufenen Deployments in einem Repository.

        Args:
            repository: Pfad zum Mamplan-Repository-Verzeichnis.
        """
        raise NotImplementedError

    def create_mamplan(self, **kwargs) -> None:
        """Erstellt einen neuen Mamplan interaktiv.

        Args:
            **kwargs: Mamplan-Konfigurationsfelder.
        """
        raise NotImplementedError

    def edit_mamplan(self, mamplan_path: Path, **kwargs) -> None:
        """Bearbeitet einen Mamplan via key:key:value-Strings.

        Args:
            mamplan_path: Pfad zur Mamplan-Datei.
            **kwargs: Zu ändernde Felder.
        """
        raise NotImplementedError

    def redeploy(self, mamplan_path: Path) -> None:
        """Löscht und deployt ein Projekt neu.

        Args:
            mamplan_path: Pfad zur Mamplan-Datei.
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


# Typer-Commands — werden in der Implementierungsphase befüllt

@app.command()
def deploy(
    mamplan: Annotated[Path, typer.Argument(help="Path to mamplan file or directory.")],
) -> None:
    """Deploy a project to Kubernetes."""
    raise NotImplementedError


@app.command()
def delete(
    mamplan: Annotated[Path, typer.Argument(help="Path to mamplan file or directory.")],
    s3_clean: Annotated[bool, typer.Option(help="Also delete S3 bucket.")] = False,
) -> None:
    """Delete a deployment and its Kubernetes resources."""
    raise NotImplementedError


@app.command()
def delete_expired(
    repository: Annotated[Path, typer.Argument(help="Path to mamplan repository.")],
) -> None:
    """Delete all expired deployments in a repository."""
    raise NotImplementedError


@app.command()
def redeploy(
    mamplan: Annotated[Path, typer.Argument(help="Path to mamplan file.")],
) -> None:
    """Delete and redeploy a project."""
    raise NotImplementedError


@app.command()
def create_mamplan(
    project_id: Annotated[str, typer.Option(help="Unique project ID.")],
    tool: Annotated[str, typer.Option(help="Tool name.")],
    cluster: Annotated[str, typer.Option(help="Target cluster.")],
    output: Annotated[Path, typer.Option(help="Output path for generated mamplan.")],
) -> None:
    """Create a new mamplan (mamplan_writer)."""
    raise NotImplementedError


@app.command()
def edit_mamplan(
    mamplan: Annotated[Path, typer.Argument(help="Path to mamplan file.")],
    fields: Annotated[list[str], typer.Option("--edit", "-e", help="Fields to edit: key:key:value.")],
) -> None:
    """Edit mamplan fields and redeploy."""
    raise NotImplementedError
