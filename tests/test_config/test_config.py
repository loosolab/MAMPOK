"""Tests für MampokConfig — Config-Modul."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import jsonschema
import pytest

import jsonschema

from mampok.config import AuthProxyConfig, ClusterConfig, MampokConfig, S3Config


MINIMAL_CONFIG = {
    "cluster": {
        "BN": {
            "host": "bioinformatics-cluster.example.com",
            "namespace": "mampok-bn",
            "kubeconfig_path": "/app/BN_kube_config",
        }
    },
    "s3": {
        "endpoint": "https://s3.example.com",
        "access_key": "mampok-service",
        "secret_key": "secret123",
        "secretname": "mpis",
    },
    "mamplan_repo": "/app/BCU_REPOSITORY/",
    "mamplates_path": "/app/BCU_REPOSITORY/MaMplates",
    "lifetime_days": 10,
}

FULL_CONFIG = {
    "cluster": {
        "BN": {
            "host": "bioinformatics-cluster.example.com",
            "namespace": "mampok-bn",
            "kubeconfig_path": "/app/BN_kube_config",
            "annotations": {"kubernetes.io/ingress.class": "nginx"},
            "ingress_class": "nginx",
            "dnsissuer": "letsencrypt-prod",
            "dnssecret": "route53-creds",
        },
        "BN_public": {
            "host": "bioinformatics-cluster2.example.com",
            "namespace": "mampok-public",
            "kubeconfig_path": "/app/BN_public_kube_config",
        },
    },
    "s3": {
        "endpoint": "https://s3.example.com",
        "access_key": "mampok-service",
        "secret_key": "secret123",
        "secretname": "mpis",
        "prefix": "mampok-cluster-bn",
    },
    "mamplan_repo": "/app/BCU_REPOSITORY/",
    "mamplates_path": "/app/BCU_REPOSITORY/MaMplates",
    "lifetime_days": 10,
}


class TestMampokConfigFromDict:
    """Tests für MampokConfig.from_dict."""

    def test_minimal_config_valid(self):
        cfg = MampokConfig.from_dict(MINIMAL_CONFIG)
        assert cfg.lifetime_days == 10
        assert cfg.mamplan_repo == Path("/app/BCU_REPOSITORY/")
        assert cfg.mamplates_path == Path("/app/BCU_REPOSITORY/MaMplates")

    def test_full_config_valid(self):
        cfg = MampokConfig.from_dict(FULL_CONFIG)
        assert len(cfg.clusters) == 2
        assert "BN" in cfg.clusters
        assert "BN_public" in cfg.clusters

    def test_cluster_fields_mapped(self):
        cfg = MampokConfig.from_dict(FULL_CONFIG)
        bn = cfg.clusters["BN"]
        assert bn.host == "bioinformatics-cluster.example.com"
        assert bn.namespace == "mampok-bn"
        assert bn.kubeconfig_path == "/app/BN_kube_config"
        assert bn.annotations == {"kubernetes.io/ingress.class": "nginx"}
        assert bn.ingress_class == "nginx"
        assert bn.dnsissuer == "letsencrypt-prod"
        assert bn.dnssecret == "route53-creds"

    def test_optional_cluster_fields_default_to_empty(self):
        cfg = MampokConfig.from_dict(MINIMAL_CONFIG)
        bn = cfg.clusters["BN"]
        assert bn.annotations == {}
        assert bn.ingress_class == ""
        assert bn.dnsissuer == ""
        assert bn.dnssecret == ""

    def test_s3_fields_mapped(self):
        cfg = MampokConfig.from_dict(FULL_CONFIG)
        assert cfg.s3.endpoint == "https://s3.example.com"
        assert cfg.s3.access_key == "mampok-service"
        assert cfg.s3.secret_key == "secret123"
        assert cfg.s3.secretname == "mpis"
        assert cfg.s3.prefix == "mampok-cluster-bn"

    def test_s3_prefix_optional_defaults_to_empty(self):
        cfg = MampokConfig.from_dict(MINIMAL_CONFIG)
        assert cfg.s3.prefix == ""

    def test_paths_are_path_objects(self):
        cfg = MampokConfig.from_dict(MINIMAL_CONFIG)
        assert isinstance(cfg.mamplan_repo, Path)
        assert isinstance(cfg.mamplates_path, Path)

    def test_missing_cluster_raises(self):
        data = {k: v for k, v in MINIMAL_CONFIG.items() if k != "cluster"}
        with pytest.raises(jsonschema.ValidationError):
            MampokConfig.from_dict(data)

    def test_empty_cluster_dict_raises(self):
        import copy
        data = copy.deepcopy(MINIMAL_CONFIG)
        data["cluster"] = {}
        with pytest.raises(jsonschema.ValidationError):
            MampokConfig.from_dict(data)

    def test_missing_cluster_host_raises(self):
        import copy
        data = copy.deepcopy(MINIMAL_CONFIG)
        del data["cluster"]["BN"]["host"]
        with pytest.raises(jsonschema.ValidationError):
            MampokConfig.from_dict(data)

    def test_missing_cluster_kubeconfig_path_raises(self):
        import copy
        data = copy.deepcopy(MINIMAL_CONFIG)
        del data["cluster"]["BN"]["kubeconfig_path"]
        with pytest.raises(jsonschema.ValidationError):
            MampokConfig.from_dict(data)

    def test_missing_s3_raises(self):
        data = {k: v for k, v in MINIMAL_CONFIG.items() if k != "s3"}
        with pytest.raises(jsonschema.ValidationError):
            MampokConfig.from_dict(data)

    def test_missing_s3_access_key_raises(self):
        import copy
        data = copy.deepcopy(MINIMAL_CONFIG)
        del data["s3"]["access_key"]
        with pytest.raises(jsonschema.ValidationError):
            MampokConfig.from_dict(data)

    def test_wrong_type_lifetime_days_raises(self):
        import copy
        data = copy.deepcopy(MINIMAL_CONFIG)
        data["lifetime_days"] = "ten"
        with pytest.raises(jsonschema.ValidationError):
            MampokConfig.from_dict(data)

    def test_lifetime_days_minimum_1(self):
        import copy
        data = copy.deepcopy(MINIMAL_CONFIG)
        data["lifetime_days"] = 0
        with pytest.raises(jsonschema.ValidationError):
            MampokConfig.from_dict(data)

    def test_schema_is_cached(self):
        MampokConfig._schema_cache = None
        MampokConfig.from_dict(MINIMAL_CONFIG)
        assert MampokConfig._schema_cache is not None
        cached = MampokConfig._schema_cache
        MampokConfig.from_dict(MINIMAL_CONFIG)
        assert MampokConfig._schema_cache is cached  # same object


class TestMampokConfigFromFile:
    """Tests für MampokConfig.from_file."""

    def test_load_from_file(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(MINIMAL_CONFIG), encoding="utf-8")
        cfg = MampokConfig.from_file(config_file)
        assert cfg.lifetime_days == 10

    def test_file_not_found_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            MampokConfig.from_file(tmp_path / "nonexistent.json")

    def test_invalid_json_raises(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text("not valid json", encoding="utf-8")
        with pytest.raises(Exception):
            MampokConfig.from_file(config_file)


class TestGetCluster:
    """Tests für MampokConfig.get_cluster."""

    def test_returns_cluster_config(self):
        cfg = MampokConfig.from_dict(FULL_CONFIG)
        bn = cfg.get_cluster("BN")
        assert isinstance(bn, ClusterConfig)
        assert bn.host == "bioinformatics-cluster.example.com"

    def test_unknown_cluster_raises_key_error(self):
        cfg = MampokConfig.from_dict(MINIMAL_CONFIG)
        with pytest.raises(KeyError, match="Unknown cluster"):
            cfg.get_cluster("NONEXISTENT")


class TestBuildClients:
    """Tests für MampokConfig.build_deployment_manager und build_s3_client."""

    def test_build_s3_client(self):
        cfg = MampokConfig.from_dict(MINIMAL_CONFIG)
        from mampok.s3.s3 import S3
        s3 = cfg.build_s3_client("my-bucket")
        assert isinstance(s3, S3)
        assert s3.bucket == "my-bucket"

    def test_build_deployment_manager(self):
        cfg = MampokConfig.from_dict(MINIMAL_CONFIG)
        from mampok.kubernetes.manager import DeploymentManager

        mock_api_client = MagicMock()
        with (
            patch("kubernetes.config.load_kube_config") as mock_load,
            patch("kubernetes.client.ApiClient", return_value=mock_api_client),
        ):
            manager = cfg.build_deployment_manager("BN")
            mock_load.assert_called_once_with(config_file="/app/BN_kube_config")
            assert isinstance(manager, DeploymentManager)

    def test_build_deployment_manager_unknown_cluster_raises(self):
        cfg = MampokConfig.from_dict(MINIMAL_CONFIG)
        with pytest.raises(KeyError):
            cfg.build_deployment_manager("NONEXISTENT")


# ---------------------------------------------------------------------------
# Gatekeeper — AuthProxyConfig
# ---------------------------------------------------------------------------

AUTH_PROXY_CLUSTER = {
    "host": "bioinformatics-cluster.example.com",
    "namespace": "mampok-bn",
    "kubeconfig_path": "/app/BN_kube_config",
    "auth_proxy": {
        "auth_proxy_image": "registry.example.com/gatekeeper:latest",
        "proxy_port": 9090,
        "auth_annotations": {"nginx.ingress.kubernetes.io/auth-type": "basic"},
        "image_pull_secrets": ["regcred"],
    },
}


def _config_with_cluster(cluster_dict: dict) -> dict:
    return {**MINIMAL_CONFIG, "cluster": {"BN": cluster_dict}}


class TestClusterConfigAuthProxy:
    """Tests für AuthProxyConfig-Parsing in MampokConfig.from_dict()."""

    def test_auth_proxy_parsed(self):
        cfg = MampokConfig.from_dict(_config_with_cluster(AUTH_PROXY_CLUSTER))
        ap = cfg.clusters["BN"].auth_proxy
        assert ap is not None
        assert ap.auth_proxy_image == "registry.example.com/gatekeeper:latest"
        assert ap.proxy_port == 9090
        assert ap.auth_annotations == {"nginx.ingress.kubernetes.io/auth-type": "basic"}
        assert ap.image_pull_secrets == ["regcred"]

    def test_auth_proxy_none_when_absent(self):
        cfg = MampokConfig.from_dict(MINIMAL_CONFIG)
        assert cfg.clusters["BN"].auth_proxy is None

    def test_auth_proxy_image_required(self):
        bad = {**AUTH_PROXY_CLUSTER, "auth_proxy": {"proxy_port": 9090}}
        with pytest.raises(jsonschema.ValidationError):
            MampokConfig.from_dict(_config_with_cluster(bad))

    def test_auth_proxy_port_default(self):
        minimal_ap = {**AUTH_PROXY_CLUSTER, "auth_proxy": {"auth_proxy_image": "gk:latest"}}
        cfg = MampokConfig.from_dict(_config_with_cluster(minimal_ap))
        assert cfg.clusters["BN"].auth_proxy.proxy_port == 8080

    def test_auth_proxy_annotations_default(self):
        minimal_ap = {**AUTH_PROXY_CLUSTER, "auth_proxy": {"auth_proxy_image": "gk:latest"}}
        cfg = MampokConfig.from_dict(_config_with_cluster(minimal_ap))
        assert cfg.clusters["BN"].auth_proxy.auth_annotations == {}

    def test_auth_proxy_pull_secrets_default(self):
        minimal_ap = {**AUTH_PROXY_CLUSTER, "auth_proxy": {"auth_proxy_image": "gk:latest"}}
        cfg = MampokConfig.from_dict(_config_with_cluster(minimal_ap))
        assert cfg.clusters["BN"].auth_proxy.image_pull_secrets == []

    def test_auth_proxy_unknown_field_raises(self):
        bad = {**AUTH_PROXY_CLUSTER, "auth_proxy": {**AUTH_PROXY_CLUSTER["auth_proxy"], "unknown_field": "x"}}
        with pytest.raises(jsonschema.ValidationError):
            MampokConfig.from_dict(_config_with_cluster(bad))

    def test_auth_proxy_is_authproxyconfig_instance(self):
        cfg = MampokConfig.from_dict(_config_with_cluster(AUTH_PROXY_CLUSTER))
        assert isinstance(cfg.clusters["BN"].auth_proxy, AuthProxyConfig)
