"""Pytest-Fixtures für Mampok-Orchestrator-Tests."""

from unittest.mock import MagicMock

import pytest

from mampok.config.config import AuthProxyConfig, ClusterConfig, MampokConfig, S3Config
from mampok.kubernetes.manager import DeploymentManager
from mampok.mampok.mampok import Mampok
from mampok.s3.s3 import S3


@pytest.fixture
def mock_mamplan():
    """Mamplan-Mock mit minimalen Daten."""
    mp = MagicMock()
    mp.auth = False
    mp.data = {
        "project": {
            "project_id": "test-proj",
            "tool": "cellxgene",
            "files": [],
            "init_container": [],
        },
        "deployment": {
            "status": False,
            "auth": False,
            "bucket": "test-bucket",
            "lifetime": "2030-12-31T00:00:00+00:00",
            "url": "",
            "cluster": "BN",
        },
        "service": {
            "owner": "alice",
            "organization": [],
        },
    }
    mp.merge_container_config.return_value = {
        "main": {
            "image": "cellxgene:1.0",
            "ports": 8080,
            "resources": {
                "limits": {"cpu": "2", "memory": "4Gi"},
                "requests": {},
            },
            "env": [],
            "args": [],
            "command": [],
        }
    }
    return mp


@pytest.fixture
def mock_mamplate():
    """Mamplate-Mock."""
    return MagicMock()


@pytest.fixture
def mock_kube():
    """DeploymentManager-Mock."""
    kube = MagicMock(spec=DeploymentManager)
    kube._kube = MagicMock()
    kube.deployment_exists.return_value = False
    return kube


@pytest.fixture
def mock_s3():
    """S3-Mock."""
    s3 = MagicMock(spec=S3)
    s3.bucket = "test-bucket"
    s3.compare_size.return_value = True  # default: bereits vorhanden
    return s3


@pytest.fixture
def mock_config():
    """MampokConfig-Mock."""
    cluster = ClusterConfig(
        host="bioinformatics-cluster.example.com",
        namespace="mampok-bn",
        kubeconfig_path="/app/BN_kube_config",
        annotations={"kubernetes.io/ingress.class": "nginx"},
        ingress_class="nginx",
        dnsissuer="letsencrypt-prod",
        dnssecret="route53-creds",
    )
    s3 = S3Config(
        endpoint="https://s3.example.com",
        access_key="mampok-service",
        secret_key="secret123",
        secretname="mpis",
        prefix="mampok-cluster-bn",
    )
    return MampokConfig(
        clusters={"BN": cluster},
        s3=s3,
        mamplan_repo=__import__("pathlib").Path("/app/BCU_REPOSITORY/"),
        mamplates_path=__import__("pathlib").Path("/app/BCU_REPOSITORY/MaMplates"),
        lifetime_days=10,
    )


@pytest.fixture
def mock_config_with_auth():
    """MampokConfig mit auth_proxy-Konfiguration."""
    cluster = ClusterConfig(
        host="bioinformatics-cluster.example.com",
        namespace="mampok-bn",
        kubeconfig_path="/app/BN_kube_config",
        annotations={"kubernetes.io/ingress.class": "nginx"},
        ingress_class="nginx",
        dnsissuer="letsencrypt-prod",
        dnssecret="route53-creds",
        auth_proxy=AuthProxyConfig(
            auth_proxy_image="registry.example.com/gatekeeper:latest",
            proxy_port=9090,
            auth_annotations={"nginx.ingress.kubernetes.io/auth-type": "basic"},
            image_pull_secrets=["regcred"],
        ),
    )
    s3 = S3Config(
        endpoint="https://s3.example.com",
        access_key="mampok-service",
        secret_key="secret123",
        secretname="mpis",
        prefix="mampok-cluster-bn",
    )
    return MampokConfig(
        clusters={"BN": cluster},
        s3=s3,
        mamplan_repo=__import__("pathlib").Path("/app/BCU_REPOSITORY/"),
        mamplates_path=__import__("pathlib").Path("/app/BCU_REPOSITORY/MaMplates"),
        lifetime_days=10,
    )


@pytest.fixture
def mampok(mock_mamplan, mock_mamplate, mock_kube, mock_s3):
    """Mampok-Instanz mit Mock-Dependencies."""
    return Mampok(mock_mamplan, mock_mamplate, mock_kube, mock_s3)
