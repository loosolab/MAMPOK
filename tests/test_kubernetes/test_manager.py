"""Tests für DeploymentManager."""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

from mampok.kubernetes.manager import DeploymentManager


class TestDeploymentManagerInit:
    """Tests for DeploymentManager initialization."""

    def test_init(self):
        kube = MagicMock()
        mgr = DeploymentManager(kube)
        assert mgr._kube is kube
        assert mgr._builder is not None


class TestDeploy:
    """Tests for DeploymentManager.deploy."""

    def test_deploy_applies_all_manifests(self, make_config, sample_s3_credentials):
        kube = MagicMock()
        mgr = DeploymentManager(kube)

        cfg = make_config(ports=[8080], url="https://example.com", host="example.com")
        list(mgr.deploy(cfg, sample_s3_credentials))

        assert kube.apply.call_count == 4
        kinds = [c.args[0]["kind"] for c in kube.apply.call_args_list]
        assert kinds == ["Secret", "Deployment", "Service", "Ingress"]

    def test_deploy_fail_fast(self, make_config, sample_s3_credentials):
        kube = MagicMock()
        kube.apply.side_effect = [None, Exception("API error")]
        mgr = DeploymentManager(kube)

        cfg = make_config(ports=[8080])
        with pytest.raises(Exception, match="API error"):
            list(mgr.deploy(cfg, sample_s3_credentials))

        # Secret applied, Deployment failed — 2 calls total
        assert kube.apply.call_count == 2


class TestDelete:
    """Tests for DeploymentManager.delete."""

    def test_delete_all_resources(self, make_config):
        kube = MagicMock()
        mgr = DeploymentManager(kube)
        cfg = make_config()

        list(mgr.delete(cfg))

        assert kube.delete.call_count == 5
        calls = kube.delete.call_args_list
        assert calls[0] == call("Deployment", cfg.deployment_name)
        assert calls[1] == call("Service", cfg.service_name)
        assert calls[2] == call("Ingress", cfg.ingress_name)
        assert calls[3] == call("Secret", cfg.secret_name)
        assert calls[4] == call("Secret", cfg.auth_secret_name)

    def test_all_resources_attempted_even_when_first_fails(self, make_config):
        """All 5 K8s resources are attempted even if the first delete raises."""
        kube = MagicMock()
        kube.delete.side_effect = [RuntimeError("K8s error"), None, None, None, None]
        mgr = DeploymentManager(kube)
        cfg = make_config()

        with pytest.raises(RuntimeError):
            list(mgr.delete(cfg))

        assert kube.delete.call_count == 5

    def test_raises_runtime_error_listing_failures(self, make_config):
        """RuntimeError message includes failure count and resource details."""
        kube = MagicMock()
        kube.delete.side_effect = [None, RuntimeError("svc gone"), None, RuntimeError("sec gone"), None]
        mgr = DeploymentManager(kube)
        cfg = make_config()

        with pytest.raises(RuntimeError, match="2 resource"):
            list(mgr.delete(cfg))

    def test_no_raise_when_all_succeed(self, make_config):
        """No exception when all deletes succeed."""
        kube = MagicMock()
        mgr = DeploymentManager(kube)
        cfg = make_config()

        mgr.delete(cfg)  # must not raise


class TestRedeploy:
    """Tests for DeploymentManager.redeploy."""

    def test_delete_before_deploy(self, make_config, sample_s3_credentials):
        kube = MagicMock()
        mgr = DeploymentManager(kube)
        cfg = make_config(ports=[8080])

        call_order = []
        kube.delete.side_effect = lambda *a: call_order.append("delete")
        kube.apply.side_effect = lambda *a: call_order.append("apply")

        list(mgr.redeploy(cfg, sample_s3_credentials))

        # All deletes should come before any apply
        delete_indices = [i for i, v in enumerate(call_order) if v == "delete"]
        apply_indices = [i for i, v in enumerate(call_order) if v == "apply"]
        assert max(delete_indices) < min(apply_indices)


class TestRolloutStatus:
    """Tests for DeploymentManager.rollout_status."""

    def test_returns_status_dict(self, make_config):
        kube = MagicMock()
        kube.get.return_value = {
            "status": {
                "ready_replicas": 2,
                "available_replicas": 2,
                "updated_replicas": 2,
                "conditions": [{"type": "Available", "status": "True"}],
            }
        }
        mgr = DeploymentManager(kube)
        cfg = make_config()

        status = mgr.rollout_status(cfg)

        assert status["ready_replicas"] == 2
        assert status["available_replicas"] == 2
        assert status["updated_replicas"] == 2
        assert len(status["conditions"]) == 1
        kube.get.assert_called_once_with("Deployment", cfg.deployment_name)

    def test_handles_missing_status(self, make_config):
        kube = MagicMock()
        kube.get.return_value = {}
        mgr = DeploymentManager(kube)

        status = mgr.rollout_status(make_config())

        assert status["ready_replicas"] is None
        assert status["conditions"] == []


class TestPatchDeployment:
    """Tests for DeploymentManager.patch_deployment."""

    def test_delegates_to_kube_patch(self, make_config):
        kube = MagicMock()
        kube.patch.return_value = {"kind": "Deployment"}
        mgr = DeploymentManager(kube)
        cfg = make_config()

        patch_body = {"spec": {"template": {"spec": {"containers": [{"image": "new:v2"}]}}}}
        result = mgr.patch_deployment(cfg, patch_body)

        kube.patch.assert_called_once_with("Deployment", cfg.deployment_name, patch_body)
        assert result == {"kind": "Deployment"}


class TestRolloutRestart:
    """Tests for DeploymentManager.rollout_restart."""

    def test_sets_restart_annotation(self, make_config):
        kube = MagicMock()
        kube.patch.return_value = {"kind": "Deployment"}
        mgr = DeploymentManager(kube)
        cfg = make_config()

        mgr.rollout_restart(cfg)

        call_args = kube.patch.call_args
        assert call_args.args[0] == "Deployment"
        assert call_args.args[1] == cfg.deployment_name
        patch_body = call_args.args[2]
        annotation = patch_body["spec"]["template"]["metadata"]["annotations"]
        assert "mampok/restartedAt" in annotation

    def test_delegates_to_patch_deployment(self, make_config):
        kube = MagicMock()
        kube.patch.return_value = {"kind": "Deployment"}
        mgr = DeploymentManager(kube)
        cfg = make_config()

        with patch.object(mgr, "patch_deployment", wraps=mgr.patch_deployment) as mock_pd:
            mgr.rollout_restart(cfg)
            mock_pd.assert_called_once()


class TestDeploymentExists:
    """Tests für DeploymentManager.deployment_exists."""

    def test_returns_true_when_deployment_exists(self, make_config):
        kube = MagicMock()
        kube.exists.return_value = True
        mgr = DeploymentManager(kube)
        cfg = make_config()

        assert mgr.deployment_exists(cfg) is True
        kube.exists.assert_called_once_with("Deployment", cfg.deployment_name)

    def test_returns_false_when_deployment_missing(self, make_config):
        kube = MagicMock()
        kube.exists.return_value = False
        mgr = DeploymentManager(kube)
        cfg = make_config()

        assert mgr.deployment_exists(cfg) is False


class TestWaitForReady:
    """Tests für DeploymentManager.wait_for_ready."""

    def _make_event(self, ready_replicas, replicas=1):
        obj = MagicMock()
        obj.status.ready_replicas = ready_replicas
        return {"object": obj}

    def test_returns_when_replicas_ready(self, make_config):
        kube = MagicMock()
        mgr = DeploymentManager(kube)
        cfg = make_config(replicas=1)

        mock_watch = MagicMock()
        mock_watch.stream.return_value = iter([self._make_event(ready_replicas=1)])

        with patch("kubernetes.watch.Watch", return_value=mock_watch):
            list(mgr.wait_for_ready(cfg, timeout=30))

        mock_watch.stream.assert_called_once()

    def test_raises_timeout_when_stream_exhausted(self, make_config):
        kube = MagicMock()
        mgr = DeploymentManager(kube)
        cfg = make_config(replicas=2)

        mock_watch = MagicMock()
        mock_watch.stream.return_value = iter([])  # stream exhausted without ready

        with patch("kubernetes.watch.Watch", return_value=mock_watch):
            with pytest.raises(TimeoutError, match="not ready"):
                list(mgr.wait_for_ready(cfg, timeout=5))

    def test_waits_through_partial_ready(self, make_config):
        kube = MagicMock()
        mgr = DeploymentManager(kube)
        cfg = make_config(replicas=2)

        events = [
            self._make_event(ready_replicas=0),
            self._make_event(ready_replicas=1),
            self._make_event(ready_replicas=2),
        ]
        mock_watch = MagicMock()
        mock_watch.stream.return_value = iter(events)

        with patch("kubernetes.watch.Watch", return_value=mock_watch):
            list(mgr.wait_for_ready(cfg, timeout=30))

        mock_watch.stream.assert_called()

    def test_handles_none_ready_replicas(self, make_config):
        kube = MagicMock()
        mgr = DeploymentManager(kube)
        cfg = make_config(replicas=1)

        events = [
            self._make_event(ready_replicas=None),
            self._make_event(ready_replicas=1),
        ]
        mock_watch = MagicMock()
        mock_watch.stream.return_value = iter(events)

        with patch("kubernetes.watch.Watch", return_value=mock_watch):
            list(mgr.wait_for_ready(cfg, timeout=30))

        mock_watch.stream.assert_called()

    def test_passes_timeout_to_stream(self, make_config):
        kube = MagicMock()
        mgr = DeploymentManager(kube)
        cfg = make_config(replicas=1)

        mock_watch = MagicMock()
        mock_watch.stream.return_value = iter([self._make_event(ready_replicas=1)])

        with patch("kubernetes.watch.Watch", return_value=mock_watch):
            list(mgr.wait_for_ready(cfg, timeout=120))

        call_kwargs = mock_watch.stream.call_args[1]
        # wait_for_ready uses a poll loop with short intervals; timeout_seconds
        # is at most the full timeout but may be smaller (poll interval cap)
        assert "timeout_seconds" in call_kwargs
        assert 0 < call_kwargs["timeout_seconds"] <= 120


# ---------------------------------------------------------------------------
# TestFinalSyncBeforeDelete
# ---------------------------------------------------------------------------


class TestFinalSyncBeforeDelete:
    """Tests for the pre-delete S3 sync in DeploymentManager.delete()."""

    def test_delete_yields_sync_and_delete_events(self, make_config):
        """When container_data_paths is set, delete() yields s3_final_sync + k8s_delete events."""
        kube = MagicMock()
        kube.list_running_pods.return_value = ["mypod-abc123"]
        kube.exec_in_pod_stream.return_value = []
        cfg = make_config(
            container_data_paths=["/app/annotations/"],
            bucket="b",
            endpoint="https://s3.example.com",
        )

        events = list(DeploymentManager(kube).delete(cfg))

        stages = [e["stage"] for e in events]
        assert "s3_final_sync" in stages
        assert "k8s_delete" in stages

        sync_done = next(e for e in events if e["stage"] == "s3_final_sync" and e["status"] == "done")
        assert sync_done["pod"] == "mypod-abc123"

        assert "rclone copy" in " ".join(kube.exec_in_pod_stream.call_args.kwargs["command"])
        assert kube.exec_in_pod_stream.call_args.kwargs["container"] == "mampok-s3-sync"

    def test_delete_skips_sync_without_container_data(self, make_config):
        """delete() must NOT exec when container_data_paths is empty."""
        kube = MagicMock()
        events = list(DeploymentManager(kube).delete(make_config()))

        kube.exec_in_pod_stream.assert_not_called()
        kube.list_running_pods.assert_not_called()
        assert all(e["stage"] == "k8s_delete" for e in events)

    def test_delete_yields_skipped_when_no_running_pod(self, make_config):
        """delete() yields s3_final_sync/skipped and still deletes K8s resources."""
        kube = MagicMock()
        kube.list_running_pods.return_value = []
        cfg = make_config(
            container_data_paths=["/app/annotations/"],
            bucket="b",
            endpoint="https://s3.example.com",
        )

        events = list(DeploymentManager(kube).delete(cfg))

        skipped = next(e for e in events if e["stage"] == "s3_final_sync")
        assert skipped["status"] == "skipped"
        assert skipped["reason"] == "no_running_pod"
        kube.exec_in_pod_stream.assert_not_called()
        kube.delete.assert_called()

    def test_delete_yields_failed_on_exec_error(self, make_config):
        """delete() yields s3_final_sync/failed and still deletes K8s resources."""
        kube = MagicMock()
        kube.list_running_pods.return_value = ["mypod"]
        kube.exec_in_pod_stream.side_effect = Exception("connection timeout")
        cfg = make_config(
            container_data_paths=["/app/annotations/"],
            bucket="b",
            endpoint="https://s3.example.com",
        )

        events = list(DeploymentManager(kube).delete(cfg))

        failed = next(e for e in events if e["stage"] == "s3_final_sync" and e["status"] == "failed")
        assert "connection timeout" in failed["reason"]
        kube.delete.assert_called()

    def test_delete_uses_sync_timeout_from_config(self, make_config):
        """exec_in_pod_stream timeout must come from container_data_sync_timeout, not grace period."""
        kube = MagicMock()
        kube.list_running_pods.return_value = ["mypod"]
        kube.exec_in_pod_stream.return_value = []
        cfg = make_config(
            container_data_paths=["/app/annotations/"],
            bucket="b",
            endpoint="https://s3.example.com",
            container_data_sync_timeout=120,
        )

        list(DeploymentManager(kube).delete(cfg))

        assert kube.exec_in_pod_stream.call_args.kwargs["timeout"] == 120
