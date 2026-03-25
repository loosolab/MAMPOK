"""Tests für Mampok-Orchestrator."""

from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from mampok.kubernetes.config import DeploymentConfig
from mampok.mampok.mampok import Mampok, _generate_password, _transform_env


class TestMampokInit:
    """Tests für Mampok.__init__."""

    def test_stores_all_dependencies(self, mock_mamplan, mock_mamplate, mock_kube, mock_s3):
        mampok = Mampok(mock_mamplan, mock_mamplate, mock_kube, mock_s3)
        assert mampok.mamplan is mock_mamplan
        assert mampok.mamplate is mock_mamplate
        assert mampok.kube is mock_kube
        assert mampok.s3 is mock_s3


class TestBuildDeploymentConfig:
    """Tests für Mampok._build_deployment_config."""

    def test_maps_project_id_and_tool(self, mampok, mock_config):
        cfg = mampok._build_deployment_config(mock_config)
        assert cfg.project_id == "test-proj"
        assert cfg.tool == "cellxgene"

    def test_maps_image(self, mampok, mock_config):
        cfg = mampok._build_deployment_config(mock_config)
        assert cfg.image == "cellxgene:1.0"

    def test_maps_namespace_from_cluster(self, mampok, mock_config):
        cfg = mampok._build_deployment_config(mock_config)
        assert cfg.namespace == "mampok-bn"

    def test_maps_host_from_cluster(self, mampok, mock_config):
        cfg = mampok._build_deployment_config(mock_config)
        assert cfg.host == "bioinformatics-cluster.example.com"

    def test_maps_ingress_class_from_cluster(self, mampok, mock_config):
        cfg = mampok._build_deployment_config(mock_config)
        assert cfg.ingress_class == "nginx"

    def test_maps_tls_fields_from_cluster(self, mampok, mock_config):
        cfg = mampok._build_deployment_config(mock_config)
        assert cfg.tls_issuer == "letsencrypt-prod"
        assert cfg.tls_secret == "route53-creds"

    def test_maps_cpu_memory_limits(self, mampok, mock_config):
        cfg = mampok._build_deployment_config(mock_config)
        assert cfg.cpu == "2"
        assert cfg.memory == "4Gi"

    def test_request_cpu_memory_empty_when_absent(self, mampok, mock_config):
        cfg = mampok._build_deployment_config(mock_config)
        assert cfg.request_cpu == ""
        assert cfg.request_memory == ""

    def test_request_cpu_memory_mapped_when_present(self, mampok, mock_config):
        mampok.mamplan.merge_container_config.return_value = {
            "main": {
                "image": "cellxgene:1.0",
                "ports": 8080,
                "resources": {
                    "limits": {"cpu": "2", "memory": "4Gi"},
                    "requests": {"cpu": "1", "memory": "2Gi"},
                },
                "env": [],
                "args": [],
                "command": [],
            }
        }
        cfg = mampok._build_deployment_config(mock_config)
        assert cfg.request_cpu == "1"
        assert cfg.request_memory == "2Gi"

    def test_ports_int_wrapped_to_list(self, mampok, mock_config):
        cfg = mampok._build_deployment_config(mock_config)
        assert cfg.ports == [8080]

    def test_ports_none_becomes_empty_list(self, mampok, mock_config):
        mampok.mamplan.merge_container_config.return_value = {
            "main": {
                "image": "img:1",
                "resources": {"limits": {"cpu": "1", "memory": "1Gi"}, "requests": {}},
                "env": [], "args": [], "command": [],
            }
        }
        cfg = mampok._build_deployment_config(mock_config)
        assert cfg.ports == []

    def test_volume_creates_mounts_and_volumes(self, mampok, mock_config):
        mampok.mamplan.merge_container_config.return_value = {
            "main": {
                "image": "img:1",
                "ports": 8080,
                "resources": {"limits": {"cpu": "1", "memory": "1Gi"}, "requests": {}},
                "env": [], "args": [], "command": [],
                "volume": {"mountPath": "/data", "name": "data-volume"},
            }
        }
        cfg = mampok._build_deployment_config(mock_config)
        assert cfg.volume_mounts == [{"name": "data-volume", "mountPath": "/data"}]
        assert cfg.volumes == [{"name": "data-volume", "emptyDir": {}}]

    def test_no_volume_gives_empty_lists(self, mampok, mock_config):
        cfg = mampok._build_deployment_config(mock_config)
        assert cfg.volume_mounts == []
        assert cfg.volumes == []

    def test_init_container_mapped_when_present(self, mampok, mock_config):
        mampok.mamplan.merge_container_config.return_value = {
            "main": {
                "image": "img:1",
                "ports": 8080,
                "resources": {"limits": {"cpu": "1", "memory": "1Gi"}, "requests": {}},
                "env": [], "args": [], "command": [],
            },
            "init": {"image": "init:1", "containertype": "initcontainer"},
        }
        cfg = mampok._build_deployment_config(mock_config)
        assert cfg.init_container == {"image": "init:1", "containertype": "initcontainer"}

    def test_no_init_container_by_default(self, mampok, mock_config):
        cfg = mampok._build_deployment_config(mock_config)
        assert cfg.init_container is None

    def test_s3_secret_name_from_config(self, mampok, mock_config):
        cfg = mampok._build_deployment_config(mock_config)
        assert cfg.s3_secret_name == "mpis"

    def test_unknown_cluster_raises(self, mampok, mock_config):
        mampok.mamplan.data["deployment"]["cluster"] = "NONEXISTENT"
        with pytest.raises(KeyError):
            mampok._build_deployment_config(mock_config)


class TestTransformEnv:
    """Tests für _transform_env Hilfsfunktion."""

    def test_direct_env_var_passed_through(self):
        items = [{"name": "MY_VAR", "value": "hello"}]
        result = _transform_env(items, "proj-sc-tool", "mpis")
        assert result == [{"name": "MY_VAR", "value": "hello"}]

    def test_secret_env_var_secretname_0_uses_project_secret(self):
        items = [{"key": "MY_KEY", "name": "s3_key", "secretname": 0}]
        result = _transform_env(items, "test-proj-sc-cellxgene", "mpis")
        assert result == [
            {
                "name": "MY_KEY",
                "valueFrom": {"secretKeyRef": {"name": "test-proj-sc-cellxgene", "key": "s3_key"}},
            }
        ]

    def test_secret_env_var_secretname_1_uses_cluster_secret(self):
        items = [{"key": "CLUSTER_KEY", "name": "some_key", "secretname": 1}]
        result = _transform_env(items, "test-proj-sc-cellxgene", "mpis")
        assert result == [
            {
                "name": "CLUSTER_KEY",
                "valueFrom": {"secretKeyRef": {"name": "mpis", "key": "some_key"}},
            }
        ]

    def test_secret_env_var_custom_string_secretname(self):
        items = [{"key": "CUSTOM_KEY", "name": "key_ref", "secretname": "my-custom-secret"}]
        result = _transform_env(items, "proj-sc", "mpis")
        assert result[0]["valueFrom"]["secretKeyRef"]["name"] == "my-custom-secret"

    def test_empty_list_returns_empty(self):
        assert _transform_env([], "proj-sc", "mpis") == []

    def test_mixed_env_vars(self):
        items = [
            {"name": "DIRECT", "value": "val"},
            {"key": "FROM_SECRET", "name": "key", "secretname": 0},
        ]
        result = _transform_env(items, "proj-sc", "mpis")
        assert len(result) == 2
        assert result[0] == {"name": "DIRECT", "value": "val"}
        assert result[1]["name"] == "FROM_SECRET"


class TestIsExpired:
    """Tests für Mampok.is_expired Property."""

    def test_expired_active_returns_true(self, mampok):
        mampok.mamplan.data["deployment"]["status"] = True
        mampok.mamplan.data["deployment"]["lifetime"] = "2020-01-01T00:00:00+00:00"
        assert mampok.is_expired is True

    def test_not_expired_active_returns_false(self, mampok):
        mampok.mamplan.data["deployment"]["status"] = True
        mampok.mamplan.data["deployment"]["lifetime"] = "2099-12-31T00:00:00+00:00"
        assert mampok.is_expired is False

    def test_inactive_never_expired(self, mampok):
        mampok.mamplan.data["deployment"]["status"] = False
        mampok.mamplan.data["deployment"]["lifetime"] = "2020-01-01T00:00:00+00:00"
        assert mampok.is_expired is False

    def test_timezone_naive_lifetime_handled(self, mampok):
        mampok.mamplan.data["deployment"]["status"] = True
        mampok.mamplan.data["deployment"]["lifetime"] = "2020-01-01T00:00:00"
        assert mampok.is_expired is True


class TestDeploy:
    """Tests für Mampok.deploy."""

    def test_creates_bucket(self, mampok, mock_config, mock_s3):
        mampok.deploy(mock_config)
        mock_s3.create_bucket.assert_called_once()

    def test_skips_upload_when_compare_size_true(self, mampok, mock_config, mock_s3):
        mampok.mamplan.data["project"]["files"] = ["/data/file.h5"]
        mock_s3.compare_size.return_value = True
        mampok.deploy(mock_config)
        mock_s3.upload.assert_not_called()

    def test_uploads_when_compare_size_false(self, mampok, mock_config, mock_s3):
        mampok.mamplan.data["project"]["files"] = ["/data/file.h5"]
        mock_s3.compare_size.return_value = False
        mampok.deploy(mock_config)
        mock_s3.upload.assert_called_once_with(Path("/data/file.h5"), "file.h5")

    def test_uploads_multiple_files(self, mampok, mock_config, mock_s3):
        mampok.mamplan.data["project"]["files"] = ["/data/a.h5", "/data/b.csv"]
        mock_s3.compare_size.return_value = False
        mampok.deploy(mock_config)
        assert mock_s3.upload.call_count == 2

    def test_no_upload_when_no_files(self, mampok, mock_config, mock_s3):
        mampok.mamplan.data["project"]["files"] = []
        mampok.deploy(mock_config)
        mock_s3.upload.assert_not_called()

    def test_calls_kube_deploy_with_correct_credentials(self, mampok, mock_config, mock_kube):
        mampok.deploy(mock_config)
        mock_kube.deploy.assert_called_once()
        _, s3_creds = mock_kube.deploy.call_args[0]
        assert s3_creds["s3_endpoint"] == "https://s3.example.com"
        assert s3_creds["s3_key"] == "mampok-service"
        assert s3_creds["s3_secret"] == "secret123"

    def test_calls_wait_for_ready(self, mampok, mock_config, mock_kube):
        mampok.deploy(mock_config, timeout=120)
        mock_kube.wait_for_ready.assert_called_once()
        _, kwargs = mock_kube.wait_for_ready.call_args
        assert kwargs.get("timeout", mock_kube.wait_for_ready.call_args[0][1] if len(mock_kube.wait_for_ready.call_args[0]) > 1 else None) in (120, None)

    def test_updates_mamplan_status_true(self, mampok, mock_config):
        mampok.deploy(mock_config)
        mampok.mamplan.edit.assert_called_once()
        kwargs = mampok.mamplan.edit.call_args[1]
        assert kwargs["deployment__status"] is True

    def test_s3_files_string_in_credentials(self, mampok, mock_config, mock_kube, mock_s3):
        mampok.mamplan.data["project"]["files"] = ["/data/a.h5", "/data/b.csv"]
        mock_s3.compare_size.return_value = False
        mampok.deploy(mock_config)
        _, s3_creds = mock_kube.deploy.call_args[0]
        assert s3_creds["s3_files"] == "a.h5,b.csv"


class TestStop:
    """Tests für Mampok.stop."""

    def test_calls_kube_delete(self, mampok, mock_config, mock_kube):
        mampok.stop(mock_config)
        mock_kube.delete.assert_called_once()

    def test_updates_mamplan_status_false(self, mampok, mock_config):
        mampok.stop(mock_config)
        mampok.mamplan.edit.assert_called_once()
        kwargs = mampok.mamplan.edit.call_args[1]
        assert kwargs["deployment__status"] is False

    def test_does_not_touch_s3(self, mampok, mock_config, mock_s3):
        mampok.stop(mock_config)
        mock_s3.delete_bucket.assert_not_called()
        mock_s3.upload.assert_not_called()
        mock_s3.create_bucket.assert_not_called()


class TestCheckStatus:
    """Tests für Mampok.check_status."""

    def test_healthy_when_both_active(self, mampok, mock_config, mock_kube):
        mampok.mamplan.data["deployment"]["status"] = True
        mock_kube.deployment_exists.return_value = True
        result = mampok.check_status(mock_config)
        assert result["expected_active"] is True
        assert result["actually_deployed"] is True
        assert result["healthy"] is True

    def test_healthy_when_both_inactive(self, mampok, mock_config, mock_kube):
        mampok.mamplan.data["deployment"]["status"] = False
        mock_kube.deployment_exists.return_value = False
        result = mampok.check_status(mock_config)
        assert result["healthy"] is True

    def test_unhealthy_mamplan_active_kube_missing(self, mampok, mock_config, mock_kube):
        mampok.mamplan.data["deployment"]["status"] = True
        mock_kube.deployment_exists.return_value = False
        result = mampok.check_status(mock_config)
        assert result["expected_active"] is True
        assert result["actually_deployed"] is False
        assert result["healthy"] is False

    def test_unhealthy_kube_active_mamplan_inactive(self, mampok, mock_config, mock_kube):
        mampok.mamplan.data["deployment"]["status"] = False
        mock_kube.deployment_exists.return_value = True
        result = mampok.check_status(mock_config)
        assert result["healthy"] is False

    def test_returns_correct_project_id(self, mampok, mock_config):
        result = mampok.check_status(mock_config)
        assert result["project_id"] == "test-proj"


class TestUpdateAuthSecret:
    """Tests für Mampok.update_auth_secret."""

    def test_generates_htpasswd_for_users(self, mampok, mock_config, mock_kube):
        mampok.update_auth_secret(["alice", "bob"], mock_config)
        mock_kube._kube.apply.assert_called_once()
        manifest = mock_kube._kube.apply.call_args[0][0]
        import base64
        htpasswd = base64.b64decode(manifest["data"]["auth"]).decode()
        assert "alice:" in htpasswd
        assert "bob:" in htpasswd

    def test_htpasswd_uses_bcrypt_format(self, mampok, mock_config, mock_kube):
        mampok.update_auth_secret(["alice"], mock_config)
        manifest = mock_kube._kube.apply.call_args[0][0]
        import base64
        htpasswd = base64.b64decode(manifest["data"]["auth"]).decode()
        # bcrypt hashes start with $2b$
        assert "$2b$" in htpasswd

    def test_public_user_single_entry(self, mampok, mock_config, mock_kube):
        mampok.update_auth_secret(["public"], mock_config)
        manifest = mock_kube._kube.apply.call_args[0][0]
        import base64
        htpasswd = base64.b64decode(manifest["data"]["auth"]).decode()
        lines = [l for l in htpasswd.strip().splitlines() if l]
        assert len(lines) == 1
        assert lines[0].startswith("public:")

    def test_applies_auth_secret_manifest(self, mampok, mock_config, mock_kube):
        mampok.update_auth_secret(["alice"], mock_config)
        manifest = mock_kube._kube.apply.call_args[0][0]
        assert manifest["kind"] == "Secret"
        assert manifest["type"] == "kubernetes.io/basic-auth"

    def test_secret_name_uses_project_and_tool(self, mampok, mock_config, mock_kube):
        mampok.update_auth_secret(["alice"], mock_config)
        manifest = mock_kube._kube.apply.call_args[0][0]
        assert manifest["metadata"]["name"] == "test-proj-sc-cellxgene-auth"


class TestGeneratePassword:
    """Tests für _generate_password Hilfsfunktion."""

    def test_default_length_is_16(self):
        pw = _generate_password()
        assert len(pw) == 16

    def test_custom_length(self):
        pw = _generate_password(32)
        assert len(pw) == 32

    def test_alphanumeric_only(self):
        import string
        allowed = set(string.ascii_letters + string.digits)
        pw = _generate_password(100)
        assert all(c in allowed for c in pw)

    def test_passwords_are_unique(self):
        passwords = {_generate_password() for _ in range(20)}
        assert len(passwords) > 1


# ---------------------------------------------------------------------------
# Gatekeeper — _build_deployment_config auth-Felder
# ---------------------------------------------------------------------------


class TestBuildDeploymentConfigAuthProxy:
    """Tests für auth_proxy-Verdrahtung in _build_deployment_config."""

    def test_auth_proxy_image_mapped(self, mampok, mock_config_with_auth):
        cfg = mampok._build_deployment_config(mock_config_with_auth)
        assert cfg.auth_proxy_image == "registry.example.com/gatekeeper:latest"

    def test_auth_proxy_port_mapped(self, mampok, mock_config_with_auth):
        cfg = mampok._build_deployment_config(mock_config_with_auth)
        assert cfg.proxy_port == 9090

    def test_auth_annotations_mapped(self, mampok, mock_config_with_auth):
        cfg = mampok._build_deployment_config(mock_config_with_auth)
        assert cfg.auth_annotations == {"nginx.ingress.kubernetes.io/auth-type": "basic"}

    def test_image_pull_secrets_mapped(self, mampok, mock_config_with_auth):
        cfg = mampok._build_deployment_config(mock_config_with_auth)
        assert cfg.image_pull_secrets == ["regcred"]

    def test_proxy_fields_empty_when_no_auth_proxy(self, mampok, mock_config):
        cfg = mampok._build_deployment_config(mock_config)
        assert cfg.auth_proxy_image == ""
        assert cfg.proxy_port == 8080
        assert cfg.auth_annotations == {}
        assert cfg.image_pull_secrets == []
