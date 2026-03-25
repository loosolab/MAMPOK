"""Tests für S3-Client."""

from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest
from botocore.exceptions import ClientError

from mampok.s3.s3 import S3


def make_client_error(code: str = "404") -> ClientError:
    """Erstellt einen ClientError mit gegebenem HTTP-Statuscode."""
    return ClientError(
        {"Error": {"Code": code, "Message": "Test error"}},
        "HeadBucket",
    )


@pytest.fixture
def mock_client() -> MagicMock:
    """Gemockter boto3 S3-Client."""
    return MagicMock()


@pytest.fixture
def s3(mock_client: MagicMock) -> S3:
    """S3-Instanz mit injiziertem Mock-Client."""
    return S3(bucket="test-bucket", client=mock_client)


class TestS3Init:
    def test_with_injected_client(self, mock_client: MagicMock) -> None:
        instance = S3(bucket="my-bucket", client=mock_client)
        assert instance.bucket == "my-bucket"
        assert instance.client is mock_client

    def test_with_credentials(self) -> None:
        mock_boto3_client = MagicMock()
        mock_session = MagicMock()
        mock_session.client.return_value = mock_boto3_client

        with patch("mampok.s3.s3.boto3.Session", return_value=mock_session) as mock_session_cls:
            instance = S3(
                bucket="my-bucket",
                endpoint_url="http://minio:9000",
                access_key="key",
                secret_key="secret",
            )

        mock_session_cls.assert_called_once_with(
            aws_access_key_id="key",
            aws_secret_access_key="secret",
        )
        mock_session.client.assert_called_once()
        call_kwargs = mock_session.client.call_args
        assert call_kwargs[0][0] == "s3"
        assert call_kwargs[1]["endpoint_url"] == "http://minio:9000"
        assert instance.client is mock_boto3_client


class TestS3BucketExists:
    def test_bucket_exists(self, s3: S3, mock_client: MagicMock) -> None:
        mock_client.head_bucket.return_value = {}
        assert s3.bucket_exists() is True
        mock_client.head_bucket.assert_called_once_with(Bucket="test-bucket")

    def test_bucket_not_exists(self, s3: S3, mock_client: MagicMock) -> None:
        mock_client.head_bucket.side_effect = make_client_error("404")
        assert s3.bucket_exists() is False


class TestS3CreateBucket:
    def test_create_new_bucket(self, s3: S3, mock_client: MagicMock) -> None:
        mock_client.head_bucket.side_effect = make_client_error("404")
        s3.create_bucket()
        mock_client.create_bucket.assert_called_once_with(Bucket="test-bucket")

    def test_bucket_already_exists(self, s3: S3, mock_client: MagicMock) -> None:
        mock_client.head_bucket.return_value = {}
        s3.create_bucket()
        mock_client.create_bucket.assert_not_called()


class TestS3Upload:
    def test_upload_ok(self, s3: S3, mock_client: MagicMock, tmp_path: Path) -> None:
        local_file = tmp_path / "data.h5ad"
        local_file.write_bytes(b"content")
        s3.upload(local_file, "data.h5ad")
        mock_client.upload_file.assert_called_once_with(
            str(local_file), "test-bucket", "data.h5ad"
        )

    def test_upload_propagates_client_error(
        self, s3: S3, mock_client: MagicMock, tmp_path: Path
    ) -> None:
        local_file = tmp_path / "data.h5ad"
        local_file.write_bytes(b"content")
        mock_client.upload_file.side_effect = make_client_error("NoSuchBucket")
        with pytest.raises(ClientError):
            s3.upload(local_file, "data.h5ad")


class TestS3CompareSize:
    def test_same_size_returns_true(
        self, s3: S3, mock_client: MagicMock, tmp_path: Path
    ) -> None:
        local_file = tmp_path / "file.txt"
        local_file.write_bytes(b"hello")
        mock_client.head_object.return_value = {"ContentLength": 5}
        assert s3.compare_size("file.txt", local_file) is True

    def test_different_size_returns_false(
        self, s3: S3, mock_client: MagicMock, tmp_path: Path
    ) -> None:
        local_file = tmp_path / "file.txt"
        local_file.write_bytes(b"hello")
        mock_client.head_object.return_value = {"ContentLength": 999}
        assert s3.compare_size("file.txt", local_file) is False

    def test_key_not_found_returns_false(
        self, s3: S3, mock_client: MagicMock, tmp_path: Path
    ) -> None:
        local_file = tmp_path / "file.txt"
        local_file.write_bytes(b"hello")
        mock_client.head_object.side_effect = make_client_error("NoSuchKey")
        assert s3.compare_size("missing.txt", local_file) is False


class TestS3DownloadToLocal:
    def test_download_ok(self, s3: S3, mock_client: MagicMock, tmp_path: Path) -> None:
        local_path = tmp_path / "output.h5ad"
        result = s3.download_to_local("data.h5ad", local_path)
        mock_client.download_file.assert_called_once_with(
            "test-bucket", "data.h5ad", str(local_path)
        )
        assert result == local_path

    def test_key_not_found_propagates(
        self, s3: S3, mock_client: MagicMock, tmp_path: Path
    ) -> None:
        mock_client.download_file.side_effect = make_client_error("NoSuchKey")
        with pytest.raises(ClientError):
            s3.download_to_local("missing.h5ad", tmp_path / "out.h5ad")


class TestS3Copy:
    def test_copy_ok(self, s3: S3, mock_client: MagicMock) -> None:
        s3.copy("src-bucket", "src-key", "dst-bucket", "dst-key")
        mock_client.copy_object.assert_called_once_with(
            CopySource={"Bucket": "src-bucket", "Key": "src-key"},
            Bucket="dst-bucket",
            Key="dst-key",
        )

    def test_source_not_found_propagates(self, s3: S3, mock_client: MagicMock) -> None:
        mock_client.copy_object.side_effect = make_client_error("NoSuchKey")
        with pytest.raises(ClientError):
            s3.copy("src-bucket", "missing", "dst-bucket", "dst-key")


class TestS3ListObjects:
    def test_bucket_with_objects(self, s3: S3, mock_client: MagicMock) -> None:
        paginator = MagicMock()
        paginator.paginate.return_value = [
            {"Contents": [{"Key": "a.txt"}, {"Key": "b.txt"}]}
        ]
        mock_client.get_paginator.return_value = paginator

        result = s3.list_objects()
        assert result == ["a.txt", "b.txt"]
        paginator.paginate.assert_called_once_with(Bucket="test-bucket", Prefix="")

    def test_empty_bucket(self, s3: S3, mock_client: MagicMock) -> None:
        paginator = MagicMock()
        paginator.paginate.return_value = [{}]
        mock_client.get_paginator.return_value = paginator

        result = s3.list_objects()
        assert result == []

    def test_with_prefix(self, s3: S3, mock_client: MagicMock) -> None:
        paginator = MagicMock()
        paginator.paginate.return_value = [
            {"Contents": [{"Key": "data/file.h5ad"}]}
        ]
        mock_client.get_paginator.return_value = paginator

        result = s3.list_objects(prefix="data/")
        assert result == ["data/file.h5ad"]
        paginator.paginate.assert_called_once_with(Bucket="test-bucket", Prefix="data/")

    def test_pagination_multiple_pages(self, s3: S3, mock_client: MagicMock) -> None:
        paginator = MagicMock()
        paginator.paginate.return_value = [
            {"Contents": [{"Key": f"file{i}.txt"} for i in range(1000)]},
            {"Contents": [{"Key": "file1000.txt"}]},
        ]
        mock_client.get_paginator.return_value = paginator

        result = s3.list_objects()
        assert len(result) == 1001
        assert result[-1] == "file1000.txt"


class TestS3DeleteBucket:
    def test_delete_bucket_with_objects(self, s3: S3, mock_client: MagicMock) -> None:
        mock_client.head_bucket.return_value = {}
        paginator = MagicMock()
        paginator.paginate.return_value = [
            {"Contents": [{"Key": "a.txt"}, {"Key": "b.txt"}]}
        ]
        mock_client.get_paginator.return_value = paginator

        s3.delete_bucket()

        assert mock_client.delete_object.call_count == 2
        mock_client.delete_object.assert_any_call(Bucket="test-bucket", Key="a.txt")
        mock_client.delete_object.assert_any_call(Bucket="test-bucket", Key="b.txt")
        mock_client.delete_bucket.assert_called_once_with(Bucket="test-bucket")

    def test_delete_empty_bucket(self, s3: S3, mock_client: MagicMock) -> None:
        mock_client.head_bucket.return_value = {}
        paginator = MagicMock()
        paginator.paginate.return_value = [{}]
        mock_client.get_paginator.return_value = paginator

        s3.delete_bucket()

        mock_client.delete_object.assert_not_called()
        mock_client.delete_bucket.assert_called_once_with(Bucket="test-bucket")

    def test_bucket_not_exists_no_error(self, s3: S3, mock_client: MagicMock) -> None:
        mock_client.head_bucket.side_effect = make_client_error("404")

        s3.delete_bucket()

        mock_client.delete_object.assert_not_called()
        mock_client.delete_bucket.assert_not_called()
