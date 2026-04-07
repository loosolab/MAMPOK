"""Tests für Mampok-Orchestrator."""

from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from mampok.kubernetes.config import DeploymentConfig
from mampok.mampok.mampok import Mampok


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
            "init": [{"image": "init:1"}],
        }
        cfg = mampok._build_deployment_config(mock_config)
        assert cfg.init_containers == [{"image": "init:1"}]

    def test_no_init_container_by_default(self, mampok, mock_config):
        cfg = mampok._build_deployment_config(mock_config)
        assert cfg.init_containers == []

    def test_s3_secret_name_from_config(self, mampok, mock_config):
        cfg = mampok._build_deployment_config(mock_config)
        assert cfg.s3_secret_name == "mpis"

    def test_unknown_cluster_raises(self, mampok, mock_config):
        mampok.mamplan.data["deployment"]["cluster"] = "NONEXISTENT"
        with pytest.raises(KeyError):
            mampok._build_deployment_config(mock_config)

    def test_generates_url_when_generate_url_true(self, mampok, mock_config):
        # generate_url=True, url="" → URL auto-generated from host/project_id/tool
        mampok.mamplan.data["deployment"]["url"] = ""
        mampok.mamplan.data["deployment"]["generate_url"] = True
        cfg = mampok._build_deployment_config(mock_config)
        assert cfg.url == "https://bioinformatics-cluster.example.com/mampok-bn/test-proj/cellxgene/"

    def test_no_url_generated_when_url_already_set(self, mampok, mock_config):
        # url already set → keep as-is, ignore generate_url
        mampok.mamplan.data["deployment"]["url"] = "https://custom.example.com/my/path"
        mampok.mamplan.data["deployment"]["generate_url"] = True
        cfg = mampok._build_deployment_config(mock_config)
        assert cfg.url == "https://custom.example.com/my/path"

    def test_no_url_generated_when_generate_url_false(self, mampok, mock_config):
        mampok.mamplan.data["deployment"]["url"] = ""
        mampok.mamplan.data["deployment"]["generate_url"] = False
        cfg = mampok._build_deployment_config(mock_config)
        assert cfg.url == ""

    def test_no_url_generated_when_host_empty(self, mampok, mock_config):
        from mampok.config.config import ClusterConfig, S3Config, MampokConfig
        cluster_no_host = ClusterConfig(
            host="",
            namespace="mampok-bn",
            kubeconfig_path="/app/BN_kube_config",
        )
        config_no_host = MampokConfig(
            clusters={"BN": cluster_no_host},
            s3=mock_config.s3,
            mamplan_repo=mock_config.mamplan_repo,
            mamplates_path=mock_config.mamplates_path,
            lifetime_days=10,
        )
        mampok.mamplan.data["deployment"]["url"] = ""
        mampok.mamplan.data["deployment"]["generate_url"] = True
        cfg = mampok._build_deployment_config(config_no_host)
        assert cfg.url == ""

    def test_random_url_suffix_appended(self, mampok, mock_config):
        mampok.mamplan.data["deployment"]["url"] = ""
        mampok.mamplan.data["deployment"]["generate_url"] = True
        mampok.mamplan.data["deployment"]["random_url_suffix"] = True
        cfg = mampok._build_deployment_config(mock_config)
        base = "https://bioinformatics-cluster.example.com/mampok-bn/test-proj/cellxgene-"
        assert cfg.url.startswith(base)
        assert cfg.url.endswith("/")
        suffix = cfg.url[len(base):].rstrip("/")
        assert len(suffix) == 5
        assert suffix.isalnum()




class TestIsExpired:
    """Tests dass Mampok.is_expired an mamplan.is_expired delegiert."""

    def test_delegates_true(self, mampok):
        mampok.mamplan.is_expired = True
        assert mampok.is_expired is True

    def test_delegates_false(self, mampok):
        mampok.mamplan.is_expired = False
        assert mampok.is_expired is False


class TestDeploy:
    """Tests für Mampok.deploy (Generator)."""

    def test_creates_bucket(self, mampok, mock_config, mock_s3):
        list(mampok.deploy(mock_config))
        mock_s3.create_bucket.assert_called_once()

    def test_skips_upload_when_compare_size_true(self, mampok, mock_config, mock_s3):
        mampok.mamplan.data["project"]["files"] = ["/data/file.h5"]
        mock_s3.compare_size.return_value = True
        list(mampok.deploy(mock_config))
        mock_s3.upload.assert_not_called()

    def test_uploads_when_compare_size_false(self, mampok, mock_config, mock_s3):
        mampok.mamplan.data["project"]["files"] = ["/data/file.h5"]
        mock_s3.compare_size.return_value = False
        list(mampok.deploy(mock_config))
        mock_s3.upload.assert_called_once_with(Path("/data/file.h5"), "file.h5")

    def test_uploads_multiple_files(self, mampok, mock_config, mock_s3):
        mampok.mamplan.data["project"]["files"] = ["/data/a.h5", "/data/b.csv"]
        mock_s3.compare_size.return_value = False
        list(mampok.deploy(mock_config))
        assert mock_s3.upload.call_count == 2

    def test_no_upload_when_no_files(self, mampok, mock_config, mock_s3):
        mampok.mamplan.data["project"]["files"] = []
        list(mampok.deploy(mock_config))
        mock_s3.upload.assert_not_called()

    def test_calls_kube_deploy_with_correct_credentials(self, mampok, mock_config, mock_kube):
        list(mampok.deploy(mock_config))
        mock_kube.deploy.assert_called_once()
        _, s3_creds = mock_kube.deploy.call_args[0]
        assert s3_creds["s3_key"] == "mampok-service"
        assert s3_creds["s3_secret"] == "secret123"
        assert "s3_endpoint" not in s3_creds
        assert "s3_files" not in s3_creds

    def test_calls_wait_for_ready(self, mampok, mock_config, mock_kube):
        list(mampok.deploy(mock_config, timeout=120))
        mock_kube.wait_for_ready.assert_called_once()
        call_args = mock_kube.wait_for_ready.call_args
        timeout = call_args.kwargs.get("timeout") or (call_args.args[1] if len(call_args.args) > 1 else None)
        assert timeout == 120

    def test_updates_mamplan_status_true(self, mampok, mock_config):
        list(mampok.deploy(mock_config))
        mampok.mamplan.edit.assert_called_once()
        kwargs = mampok.mamplan.edit.call_args[1]
        assert kwargs["deployment__status"] is True

    def test_no_s3_files_in_credentials(self, mampok, mock_config, mock_kube, mock_s3):
        mampok.mamplan.data["project"]["files"] = ["/data/a.h5", "/data/b.csv"]
        mock_s3.compare_size.return_value = False
        list(mampok.deploy(mock_config))
        _, s3_creds = mock_kube.deploy.call_args[0]
        assert "s3_files" not in s3_creds

    def test_yields_init_stage(self, mampok, mock_config):
        events = list(mampok.deploy(mock_config))
        init_event = next(e for e in events if e.get("stage") == "init")
        assert init_event["status"] == "done"
        assert init_event["project_id"] == "test-proj"

    def test_yields_done_stage_with_selfservice(self, mampok, mock_config):
        events = list(mampok.deploy(mock_config))
        done_event = next(e for e in events if e.get("stage") == "done")
        assert "selfservice" in done_event
        assert "project_id" in done_event["selfservice"]

    def test_yields_s3_bucket_stage(self, mampok, mock_config):
        events = list(mampok.deploy(mock_config))
        s3_bucket = next(e for e in events if e.get("stage") == "s3_bucket")
        assert s3_bucket["status"] in ("created", "exists")

    def test_yields_s3_upload_per_file(self, mampok, mock_config, mock_s3):
        mampok.mamplan.data["project"]["files"] = ["/data/a.h5", "/data/b.csv"]
        mock_s3.compare_size.return_value = False
        events = list(mampok.deploy(mock_config))
        upload_events = [e for e in events if e.get("stage") == "s3_upload" and "file" in e]
        assert len(upload_events) == 2

    def test_deploy_resets_lifetime_from_config(self, mampok, mock_config):
        """Deploy sets deployment.lifetime = now + config.lifetime_days."""
        from datetime import datetime, timezone, timedelta
        before = datetime.now(timezone.utc)
        list(mampok.deploy(mock_config))
        kwargs = mampok.mamplan.edit.call_args[1]
        assert "deployment__lifetime" in kwargs
        new_lifetime = datetime.fromisoformat(kwargs["deployment__lifetime"].replace("Z", "+00:00"))
        expected = before + timedelta(days=mock_config.lifetime_days)
        assert new_lifetime >= before
        assert abs((new_lifetime - expected).total_seconds()) < 5


class TestDeployCleanup:
    """Tests für automatisches K8s-Cleanup bei fehlgeschlagenem Deploy."""

    def test_cleanup_on_timeout_calls_kube_delete(self, mampok, mock_config, mock_kube):
        """Bei TimeoutError in wait_for_ready wird kube.delete() aufgerufen."""
        mock_kube.deploy.return_value = iter([{"stage": "k8s_validate", "status": "done", "count": 1}])
        mock_kube.wait_for_ready.side_effect = TimeoutError("not ready")
        with pytest.raises(TimeoutError):
            list(mampok.deploy(mock_config, cleanup=True))
        mock_kube.delete.assert_called_once()

    def test_cleanup_on_timeout_yields_cleanup_event(self, mampok, mock_config, mock_kube):
        """Bei TimeoutError wird ein k8s_cleanup-Event geliefert."""
        mock_kube.deploy.return_value = iter([{"stage": "k8s_validate", "status": "done", "count": 1}])
        mock_kube.wait_for_ready.side_effect = TimeoutError("not ready")
        events = []
        with pytest.raises(TimeoutError):
            for event in mampok.deploy(mock_config, cleanup=True):
                events.append(event)
        cleanup_events = [e for e in events if e.get("stage") == "k8s_cleanup"]
        assert len(cleanup_events) == 1
        assert cleanup_events[0]["status"] == "done"
        assert cleanup_events[0]["project_id"] == "test-proj"

    def test_cleanup_on_k8s_apply_error(self, mampok, mock_config, mock_kube):
        """Bei Fehler nach erstem k8s_apply-Event wird cleanup ausgeführt."""
        # Erster yield (k8s_validate) geht durch, dann Fehler
        def deploy_with_error(cfg, creds):
            yield {"stage": "k8s_validate", "status": "done", "count": 1}
            raise RuntimeError("apply failed")
        mock_kube.deploy.side_effect = deploy_with_error
        with pytest.raises(RuntimeError):
            list(mampok.deploy(mock_config, cleanup=True))
        mock_kube.delete.assert_called_once()

    def test_no_cleanup_flag_skips_delete_on_timeout(self, mampok, mock_config, mock_kube):
        """Mit cleanup=False wird kube.delete() bei Timeout nicht aufgerufen."""
        mock_kube.wait_for_ready.side_effect = TimeoutError("not ready")
        with pytest.raises(TimeoutError):
            list(mampok.deploy(mock_config, cleanup=False))
        mock_kube.delete.assert_not_called()

    def test_no_cleanup_on_s3_error(self, mampok, mock_config, mock_kube, mock_s3):
        """Bei Fehler vor K8s-Start (S3-Phase) wird kein Cleanup ausgeführt."""
        mock_s3.create_bucket.side_effect = RuntimeError("s3 error")
        with pytest.raises(RuntimeError):
            list(mampok.deploy(mock_config, cleanup=True))
        mock_kube.delete.assert_not_called()

    def test_mamplan_not_updated_after_cleanup(self, mampok, mock_config, mock_kube):
        """Nach Cleanup bleibt der Mamplan-Status auf False."""
        mock_kube.wait_for_ready.side_effect = TimeoutError("not ready")
        with pytest.raises(TimeoutError):
            list(mampok.deploy(mock_config, cleanup=True))
        mampok.mamplan.edit.assert_not_called()


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


class TestStopTransactional:
    """Tests für transaktionales Verhalten von Mampok.stop (Feature I)."""

    def test_mamplan_not_updated_when_delete_fails(self, mampok, mock_config, mock_kube):
        """Mamplan status must stay True when K8s delete raises."""
        mock_kube.delete.side_effect = RuntimeError("K8s unreachable")

        with pytest.raises(RuntimeError, match="K8s unreachable"):
            mampok.stop(mock_config)

        mampok.mamplan.edit.assert_not_called()

    def test_mamplan_updated_when_delete_succeeds(self, mampok, mock_config):
        """Mamplan status is updated to False when K8s delete succeeds."""
        mampok.stop(mock_config)
        kwargs = mampok.mamplan.edit.call_args[1]
        assert kwargs["deployment__status"] is False

    def test_exception_re_raised(self, mampok, mock_config, mock_kube):
        """The K8s exception propagates to the caller."""
        mock_kube.delete.side_effect = RuntimeError("network failure")

        with pytest.raises(RuntimeError):
            mampok.stop(mock_config)


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
