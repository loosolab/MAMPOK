"""S3-Client — boto3-Wrapper für alle Storage-Operationen."""

from __future__ import annotations

from pathlib import Path
from typing import Any


class S3:
    """Wrapper um boto3 für S3-kompatible Storage-Operationen.

    Unterstützt AWS S3 sowie kompatible Endpoints (MinIO, Ceph).

    Args:
        bucket: Standard-Bucket-Name für Operationen.
        endpoint_url: S3-Endpoint-URL. None für AWS-Standard.
        access_key: S3-Access-Key-ID.
        secret_key: S3-Secret-Access-Key.
        client: Optionaler vorkonfigurierter boto3-Client (für Tests).
    """

    def __init__(
        self,
        bucket: str,
        endpoint_url: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        client: Any | None = None,
    ) -> None:
        """Initialisiert S3-Client.

        Args:
            bucket: Standard-Bucket-Name.
            endpoint_url: S3-Endpoint-URL. None für AWS-Standard.
            access_key: S3-Access-Key-ID.
            secret_key: S3-Secret-Access-Key.
            client: Optionaler vorkonfigurierter boto3-Client (für Tests).
        """
        raise NotImplementedError

    def upload(self, local_path: Path, key: str) -> None:
        """Lädt eine lokale Datei in den konfigurierten Bucket hoch.

        Args:
            local_path: Pfad zur lokalen Datei.
            key: S3-Objekt-Key (Zielname im Bucket).
        """
        raise NotImplementedError

    def download_to_local(self, key: str, local_path: Path) -> Path:
        """Lädt ein S3-Objekt auf das lokale Filesystem herunter.

        Args:
            key: S3-Objekt-Key.
            local_path: Zielpfad auf dem lokalen Filesystem.

        Returns:
            Pfad zur heruntergeladenen Datei.
        """
        raise NotImplementedError

    def copy(
        self,
        source_bucket: str,
        source_key: str,
        dest_bucket: str,
        dest_key: str,
    ) -> None:
        """Kopiert ein Objekt zwischen Buckets (server-side copy).

        Args:
            source_bucket: Quell-Bucket-Name.
            source_key: Quell-Objekt-Key.
            dest_bucket: Ziel-Bucket-Name.
            dest_key: Ziel-Objekt-Key.
        """
        raise NotImplementedError

    def compare_size(self, key: str, local_path: Path) -> bool:
        """Vergleicht die Dateigröße zwischen S3-Objekt und lokaler Datei.

        Args:
            key: S3-Objekt-Key.
            local_path: Pfad zur lokalen Datei.

        Returns:
            True wenn die Größen übereinstimmen, False wenn abweichend.
        """
        raise NotImplementedError
