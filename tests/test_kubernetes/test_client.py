"""Tests für KubeClient."""

from __future__ import annotations

from unittest.mock import MagicMock, call

import pytest
from kubernetes.client.rest import ApiException

from mampok.kubernetes.client import KubeClient


class TestKubeClientInit:
    """Tests for KubeClient initialization."""

    def test_init_with_api_client(self, mock_api_client):
        client = KubeClient("default", mock_api_client)
        assert client._namespace == "default"
        assert client._api_client is mock_api_client

    def test_init_without_api_client_raises(self):
        with pytest.raises(TypeError):
            KubeClient("default")


class TestKindRouting:
    """Tests for kind routing (_resolve_path)."""

    @pytest.mark.parametrize(
        "kind,expected_fragment",
        [
            ("Deployment", "/apis/apps/v1/namespaces/ns/deployments/myapp"),
            ("Service", "/api/v1/namespaces/ns/services/myapp"),
            ("Secret", "/api/v1/namespaces/ns/secrets/myapp"),
            ("Ingress", "/apis/networking.k8s.io/v1/namespaces/ns/ingresses/myapp"),
            ("Job", "/apis/batch/v1/namespaces/ns/jobs/myapp"),
        ],
    )
    def test_supported_kinds(self, mock_api_client, kind, expected_fragment):
        client = KubeClient("ns", mock_api_client)
        path = client._resolve_path(kind, "myapp")
        assert path == expected_fragment

    def test_unknown_kind_raises(self, mock_api_client):
        client = KubeClient("ns", mock_api_client)
        with pytest.raises(ValueError, match="Unsupported kind 'Pod'"):
            client._resolve_path("Pod", "mypod")


class TestApply:
    """Tests for KubeClient.apply."""

    def _make_manifest(self, kind="Deployment", name="test"):
        return {
            "apiVersion": "apps/v1",
            "kind": kind,
            "metadata": {"name": name},
            "spec": {},
        }

    def test_apply_calls_api_with_ssa(self, mock_api_client):
        result_obj = MagicMock()
        result_obj.to_dict.return_value = {"kind": "Deployment", "metadata": {"name": "test"}}
        mock_api_client.call_api.return_value = result_obj

        client = KubeClient("ns", mock_api_client)
        manifest = self._make_manifest()
        result = client.apply(manifest)

        mock_api_client.call_api.assert_called_once()
        call_kwargs = mock_api_client.call_api.call_args
        assert call_kwargs.kwargs["method"] == "PATCH"
        assert call_kwargs.kwargs["header_params"]["Content-Type"] == "application/apply-patch+yaml"
        assert ("fieldManager", "mampok") in call_kwargs.kwargs["query_params"]
        assert ("force", "true") in call_kwargs.kwargs["query_params"]
        assert result == {"kind": "Deployment", "metadata": {"name": "test"}}

    @pytest.mark.parametrize("kind", ["Deployment", "Service", "Secret", "Ingress"])
    def test_apply_per_kind(self, mock_api_client, kind):
        result_obj = MagicMock()
        result_obj.to_dict.return_value = {"kind": kind}
        mock_api_client.call_api.return_value = result_obj

        client = KubeClient("ns", mock_api_client)
        manifest = self._make_manifest(kind=kind, name="res")
        client.apply(manifest)

        call_kwargs = mock_api_client.call_api.call_args
        assert call_kwargs.kwargs["response_type"] == KubeClient._RESPONSE_TYPES[kind]


class TestApplyMany:
    """Tests for KubeClient.apply_many."""

    def test_skips_none(self, mock_api_client):
        result_obj = MagicMock()
        result_obj.to_dict.return_value = {"kind": "Secret"}
        mock_api_client.call_api.return_value = result_obj

        client = KubeClient("ns", mock_api_client)
        manifests = [
            None,
            {"apiVersion": "v1", "kind": "Secret", "metadata": {"name": "s1"}, "data": {}},
            None,
        ]
        results = client.apply_many(manifests)

        assert len(results) == 1
        assert mock_api_client.call_api.call_count == 1

    def test_fail_fast(self, mock_api_client):
        result_obj = MagicMock()
        result_obj.to_dict.return_value = {"kind": "Secret"}
        mock_api_client.call_api.side_effect = [
            result_obj,
            ApiException(status=500, reason="Internal"),
        ]

        client = KubeClient("ns", mock_api_client)
        manifests = [
            {"apiVersion": "v1", "kind": "Secret", "metadata": {"name": "s1"}, "data": {}},
            {"apiVersion": "apps/v1", "kind": "Deployment", "metadata": {"name": "d1"}, "spec": {}},
        ]

        with pytest.raises(ApiException):
            client.apply_many(manifests)

        assert mock_api_client.call_api.call_count == 2


class TestGet:
    """Tests for KubeClient.get."""

    def test_get_success(self, mock_api_client):
        result_obj = MagicMock()
        result_obj.to_dict.return_value = {"kind": "Deployment", "metadata": {"name": "d1"}}
        mock_api_client.call_api.return_value = result_obj

        client = KubeClient("ns", mock_api_client)
        result = client.get("Deployment", "d1")

        assert result == {"kind": "Deployment", "metadata": {"name": "d1"}}
        call_kwargs = mock_api_client.call_api.call_args
        assert call_kwargs.kwargs["method"] == "GET"

    def test_get_404_propagates(self, mock_api_client):
        mock_api_client.call_api.side_effect = ApiException(status=404, reason="Not Found")

        client = KubeClient("ns", mock_api_client)
        with pytest.raises(ApiException):
            client.get("Deployment", "nonexistent")


class TestDelete:
    """Tests for KubeClient.delete."""

    def test_delete_success(self, mock_api_client):
        result_obj = MagicMock()
        mock_api_client.call_api.return_value = result_obj

        client = KubeClient("ns", mock_api_client)
        client.delete("Deployment", "d1")

        call_kwargs = mock_api_client.call_api.call_args
        assert call_kwargs.kwargs["method"] == "DELETE"

    def test_delete_404_ignored(self, mock_api_client):
        mock_api_client.call_api.side_effect = ApiException(status=404, reason="Not Found")

        client = KubeClient("ns", mock_api_client)
        client.delete("Deployment", "nonexistent")  # Should not raise

    def test_delete_500_propagates(self, mock_api_client):
        mock_api_client.call_api.side_effect = ApiException(status=500, reason="Internal")

        client = KubeClient("ns", mock_api_client)
        with pytest.raises(ApiException):
            client.delete("Deployment", "d1")


class TestExists:
    """Tests for KubeClient.exists."""

    def test_exists_true(self, mock_api_client):
        result_obj = MagicMock()
        result_obj.to_dict.return_value = {"kind": "Deployment"}
        mock_api_client.call_api.return_value = result_obj

        client = KubeClient("ns", mock_api_client)
        assert client.exists("Deployment", "d1") is True

    def test_exists_false(self, mock_api_client):
        mock_api_client.call_api.side_effect = ApiException(status=404, reason="Not Found")

        client = KubeClient("ns", mock_api_client)
        assert client.exists("Deployment", "nonexistent") is False


class TestPatch:
    """Tests for KubeClient.patch."""

    def test_patch_content_type(self, mock_api_client):
        result_obj = MagicMock()
        result_obj.to_dict.return_value = {"kind": "Deployment"}
        mock_api_client.call_api.return_value = result_obj

        client = KubeClient("ns", mock_api_client)
        client.patch("Deployment", "d1", {"spec": {"replicas": 3}})

        call_kwargs = mock_api_client.call_api.call_args
        assert call_kwargs.kwargs["method"] == "PATCH"
        assert (
            call_kwargs.kwargs["header_params"]["Content-Type"]
            == "application/strategic-merge-patch+json"
        )
