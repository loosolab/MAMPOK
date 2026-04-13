"""Kubernetes client — Schicht 1: generischer K8s-Wrapper ohne Mampok-Logik."""

from __future__ import annotations

import logging
from typing import Any

from kubernetes.client.rest import ApiException

logger = logging.getLogger(__name__)


class KubeClient:
    """Thin wrapper around the official kubernetes Python client.

    Contains no Mampok-specific logic and is fully reusable.
    Routes to the correct K8s API group based on the ``kind`` field in manifests.

    Args:
        namespace: Kubernetes namespace for all operations.
        api_client: Pre-configured kubernetes ApiClient (mandatory).
    """

    _API_PATHS: dict[str, str] = {
        "Deployment": "/apis/apps/v1/namespaces/{namespace}/deployments/{name}",
        "Service": "/api/v1/namespaces/{namespace}/services/{name}",
        "Secret": "/api/v1/namespaces/{namespace}/secrets/{name}",
        "Ingress": "/apis/networking.k8s.io/v1/namespaces/{namespace}/ingresses/{name}",
        "Job": "/apis/batch/v1/namespaces/{namespace}/jobs/{name}",
    }

    _RESPONSE_TYPES: dict[str, str] = {
        "Deployment": "V1Deployment",
        "Service": "V1Service",
        "Secret": "V1Secret",
        "Ingress": "V1Ingress",
        "Job": "V1Job",
    }

    def __init__(self, namespace: str, api_client: Any) -> None:
        """Initialize KubeClient.

        Args:
            namespace: Kubernetes namespace for all operations.
            api_client: Pre-configured kubernetes ApiClient (mandatory).
        """
        self._namespace = namespace
        self._api_client = api_client

    def _resolve_path(self, kind: str, name: str) -> str:
        """Build the API path for a given kind and resource name.

        Args:
            kind: Resource kind (e.g. "Deployment", "Service").
            name: Resource name.

        Returns:
            Formatted API path string.

        Raises:
            ValueError: If kind is not supported.
        """
        if kind not in self._API_PATHS:
            raise ValueError(
                f"Unsupported kind '{kind}'. Supported: {list(self._API_PATHS)}"
            )
        return self._API_PATHS[kind].format(namespace=self._namespace, name=name)

    def apply(self, manifest: dict) -> dict:
        """Apply a Kubernetes manifest using Server-Side Apply.

        Behaves like ``kubectl apply``: creates the resource if it doesn't exist,
        updates it if it does. Uses fieldManager="mampok" and force=True.

        Args:
            manifest: Complete K8s manifest as dict (with apiVersion, kind,
                metadata, spec).

        Returns:
            The created/updated resource object as dict.
        """
        kind = manifest["kind"]
        name = manifest["metadata"]["name"]
        logger.debug("apply: %s/%s", kind, name)
        path = self._resolve_path(kind, name)
        response_type = self._RESPONSE_TYPES[kind]

        result = self._api_client.call_api(
            resource_path=path,
            method="PATCH",
            header_params={
                "Content-Type": "application/apply-patch+yaml",
                "Accept": "application/json",
            },
            body=manifest,
            auth_settings=["BearerToken"],
            response_type=response_type,
            _return_http_data_only=True,
            query_params=[("fieldManager", "mampok"), ("force", "true")],
        )
        return result.to_dict()

    def apply_many(self, manifests: list[dict]) -> list[dict]:
        """Apply multiple Kubernetes manifests. Skips None entries. Fail-fast.

        Args:
            manifests: List of K8s manifests. None entries are skipped.

        Returns:
            List of created/updated resource objects as dicts.
        """
        results = []
        for manifest in manifests:
            if manifest is None:
                continue
            results.append(self.apply(manifest))
        return results

    def get(self, kind: str, name: str) -> dict:
        """Read a Kubernetes resource.

        Args:
            kind: Resource kind (e.g. "Deployment").
            name: Resource name.

        Returns:
            The resource object as dict.
        """
        logger.debug("get: %s/%s", kind, name)
        path = self._resolve_path(kind, name)
        response_type = self._RESPONSE_TYPES[kind]

        result = self._api_client.call_api(
            resource_path=path,
            method="GET",
            header_params={"Accept": "application/json"},
            auth_settings=["BearerToken"],
            response_type=response_type,
            _return_http_data_only=True,
        )
        return result.to_dict()

    def delete(self, kind: str, name: str) -> None:
        """Delete a Kubernetes resource. Idempotent — ignores 404.

        Args:
            kind: Resource kind (e.g. "Deployment", "Service").
            name: Resource name.
        """
        logger.debug("delete: %s/%s", kind, name)
        path = self._resolve_path(kind, name)

        try:
            self._api_client.call_api(
                resource_path=path,
                method="DELETE",
                header_params={"Accept": "application/json"},
                auth_settings=["BearerToken"],
                response_type="object",
                _return_http_data_only=True,
            )
        except ApiException as e:
            if e.status == 404:
                return
            raise

    def exists(self, kind: str, name: str) -> bool:
        """Check whether a Kubernetes resource exists.

        Args:
            kind: Resource kind.
            name: Resource name.

        Returns:
            True if the resource exists, False otherwise.
        """
        try:
            self.get(kind, name)
            return True
        except ApiException as e:
            if e.status == 404:
                return False
            raise

    def list_running_pods(self, label_selector: str) -> list[str]:
        """Return names of Running pods matching the label selector.

        Args:
            label_selector: K8s label selector string (e.g. "app=myapp").

        Returns:
            List of pod names whose phase is Running.
        """
        import kubernetes.client

        v1 = kubernetes.client.CoreV1Api(api_client=self._api_client)
        pods = v1.list_namespaced_pod(
            namespace=self._namespace,
            label_selector=label_selector,
        )
        return [p.metadata.name for p in pods.items if p.status.phase == "Running"]

    def exec_in_pod(
        self,
        pod_name: str,
        container: str,
        command: list[str],
        timeout: int = 300,
    ) -> str:
        """Execute a command in a running container and return combined stdout+stderr.

        Blocks until the command exits or the timeout is reached. The caller can treat
        a normal return as confirmation that the command completed successfully.

        Args:
            pod_name: Name of the pod.
            container: Container name within the pod.
            command: Command as list (e.g. ["/bin/sh", "-c", "echo hi"]).
            timeout: Maximum seconds to wait for the command to complete.

        Returns:
            Combined stdout+stderr output as a string.

        Raises:
            Exception: If exec setup fails (pod not found, container not running, etc.).
        """
        import kubernetes.client
        import kubernetes.stream

        v1 = kubernetes.client.CoreV1Api(api_client=self._api_client)
        ws = kubernetes.stream.stream(
            v1.connect_get_namespaced_pod_exec,
            pod_name,
            self._namespace,
            container=container,
            command=command,
            stderr=True,
            stdin=False,
            stdout=True,
            tty=False,
            _preload_content=False,
        )
        ws.run_forever(timeout=timeout)
        parts: list[str] = []
        if ws.peek_stdout():
            parts.append(ws.read_stdout())
        if ws.peek_stderr():
            parts.append(ws.read_stderr())
        return "".join(parts)

    def patch(self, kind: str, name: str, body: dict) -> dict:
        """Apply a Strategic Merge Patch to a resource.

        Args:
            kind: Resource kind (e.g. "Deployment").
            name: Resource name.
            body: Patch body as dict.

        Returns:
            The patched resource object as dict.
        """
        logger.debug("patch: %s/%s", kind, name)
        path = self._resolve_path(kind, name)
        response_type = self._RESPONSE_TYPES[kind]

        result = self._api_client.call_api(
            resource_path=path,
            method="PATCH",
            header_params={
                "Content-Type": "application/strategic-merge-patch+json",
                "Accept": "application/json",
            },
            body=body,
            auth_settings=["BearerToken"],
            response_type=response_type,
            _return_http_data_only=True,
        )
        return result.to_dict()
