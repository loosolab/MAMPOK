"""DeploymentManager — Schicht 3: Orchestrierung von KubeClient und ManifestBuilder."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Iterator

from mampok.kubernetes.builder import ManifestBuilder
from mampok.kubernetes.client import KubeClient
from mampok.kubernetes.config import DeploymentConfig
from mampok.kubernetes.validator import ManifestValidationError, ManifestValidator

logger = logging.getLogger(__name__)


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

    def delete(self, cfg: DeploymentConfig) -> None:
        """Delete all Kubernetes resources of a deployment.

        Order: Deployment -> Service -> Ingress -> Secret -> Auth-Secret.
        All resources are attempted even if earlier deletions fail.
        Non-existing resources are silently ignored (idempotent via KubeClient.delete).

        Args:
            cfg: Deployment configuration.

        Raises:
            RuntimeError: If one or more resources could not be deleted,
                          listing all failures in the message.
        """
        logger.debug("delete: project_id=%s", cfg.project_id)
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
            except Exception as exc:
                logger.warning("failed to delete %s/%s: %s", kind, name, exc)
                failures.append((kind, name, exc))
        if failures:
            details = "; ".join(f"{k}/{n}: {e}" for k, n, e in failures)
            raise RuntimeError(
                f"Failed to delete {len(failures)} resource(s) for '{cfg.project_id}': {details}"
            )

    def redeploy(self, cfg: DeploymentConfig, s3_credentials: dict) -> Iterator[dict]:
        """Delete and re-deploy a deployment.

        Args:
            cfg: Deployment configuration.
            s3_credentials: S3 credentials dict.

        Yields:
            Progress dicts from deploy().
        """
        self.delete(cfg)
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
        warned_reasons: set,
        fail_fast_reasons: set,
        threshold: int,
    ) -> Iterator[dict]:
        """Diagnose pod failure and yield a k8s_pod_warning step if a failure is detected.

        Calls _diagnose_pod_failure() and yields a warning step on the first occurrence
        of each failure reason. Raises TimeoutError immediately on fatal conditions.

        Args:
            cfg: Deployment configuration.
            warned_reasons: Mutable set tracking already-warned reasons (shared across calls).
            fail_fast_reasons: Set of reason strings that are always fatal (e.g. ImagePullBackOff).
            threshold: restart_count at or above which OOM/Crash failures become fatal.

        Yields:
            {"stage": "k8s_pod_warning", ...} on first occurrence of each failure reason.

        Raises:
            TimeoutError: On fatal failure condition.
        """
        diagnosis = self._diagnose_pod_failure(cfg)
        reason = diagnosis.get("reason", "")
        restart_count = diagnosis.get("restart_count", 0)

        if reason not in ("Timeout", "Unknown"):
            is_fatal = reason in fail_fast_reasons or restart_count >= threshold
            if reason not in warned_reasons:
                warned_reasons.add(reason)
                logger.warning("Pod warning for %s: %s (fatal=%s)",
                               cfg.project_id, reason, is_fatal)
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
        warned_reasons: set[str] = set()
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
                if status is not None and status.ready_replicas is not None:
                    logger.debug("ready_replicas=%s/%s", status.ready_replicas, cfg.replicas)
                    yield {
                        "stage": "k8s_ready",
                        "status": "running",
                        "ready_replicas": status.ready_replicas,
                    }
                    if status.ready_replicas >= cfg.replicas:
                        return

                # On-event pod diagnosis
                yield from self._check_and_yield_pod_warning(
                    cfg, warned_reasons, _FAIL_FAST_REASONS, _FAIL_FAST_RESTART_THRESHOLD
                )

            # Poll interval elapsed without Watch events — proactively check pod state.
            # This catches CrashLoopBackOff during back-off periods, when the Deployment's
            # ready_replicas stays None and no Watch events are fired by Kubernetes.
            yield from self._check_and_yield_pod_warning(
                cfg, warned_reasons, _FAIL_FAST_REASONS, _FAIL_FAST_RESTART_THRESHOLD
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
