"""DeploymentManager — Schicht 3: Orchestrierung von KubeClient und ManifestBuilder."""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone
from typing import Iterator

from mampok.kubernetes.builder import ManifestBuilder, _S3SYNC_SIDECAR_NAME
from mampok.kubernetes.client import KubeClient
from mampok.kubernetes.config import DeploymentConfig
from mampok.kubernetes.validator import ManifestValidationError, ManifestValidator

logger = logging.getLogger(__name__)


def _parse_rclone_stats(output: str) -> dict:
    """Extract transfer progress, speed, and elapsed time from rclone --stats output.

    Handles the two "Transferred:" lines rclone emits:
      - Bytes line: "Transferred:   512.0 MiB / 1.024 GiB, 50%, 51.2 MiB/s, ETA 10s"
      - File count: "Transferred:         50 / 100, 50%"  (plain integers, no unit)

    Returns:
        Dict with a subset of: transferred_files, total_files, transferred_pct,
        transferred_bytes_human, total_bytes_human, speed, elapsed.
        Empty dict when no stats are found in output.
    """
    result: dict = {}
    # File-count line has plain integers followed by "%" with no unit after numbers.
    # The bytes line has a float + unit (e.g. "512.0 MiB") before the slash.
    m = re.search(r"Transferred:\s+(\d+)\s*/\s*(\d+),\s*(\d+)%\s*(?:\n|$)", output)
    if m:
        result["transferred_files"] = int(m.group(1))
        result["total_files"] = int(m.group(2))
        result["transferred_pct"] = int(m.group(3))
    # Bytes + speed line
    m = re.search(
        r"Transferred:\s+([\d.]+\s*\S+)\s*/\s*([\d.]+\s*\S+),\s*\d+%,\s*([\d.]+\s*\S+/s)",
        output,
    )
    if m:
        result["transferred_bytes_human"] = m.group(1)
        result["total_bytes_human"] = m.group(2)
        result["speed"] = m.group(3)
    # Elapsed time
    m = re.search(r"Elapsed time:\s+([\d.]+\S+)", output)
    if m:
        result["elapsed"] = m.group(1)
    return result


class DeploymentManager:
    """Connects KubeClient (layer 1) and ManifestBuilder (layer 2).

    Orchestrates deploy/delete cycles for a Mampok deployment.

    Args:
        kube: Configured KubeClient for the target namespace.
    """

    def __init__(self, kube: KubeClient) -> None:
        """Initialize DeploymentManager.

        Args:
            kube: Configured KubeClient for the target namespace.
        """
        self._kube = kube
        self._builder = ManifestBuilder()

    def deploy(self, cfg: DeploymentConfig, s3_credentials: dict) -> Iterator[dict]:
        """Deploy all Kubernetes resources for a DeploymentConfig.

        Builds manifests via ManifestBuilder and applies them via KubeClient.
        Yields a progress dict after each applied resource.
        Order: Secret -> Deployment -> Service -> Ingress.

        Args:
            cfg: Deployment configuration.
            s3_credentials: S3 credentials dict.

        Yields:
            {"stage": "k8s_apply", "status": "done", "resource": "Kind/name"}
        """
        manifests = self._builder.build_all(cfg, s3_credentials)
        logger.debug("deploy: project_id=%s, manifests=%d", cfg.project_id, len(manifests))
        ManifestValidator.validate_all(manifests)
        yield {"stage": "k8s_validate", "status": "done", "count": len(manifests)}
        for manifest in manifests:
            kind = manifest.get("kind", "Unknown")
            name = manifest.get("metadata", {}).get("name", "unknown")
            logger.debug("applying %s/%s", kind, name)
            self._kube.apply(manifest)
            yield {"stage": "k8s_apply", "status": "done", "resource": f"{kind}/{name}"}

    def delete(self, cfg: DeploymentConfig) -> Iterator[dict]:
        """Delete all Kubernetes resources of a deployment.

        Yields progress dicts analogous to deploy(). Caller must iterate to drive execution.
        When container_data_paths is configured, a final S3 sync is performed first
        (best-effort — never blocks deletion even on failure or timeout).

        Order: (optional S3 sync) -> Deployment -> Service -> Ingress -> Secret -> Auth-Secret.
        All K8s resources are attempted even if earlier deletions fail.
        Non-existing resources are silently ignored (idempotent via KubeClient.delete).

        Args:
            cfg: Deployment configuration.

        Yields:
            {"stage": "s3_final_sync", "status": "starting"|"done"|"skipped"|"failed", ...}
            {"stage": "k8s_delete", "status": "done", "resource": "Kind/name"}

        Raises:
            RuntimeError: If one or more K8s resources could not be deleted.
        """
        logger.debug("delete: project_id=%s", cfg.project_id)

        if cfg.container_data_paths:
            yield from self._final_sync_before_delete(cfg)

        resources = [
            ("Deployment", cfg.deployment_name),
            ("Service", cfg.service_name),
            ("Ingress", cfg.ingress_name),
            ("Secret", cfg.secret_name),
            ("Secret", cfg.auth_secret_name),
        ]
        failures = []
        for kind, name in resources:
            try:
                logger.debug("deleting %s/%s", kind, name)
                self._kube.delete(kind, name)
                yield {"stage": "k8s_delete", "status": "done", "resource": f"{kind}/{name}"}
            except Exception as exc:
                logger.warning("failed to delete %s/%s: %s", kind, name, exc)
                failures.append((kind, name, exc))
        if failures:
            details = "; ".join(f"{k}/{n}: {e}" for k, n, e in failures)
            raise RuntimeError(
                f"Failed to delete {len(failures)} resource(s) for '{cfg.project_id}': {details}"
            )

    def _final_sync_before_delete(self, cfg: DeploymentConfig) -> Iterator[dict]:
        """Exec a final S3 sync in the mampok-s3-sync sidecar before pod deletion.

        Best-effort: always yields a status event and never raises. Deletion proceeds
        regardless of whether the sync succeeded, was skipped, or timed out.

        Uses exec_in_pod_stream() to yield periodic progress events every ~10 s while
        rclone is running, then a final "done" event with the complete stats.

        Yields:
            {"stage": "s3_final_sync", "status": "starting",  "pod": pod_name}
            {"stage": "s3_final_sync", "status": "progress",  "pod": pod_name, ...stats}
            {"stage": "s3_final_sync", "status": "done",      "pod": pod_name, ...stats}
            {"stage": "s3_final_sync", "status": "skipped",   "reason": str}
            {"stage": "s3_final_sync", "status": "failed",    "reason": str}
        """
        try:
            pod_names = self._kube.list_running_pods(f"app={cfg.app_label}")
        except Exception as e:
            logger.warning("final_sync: pod list failed for %s: %s", cfg.project_id, e)
            yield {"stage": "s3_final_sync", "status": "skipped", "reason": "pod_list_failed"}
            return

        if not pod_names:
            logger.warning("final_sync: no running pod for %s", cfg.project_id)
            yield {"stage": "s3_final_sync", "status": "skipped", "reason": "no_running_pod"}
            return

        pod_name = pod_names[0]
        yield {"stage": "s3_final_sync", "status": "starting", "pod": pod_name}
        # rclone copy (not bisync): one-shot local→S3 upload before pod deletion.
        # --stats 10s emits periodic progress; exec_in_pod_stream() surfaces each
        # stats block as a "progress" event so callers can update MongoDB in real time.
        sync_cmd = [
            "/bin/sh", "-c",
            "rclone copy /sync/ S3:$s3bucket/container_data/ "
            "--transfers 4 --retries 3 --stats 10s --log-level INFO",
        ]
        try:
            last_pct = -1
            accumulated = ""
            for accumulated in self._kube.exec_in_pod_stream(
                pod_name=pod_name,
                container=_S3SYNC_SIDECAR_NAME,
                command=sync_cmd,
                timeout=cfg.container_data_sync_timeout,
                poll_interval=10,
            ):
                stats = _parse_rclone_stats(accumulated)
                pct = stats.get("transferred_pct", -1)
                if stats and pct != last_pct:
                    last_pct = pct
                    yield {"stage": "s3_final_sync", "status": "progress", "pod": pod_name, **stats}

            if accumulated:
                logger.info("final_sync output: %s", accumulated.strip())
            final_stats = _parse_rclone_stats(accumulated)
            yield {"stage": "s3_final_sync", "status": "done", "pod": pod_name, **final_stats}
        except Exception as e:
            logger.warning("final_sync: exec failed for %s: %s", cfg.project_id, e)
            yield {"stage": "s3_final_sync", "status": "failed", "reason": str(e)}

    def redeploy(self, cfg: DeploymentConfig, s3_credentials: dict) -> Iterator[dict]:
        """Delete and re-deploy a deployment.

        Args:
            cfg: Deployment configuration.
            s3_credentials: S3 credentials dict.

        Yields:
            Progress dicts from deploy().
        """
        yield from self.delete(cfg)
        yield from self.deploy(cfg, s3_credentials)

    def rollout_status(self, cfg: DeploymentConfig) -> dict:
        """Return the current rollout status of the deployment.

        Args:
            cfg: Deployment configuration.

        Returns:
            Dict with ready_replicas, available_replicas, updated_replicas, conditions.
        """
        deployment = self._kube.get("Deployment", cfg.deployment_name)
        status = deployment.get("status", {})
        return {
            "ready_replicas": status.get("ready_replicas"),
            "available_replicas": status.get("available_replicas"),
            "updated_replicas": status.get("updated_replicas"),
            "conditions": status.get("conditions", []),
        }

    def patch_deployment(self, cfg: DeploymentConfig, patch: dict) -> dict:
        """Apply a Strategic Merge Patch to the deployment.

        Args:
            cfg: Deployment configuration.
            patch: Patch body as dict.

        Returns:
            The patched resource object as dict.
        """
        return self._kube.patch("Deployment", cfg.deployment_name, patch)

    def deployment_exists(self, cfg: DeploymentConfig) -> bool:
        """Check whether the Deployment resource exists on the cluster.

        Args:
            cfg: Deployment configuration.

        Returns:
            True if the Deployment exists, False otherwise.
        """
        return self._kube.exists("Deployment", cfg.deployment_name)

    def _diagnose_pod_failure(self, cfg: DeploymentConfig) -> dict:
        """Query pod container states to determine why pods are not starting.

        Checks for OOMKilled, CrashLoopBackOff, ImagePullBackOff and similar
        failure conditions in container statuses.

        Args:
            cfg: Deployment configuration.

        Returns:
            Dict with "reason" (str), "container" (str), "restart_count" (int),
            and "message" (str) describing the failure.
        """
        import kubernetes.client

        v1 = kubernetes.client.CoreV1Api(api_client=self._kube._api_client)
        try:
            pods = v1.list_namespaced_pod(
                namespace=cfg.namespace,
                label_selector=f"app={cfg.app_label}",
            )
        except Exception as e:
            logger.warning("Could not list pods for %s: %s", cfg.project_id, e)
            return {"reason": "Unknown", "container": "", "restart_count": 0,
                    "message": "Could not query pod status"}

        for pod in pods.items:
            for cs in pod.status.container_statuses or []:
                # Check last terminated state (OOMKilled shows up here after restart)
                last = cs.last_state.terminated if cs.last_state else None
                if last and last.reason == "OOMKilled":
                    return {
                        "reason": "OOMKilled",
                        "container": cs.name,
                        "restart_count": cs.restart_count,
                        "message": (
                            f"Container '{cs.name}' OOMKilled "
                            f"(Restarts: {cs.restart_count}). "
                            "Memory limit möglicherweise zu niedrig."
                        ),
                    }
                # Check current waiting state
                waiting = cs.state.waiting if cs.state else None
                if waiting and waiting.reason in (
                    "CrashLoopBackOff", "Error",
                    "ImagePullBackOff", "ErrImagePull",
                ):
                    return {
                        "reason": waiting.reason,
                        "container": cs.name,
                        "restart_count": cs.restart_count,
                        "message": (
                            f"Container '{cs.name}' ist in Status '{waiting.reason}'"
                            f" (Restarts: {cs.restart_count})"
                            + (f": {waiting.message}" if waiting.message else "")
                        ),
                    }

        return {
            "reason": "Timeout",
            "container": "",
            "restart_count": 0,
            "message": "Pods nicht innerhalb des Timeouts gestartet",
        }

    def _check_and_yield_pod_warning(
        self,
        cfg: DeploymentConfig,
        last_restart_counts: dict,
        fail_fast_reasons: set,
        threshold: int,
    ) -> Iterator[dict]:
        """Diagnose pod failure and yield a k8s_pod_warning step if restart_count increased.

        Calls _diagnose_pod_failure() and yields a new warning step whenever restart_count
        exceeds the previously seen count for that reason. This produces one step per crash
        cycle (rc=1, rc=2, rc=3, ...) so the user sees the count incrementing in the UI.
        Raises TimeoutError immediately on fatal conditions.

        Args:
            cfg: Deployment configuration.
            last_restart_counts: Mutable dict mapping reason → highest restart_count seen
                                  (shared across calls, updated in place).
            fail_fast_reasons: Set of reason strings that are always fatal (e.g. ImagePullBackOff).
            threshold: restart_count at or above which OOM/Crash failures become fatal.

        Yields:
            {"stage": "k8s_pod_warning", ...} whenever restart_count increases for a reason.

        Raises:
            TimeoutError: On fatal failure condition.
        """
        diagnosis = self._diagnose_pod_failure(cfg)
        reason = diagnosis.get("reason", "")
        restart_count = diagnosis.get("restart_count", 0)

        if reason not in ("Timeout", "Unknown"):
            is_fatal = reason in fail_fast_reasons or restart_count >= threshold
            # Emit a step whenever restart_count increased since last check.
            # This produces one warning per crash cycle (rc=1, rc=2, rc=3, ...).
            if restart_count > last_restart_counts.get(reason, -1):
                last_restart_counts[reason] = restart_count
                logger.warning("Pod warning for %s: %s rc=%d (fatal=%s)",
                               cfg.project_id, reason, restart_count, is_fatal)
                yield {
                    "stage": "k8s_pod_warning",
                    "reason": reason,
                    "container": diagnosis.get("container", ""),
                    "restart_count": restart_count,
                    "message": diagnosis.get("message", ""),
                    "fatal": is_fatal,
                }
            if is_fatal:
                raise TimeoutError(
                    f"Deployment '{cfg.deployment_name}' aborted early. "
                    f"{reason}: {diagnosis['message']}"
                )

    def _get_pod_phase(self, cfg: DeploymentConfig) -> str | None:
        """Query pod status to determine the current startup phase.

        Returns:
            "init_containers" if any init container is currently running,
            "starting" if init containers completed but readiness probe not yet passed,
            None if phase cannot be determined or pods are already ready.
        """
        import kubernetes.client

        v1 = kubernetes.client.CoreV1Api(api_client=self._kube._api_client)
        try:
            pods = v1.list_namespaced_pod(
                namespace=cfg.namespace,
                label_selector=f"app={cfg.app_label}",
            )
        except Exception as e:
            logger.debug("Could not get pod phase for %s: %s", cfg.project_id, e)
            return None

        for pod in pods.items:
            for cs in (pod.status.init_container_statuses or []):
                if cs.state and cs.state.running is not None:
                    return "init_containers"
            for cs in (pod.status.container_statuses or []):
                if cs.state and cs.state.running is not None and not cs.ready:
                    return "starting"
        return None

    def wait_for_ready(self, cfg: DeploymentConfig, timeout: int = 900) -> Iterator[dict]:
        """Wait until all replicas are ready via the Kubernetes Watch API.

        Streams Deployment events until ready_replicas >= cfg.replicas.
        Yields a progress dict for each event that reports ready replicas.
        On each Watch event and after every poll interval, checks pod status for
        failure conditions (OOMKilled, CrashLoopBackOff, ImagePullBackOff) and
        yields k8s_pod_warning steps.

        Uses short Watch intervals (_POLL_INTERVAL seconds) so that pod failures
        are detected proactively during CrashLoopBackOff back-off periods, when
        no Deployment Watch events would otherwise fire (ready_replicas stays None).

        Fatal conditions (ImagePullBackOff, or restart_count >= _FAIL_FAST_RESTART_THRESHOLD
        for OOM/Crash) trigger an early abort instead of waiting for the full timeout.

        Args:
            cfg: Deployment configuration.
            timeout: Maximum seconds to wait for pods to become ready. Default: 900s (15min).

        Yields:
            {"stage": "k8s_ready", "status": "running", "ready_replicas": N}
            {"stage": "k8s_pod_warning", "reason": str, "container": str,
             "restart_count": int, "message": str, "fatal": bool}

        Raises:
            TimeoutError: If replicas are not ready within timeout seconds,
                          or immediately on fatal failure conditions.
                          Message includes pod diagnosis reason and details.
        """
        import kubernetes.client
        import kubernetes.watch

        _FAIL_FAST_REASONS = {"ImagePullBackOff", "ErrImagePull"}
        _FAIL_FAST_RESTART_THRESHOLD = 3
        _POLL_INTERVAL = 10

        apps_v1 = kubernetes.client.AppsV1Api(api_client=self._kube._api_client)
        last_restart_counts: dict[str, int] = {}
        last_ready: int = -1  # sentinel: -1 = not yet reported; triggers yield on first event
        deadline = time.monotonic() + timeout

        logger.debug("wait_for_ready: deployment=%s, replicas=%s, timeout=%s",
                     cfg.deployment_name, cfg.replicas, timeout)

        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            poll_seconds = min(_POLL_INTERVAL, remaining)

            for event in kubernetes.watch.Watch().stream(
                apps_v1.list_namespaced_deployment,
                namespace=cfg.namespace,
                field_selector=f"metadata.name={cfg.deployment_name}",
                timeout_seconds=poll_seconds,
            ):
                status = event["object"].status
                ready = status.ready_replicas if (status and status.ready_replicas is not None) else 0
                if ready != last_ready:
                    logger.debug("ready_replicas=%s/%s (was %s)", ready, cfg.replicas, last_ready)
                    phase = self._get_pod_phase(cfg) if ready == 0 else None
                    step: dict = {"stage": "k8s_ready", "status": "running", "ready_replicas": ready}
                    if phase:
                        step["phase"] = phase
                    yield step
                    last_ready = ready
                if ready >= cfg.replicas:
                    return

                # On-event pod diagnosis
                yield from self._check_and_yield_pod_warning(
                    cfg, last_restart_counts, _FAIL_FAST_REASONS, _FAIL_FAST_RESTART_THRESHOLD
                )

            # Poll interval elapsed without Watch events — proactively check pod state.
            # This catches CrashLoopBackOff during back-off periods, when the Deployment's
            # ready_replicas stays None and no Watch events are fired by Kubernetes.
            yield from self._check_and_yield_pod_warning(
                cfg, last_restart_counts, _FAIL_FAST_REASONS, _FAIL_FAST_RESTART_THRESHOLD
            )

        # Total timeout reached
        diagnosis = self._diagnose_pod_failure(cfg)
        raise TimeoutError(
            f"Deployment '{cfg.deployment_name}' not ready within {timeout}s. "
            f"{diagnosis['reason']}: {diagnosis['message']}"
        )

    def rollout_restart(self, cfg: DeploymentConfig) -> dict:
        """Trigger a rolling restart via annotation patch.

        Sets ``mampok/restartedAt`` annotation to current UTC timestamp,
        causing Kubernetes to recreate pods (init containers re-run).

        Args:
            cfg: Deployment configuration.

        Returns:
            The patched resource object as dict.
        """
        patch = {
            "spec": {
                "template": {
                    "metadata": {
                        "annotations": {
                            "mampok/restartedAt": datetime.now(
                                timezone.utc
                            ).isoformat()
                        }
                    }
                }
            }
        }
        return self.patch_deployment(cfg, patch)
