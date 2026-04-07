"""Shared fixtures for Kubernetes module tests."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from mampok.kubernetes.config import DeploymentConfig


@pytest.fixture
def make_config():
    """Factory for DeploymentConfig with sensible defaults."""

    def _make(**overrides) -> DeploymentConfig:
        defaults = {
            "project_id": "testproj",
            "tool": "nginx",
            "image": "nginx:latest",
            "namespace": "default",
            "ports": [8080],
        }
        defaults.update(overrides)
        return DeploymentConfig(**defaults)

    return _make


@pytest.fixture
def sample_s3_credentials() -> dict:
    """S3 credentials dict for testing."""
    return {
        "s3_key": "AKIAIOSFODNN7EXAMPLE",
        "s3_secret": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
    }


@pytest.fixture
def make_auth_config(make_config):
    """Factory für auth-aktivierte DeploymentConfig."""

    def _make(**overrides) -> DeploymentConfig:
        defaults = {
            "auth": True,
            "auth_proxy_image": "registry.example.com/gatekeeper:latest",
            "proxy_port": 9090,
            "ports": [8080],
            "host": "example.com",
            "url": "https://example.com/mynamespace/testproj/nginx/",
        }
        defaults.update(overrides)
        return make_config(**defaults)

    return _make


@pytest.fixture
def mock_api_client() -> MagicMock:
    """MagicMock for kubernetes ApiClient."""
    client = MagicMock()
    client.call_api = MagicMock()
    return client
