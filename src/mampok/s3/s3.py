"""S3 client — boto3 wrapper for all storage operations."""

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
    """Wrapper around boto3 for S3-compatible storage operations.

    Supports AWS S3 as well as compatible endpoints (MinIO, Ceph).

    Args:
        bucket: Default bucket name for operations.
        endpoint_url: S3 endpoint URL. None for AWS default.
        access_key: S3 access key ID.
        secret_key: S3 secret access key.
        client: Optional pre-configured boto3 client (for tests).
    """

    def __init__(
        self,
        bucket: str,
        endpoint_url: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        client: Any | None = None,
    ) -> None:
        """Initialize S3 client.

        Args:
            bucket: Default bucket name.
            endpoint_url: S3 endpoint URL. None for AWS default.
            access_key: S3 access key ID.
            secret_key: S3 secret access key.
            client: Optional pre-configured boto3 client (for tests).
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

    def upload(self, local_path: Path, key: str, callback: Any | None = None) -> None:
        """Upload a local file to the configured bucket.

        Args:
            local_path: Path to the local file.
            key: S3 object key (target name in the bucket).
            callback: Optional boto3 callback invoked with the number of bytes
                transferred. Useful for progress displays.
        """
        logger.debug("upload: %s -> s3://%s/%s", local_path, self.bucket, key)
        self.client.upload_file(str(local_path), self.bucket, key, Callback=callback)

    def download_to_local(self, key: str, local_path: Path) -> Path:
        """Download an S3 object to the local filesystem.

        Args:
            key: S3 object key.
            local_path: Target path on the local filesystem.

        Returns:
            Path to the downloaded file.
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
        """Copy an object between buckets (server-side copy).

        Args:
            source_bucket: Source bucket name.
            source_key: Source object key.
            dest_bucket: Destination bucket name.
            dest_key: Destination object key.
        """
        self.client.copy_object(
            CopySource={"Bucket": source_bucket, "Key": source_key},
            Bucket=dest_bucket,
            Key=dest_key,
        )

    def compare_size(self, key: str, local_path: Path) -> bool:
        """Compare the file size between an S3 object and a local file.

        Returns False if the object does not exist or sizes differ.
        Can be used as a pre-upload check:
        ``if not compare_size(key, local): upload(local, key)``

        Args:
            key: S3 object key.
            local_path: Path to the local file.

        Returns:
            True if the object exists and sizes match.
            False if the object does not exist or sizes differ.
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
        """Create the configured bucket (idempotent).

        No error if the bucket already exists.
        """
        if not self.bucket_exists():
            logger.debug("create_bucket: %s", self.bucket)
            self.client.create_bucket(Bucket=self.bucket)

    def set_lifecycle_policy(self) -> None:
        """Set a lifecycle rule to abort incomplete multipart uploads after 7 days.

        Prevents unintended storage costs from interrupted uploads
        (e.g. when the preStop sync was killed by SIGKILL).
        Fails on older MinIO versions (no support for
        AbortIncompleteMultipartUpload) — errors are logged, not raised.
        """
        logger.debug("set_lifecycle_policy: %s", self.bucket)
        try:
            self.client.put_bucket_lifecycle_configuration(
                Bucket=self.bucket,
                LifecycleConfiguration={
                    "Rules": [
                        {
                            "ID": "abort-incomplete-multipart",
                            "Status": "Enabled",
                            "Filter": {"Prefix": "container_data/"},
                            "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": 7},
                        }
                    ]
                },
            )
        except ClientError as e:
            logger.warning("set_lifecycle_policy failed (MinIO compatibility): %s", e)

    def delete_bucket(self) -> None:
        """Empty the bucket and delete it (idempotent).

        Deletes all objects first, then the bucket itself.
        No error if the bucket does not exist.
        """
        if not self.bucket_exists():
            return
        logger.debug("delete_bucket: %s", self.bucket)
        for key in self.list_objects():
            self.client.delete_object(Bucket=self.bucket, Key=key)
        self.client.delete_bucket(Bucket=self.bucket)

    def bucket_exists(self) -> bool:
        """Check whether the configured bucket exists.

        Returns:
            True if the bucket exists, False otherwise.
        """
        try:
            self.client.head_bucket(Bucket=self.bucket)
            return True
        except ClientError:
            return False
