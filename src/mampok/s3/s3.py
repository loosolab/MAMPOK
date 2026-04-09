"""S3-Client — boto3-Wrapper für alle Storage-Operationen."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


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
        self.bucket = bucket
        if client is not None:
            self.client = client
        else:
            session = boto3.Session(
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
            )
            self.client = session.client(
                "s3",
                endpoint_url=endpoint_url,
                config=Config(signature_version="s3v4"),
            )

    def upload(self, local_path: Path, key: str) -> None:
        """Lädt eine lokale Datei in den konfigurierten Bucket hoch.

        Args:
            local_path: Pfad zur lokalen Datei.
            key: S3-Objekt-Key (Zielname im Bucket).
        """
        logger.debug("upload: %s -> s3://%s/%s", local_path, self.bucket, key)
        self.client.upload_file(str(local_path), self.bucket, key)

    def download_to_local(self, key: str, local_path: Path) -> Path:
        """Lädt ein S3-Objekt auf das lokale Filesystem herunter.

        Args:
            key: S3-Objekt-Key.
            local_path: Zielpfad auf dem lokalen Filesystem.

        Returns:
            Pfad zur heruntergeladenen Datei.
        """
        logger.debug("download: s3://%s/%s -> %s", self.bucket, key, local_path)
        self.client.download_file(self.bucket, key, str(local_path))
        return local_path

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
        self.client.copy_object(
            CopySource={"Bucket": source_bucket, "Key": source_key},
            Bucket=dest_bucket,
            Key=dest_key,
        )

    def compare_size(self, key: str, local_path: Path) -> bool:
        """Vergleicht die Dateigröße zwischen S3-Objekt und lokaler Datei.

        Gibt False zurück wenn das Objekt nicht existiert oder die Größen
        abweichen. Kann als Pre-Upload-Check genutzt werden:
        ``if not compare_size(key, local): upload(local, key)``

        Args:
            key: S3-Objekt-Key.
            local_path: Pfad zur lokalen Datei.

        Returns:
            True wenn das Objekt existiert und die Größen übereinstimmen.
            False wenn das Objekt nicht existiert oder die Größen abweichen.
        """
        try:
            response = self.client.head_object(Bucket=self.bucket, Key=key)
        except ClientError:
            return False
        s3_size = response["ContentLength"]
        local_size = os.path.getsize(local_path)
        return s3_size == local_size

    def list_objects(self, prefix: str = "") -> list[str]:
        """Listet alle Objekt-Keys im Bucket auf.

        Args:
            prefix: Optionaler Prefix-Filter.

        Returns:
            Liste aller Objekt-Keys im Bucket.
        """
        paginator = self.client.get_paginator("list_objects_v2")
        keys = []
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                keys.append(obj["Key"])
        return keys

    def create_bucket(self) -> None:
        """Erstellt den konfigurierten Bucket (idempotent).

        Kein Fehler wenn der Bucket bereits existiert.
        """
        if not self.bucket_exists():
            logger.debug("create_bucket: %s", self.bucket)
            self.client.create_bucket(Bucket=self.bucket)

    def set_lifecycle_policy(self) -> None:
        """Setzt eine Lifecycle-Rule zum Abbruch unvollständiger Multipart-Uploads nach 7 Tagen.

        Verhindert unbeabsichtigte Storage-Kosten durch unterbrochene Uploads
        (z.B. wenn der preStop-Sync per SIGKILL abgebrochen wurde).
        Kompatibel mit AWS S3 und MinIO self-hosted.
        """
        logger.debug("set_lifecycle_policy: %s", self.bucket)
        self.client.put_bucket_lifecycle_configuration(
            Bucket=self.bucket,
            LifecycleConfiguration={
                "Rules": [
                    {
                        "ID": "abort-incomplete-multipart",
                        "Status": "Enabled",
                        "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": 7},
                    }
                ]
            },
        )

    def delete_bucket(self) -> None:
        """Leert den Bucket und löscht ihn (idempotent).

        Löscht zuerst alle Objekte, dann den Bucket selbst.
        Kein Fehler wenn der Bucket nicht existiert.
        """
        if not self.bucket_exists():
            return
        logger.debug("delete_bucket: %s", self.bucket)
        for key in self.list_objects():
            self.client.delete_object(Bucket=self.bucket, Key=key)
        self.client.delete_bucket(Bucket=self.bucket)

    def bucket_exists(self) -> bool:
        """Prüft ob der konfigurierte Bucket existiert.

        Returns:
            True wenn der Bucket existiert, False wenn nicht.
        """
        try:
            self.client.head_bucket(Bucket=self.bucket)
            return True
        except ClientError:
            return False
