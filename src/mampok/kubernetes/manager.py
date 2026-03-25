"""DeploymentManager — Schicht 3: Orchestrierung von KubeClient und ManifestBuilder."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterator

from mampok.kubernetes.builder import ManifestBuilder
from mampok.kubernetes.client import KubeClient
from mampok.kubernetes.config import DeploymentConfig


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
        for manifest in manifests:
            kind = manifest.get("kind", "Unknown")
            name = manifest.get("metadata", {}).get("name", "unknown")
            self._kube.apply(manifest)
            yield {"stage": "k8s_apply", "status": "done", "resource": f"{kind}/{name}"}

    def delete(self, cfg: DeploymentConfig) -> None:
        """Delete all Kubernetes resources of a deployment.

        Order: Deployment -> Service -> Ingress -> Secret -> Auth-Secret.
        Non-existing resources are silently ignored (idempotent via KubeClient.delete).

        Args:
            cfg: Deployment configuration.
        """
        for kind, name in [
            ("Deployment", cfg.deployment_name),
            ("Service", cfg.service_name),
            ("Ingress", cfg.ingress_name),
            ("Secret", cfg.secret_name),
            ("Secret", cfg.auth_secret_name),
        ]:
            self._kube.delete(kind, name)

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

    def wait_for_ready(self, cfg: DeploymentConfig, timeout: int = 300) -> Iterator[dict]:
        """Wait until all replicas are ready via the Kubernetes Watch API.

        Streams Deployment events until ready_replicas >= cfg.replicas.
        Yields a progress dict for each event that reports ready replicas.
        Readiness is determined by K8s Readiness Probes (defined in the
        Mamplate, included in the Deployment manifest).

        Args:
            cfg: Deployment configuration.
            timeout: Maximum seconds to wait for pods to become ready.

        Yields:
            {"stage": "k8s_ready", "status": "running", "ready_replicas": N}

        Raises:
            TimeoutError: If replicas are not ready within timeout seconds.
        """
        import kubernetes.client
        import kubernetes.watch

        apps_v1 = kubernetes.client.AppsV1Api(api_client=self._kube._api_client)
        w = kubernetes.watch.Watch()

        for event in w.stream(
            apps_v1.list_namespaced_deployment,
            namespace=cfg.namespace,
            field_selector=f"metadata.name={cfg.deployment_name}",
            timeout_seconds=timeout,
        ):
            status = event["object"].status
            if status is not None and status.ready_replicas is not None:
                yield {
                    "stage": "k8s_ready",
                    "status": "running",
                    "ready_replicas": status.ready_replicas,
                }
                if status.ready_replicas >= cfg.replicas:
                    w.stop()
                    return

        raise TimeoutError(
            f"Deployment {cfg.deployment_name!r} not ready within {timeout}s"
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
