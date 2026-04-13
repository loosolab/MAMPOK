"""ManifestBuilder — Schicht 2: reine Datentransformation Config → K8s-Manifest."""

from __future__ import annotations

import base64
import json
import logging
import re
from urllib.parse import urlparse

from mampok.kubernetes.config import DeploymentConfig

logger = logging.getLogger(__name__)

_S3DOWNLOAD_IMAGE = "amazon/aws-cli:2"
_S3DOWNLOAD_COMMAND = ["/bin/sh", "-c"]
_S3DOWNLOAD_ARGS = [
    "aws --endpoint-url $(s3endpoint) s3 cp s3://$(s3bucket)/analysis_data/ /analysis_data/ --recursive"
]
_S3DOWNLOAD_RESOURCES = {
    "limits": {"cpu": "1", "memory": "1Gi"},
    "requests": {"cpu": "0.5", "memory": "0.5Gi"},
}
_FILEDIR_VOLUME_NAME = "filedir"
_FILEDIR_MOUNT_PATH = "/analysis_data"
_MAMPOK_FIELDS = {"tool", "containertype", "container_data", "volume"}
_S3SYNC_IMAGE = "amazon/aws-cli:2"
_S3SYNC_SIDECAR_NAME = "mampok-s3-sync"
_S3SYNC_RESOURCES = {
    "limits": {"cpu": "200m", "memory": "256Mi"},
    "requests": {"cpu": "50m", "memory": "64Mi"},
}


class ManifestBuilder:
    """Generates Kubernetes manifests from a DeploymentConfig.

    No state, no API calls — purely functional and fully unit-testable.
    Returns None when a resource is not needed for the given config
    (e.g. no Ingress when no URL is set).
    """

    @staticmethod
    def _b64(value: str) -> str:
        """Base64-encode a string value."""
        return base64.b64encode(value.encode()).decode()

    def build_secret(self, cfg: DeploymentConfig, s3_credentials: dict) -> dict:
        """Build the S3 credentials Secret manifest.

        Args:
            cfg: Deployment configuration.
            s3_credentials: Dict with s3_key, s3_secret.

        Returns:
            Complete K8s Secret manifest (type: Opaque).
        """
        return {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {"name": cfg.secret_name, "namespace": cfg.namespace},
            "type": "Opaque",
            "data": {
                "s3_key": self._b64(s3_credentials["s3_key"]),
                "s3_secret": self._b64(s3_credentials["s3_secret"]),
            },
        }

    def build_auth_secret(self, cfg: DeploymentConfig, auth_data: dict) -> dict:
        """Build the auth proxy Secret manifest.

        Args:
            cfg: Deployment configuration.
            auth_data: Dict with keys: secret_key, users, owner, groups.

        Returns:
            Complete K8s Secret manifest (Opaque) with auth-proxy.json key.
        """
        return {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {"name": cfg.auth_secret_name, "namespace": cfg.namespace},
            "data": {"auth-proxy.json": self._b64(json.dumps(auth_data))},
        }

    def build_deployment(self, cfg: DeploymentConfig) -> dict:
        """Build the Deployment manifest.

        Args:
            cfg: Deployment configuration.

        Returns:
            Complete K8s Deployment manifest (apps/v1).
        """
        container: dict = {
            "name": "main-container",
            "image": cfg.image,
            "ports": [{"containerPort": p} for p in cfg.ports],
            "resources": {
                "limits": {"cpu": cfg.cpu, "memory": cfg.memory},
                "requests": {
                    "cpu": cfg.effective_request_cpu,
                    "memory": cfg.effective_request_memory,
                },
            },
        }

        env = list(cfg.env)
        if cfg.direct_s3_access:
            env = [
                {"name": "AWS_ACCESS_KEY_ID",
                 "valueFrom": {"secretKeyRef": {"name": cfg.secret_name, "key": "s3_key"}}},
                {"name": "AWS_SECRET_ACCESS_KEY",
                 "valueFrom": {"secretKeyRef": {"name": cfg.secret_name, "key": "s3_secret"}}},
                {"name": "AWS_ENDPOINT_URL", "value": cfg.endpoint},
            ] + env
        if env:
            container["env"] = env
        if cfg.args:
            container["args"] = cfg.args
        if cfg.command:
            container["command"] = cfg.command
        if cfg.volume_mounts:
            container["volumeMounts"] = cfg.volume_mounts
        if cfg.readiness_probe:
            container["readinessProbe"] = cfg.readiness_probe

        pod_spec: dict = {"containers": [container]}

        init_containers = []

        # --- emptyDir volumes for container_data paths ---
        # Mount at native app path in main container, at /sync/<subpath>/ in sidecar
        sync_volume_mounts_main = []
        sync_volume_mounts_sidecar = []
        for cpath in cfg.container_data_paths:
            vol_name = _sync_volume_name(cpath)
            subpath = _sync_sidecar_subpath(cpath)
            sync_volume_mounts_main.append({"name": vol_name, "mountPath": cpath.rstrip("/")})
            sync_volume_mounts_sidecar.append({"name": vol_name, "mountPath": f"/sync/{subpath}"})
            pod_spec.setdefault("volumes", []).append({"name": vol_name, "emptyDir": {}})

        if sync_volume_mounts_main:
            container.setdefault("volumeMounts", []).extend(sync_volume_mounts_main)

        if cfg.include_s3download:
            s3_download_volume_mounts = [{"name": _FILEDIR_VOLUME_NAME, "mountPath": _FILEDIR_MOUNT_PATH}]
            if cfg.container_data_restore and cfg.container_data_paths:
                # Restore init container mounts all sync volumes at native paths too
                restore_mounts = [
                    {"name": _sync_volume_name(p), "mountPath": p.rstrip("/")}
                    for p in cfg.container_data_paths
                ]
                restore_cmd_parts = " && ".join(
                    f"aws --endpoint-url $(s3endpoint) s3 cp "
                    f"s3://$(s3bucket)/container_data/{_sync_sidecar_subpath(p)}/ {p.rstrip('/')}/ "
                    f"--recursive || true"
                    for p in cfg.container_data_paths
                )
                init_containers.append({
                    "name": "init-container-restore",
                    "image": _S3DOWNLOAD_IMAGE,
                    "command": _S3DOWNLOAD_COMMAND,
                    "args": [restore_cmd_parts],
                    "env": [
                        {"name": "AWS_ACCESS_KEY_ID",
                         "valueFrom": {"secretKeyRef": {"name": cfg.secret_name, "key": "s3_key"}}},
                        {"name": "AWS_SECRET_ACCESS_KEY",
                         "valueFrom": {"secretKeyRef": {"name": cfg.secret_name, "key": "s3_secret"}}},
                        {"name": "s3endpoint", "value": cfg.endpoint},
                        {"name": "s3bucket", "value": cfg.bucket},
                    ],
                    "resources": _S3DOWNLOAD_RESOURCES,
                    "volumeMounts": restore_mounts,
                })

            init_containers.append({
                "name": "init-container",
                "image": _S3DOWNLOAD_IMAGE,
                "command": _S3DOWNLOAD_COMMAND,
                "args": _S3DOWNLOAD_ARGS,
                "env": [
                    {"name": "AWS_ACCESS_KEY_ID",
                     "valueFrom": {"secretKeyRef": {"name": cfg.secret_name, "key": "s3_key"}}},
                    {"name": "AWS_SECRET_ACCESS_KEY",
                     "valueFrom": {"secretKeyRef": {"name": cfg.secret_name, "key": "s3_secret"}}},
                    {"name": "s3endpoint", "value": cfg.endpoint},
                    {"name": "s3bucket", "value": cfg.bucket},
                ],
                "resources": _S3DOWNLOAD_RESOURCES,
                "volumeMounts": s3_download_volume_mounts,
            })
            filedir_vol = {"name": _FILEDIR_VOLUME_NAME, "emptyDir": {}}
            if not any(v.get("name") == _FILEDIR_VOLUME_NAME for v in pod_spec.get("volumes", [])):
                pod_spec.setdefault("volumes", []).append(filedir_vol)

        for custom in cfg.init_containers:
            name = custom.get("tool", "init-container")
            k8s_init: dict = {"name": name}
            k8s_init.update({k: v for k, v in custom.items() if k not in _MAMPOK_FIELDS})
            volume = custom.get("volume")
            if volume:
                k8s_init["volumeMounts"] = [{"name": volume["name"], "mountPath": volume["mountPath"]}]
                vol_entry = {"name": volume["name"], "emptyDir": {}}
                if not any(v.get("name") == volume["name"] for v in pod_spec.get("volumes", [])):
                    pod_spec.setdefault("volumes", []).append(vol_entry)
            init_containers.append(k8s_init)

        if init_containers:
            pod_spec["initContainers"] = init_containers

        if cfg.volumes:
            existing_names = {v.get("name") for v in pod_spec.get("volumes", [])}
            for vol in cfg.volumes:
                if vol.get("name") not in existing_names:
                    pod_spec.setdefault("volumes", []).append(vol)

        if cfg.auth:
            if not cfg.auth_proxy_image:
                raise ValueError(
                    f"Deployment {cfg.deployment_name!r}: auth=True but auth_proxy_image is empty. "
                    "Configure auth_proxy in the cluster config."
                )

            auth_volume_name = f"{cfg.auth_secret_name}-volume"

            redirect_url = (
                "/"
                if "nginx.ingress.kubernetes.io/proxy-redirect-to" in cfg.auth_annotations
                else urlparse(cfg.url).path or f"/{cfg.project_id}/{cfg.tool}/"
            )

            gatekeeper: dict = {
                "name": "gatekeeper",
                "image": cfg.auth_proxy_image,
                "ports": [{"containerPort": cfg.proxy_port}],
                "resources": {
                    "limits": {"cpu": cfg.proxy_cpu, "memory": cfg.proxy_memory},
                    "requests": {"cpu": cfg.proxy_cpu, "memory": cfg.proxy_memory},
                },
                "env": [
                    {"name": "REVERSE_PORT", "value": str(cfg.ports[0])},
                    {"name": "REDIRECT_HOST", "value": f"https://{cfg.host}"},
                    {"name": "REDIRECT_URL", "value": redirect_url},
                    {"name": "PROJECT_ID", "value": cfg.project_id},
                ],
                "volumeMounts": [
                    {"name": auth_volume_name, "mountPath": cfg.auth_config_mount_path}
                ],
            }

            pod_spec["containers"] = [gatekeeper, container]

            pod_spec.setdefault("volumes", [])
            pod_spec["volumes"].append(
                {"name": auth_volume_name, "secret": {"secretName": cfg.auth_secret_name}}
            )

            if cfg.image_pull_secrets:
                pod_spec["imagePullSecrets"] = [{"name": s} for s in cfg.image_pull_secrets]

        # --- S3 sync sidecar (appended after auth container setup) ---
        if cfg.container_data_paths:
            sync_cmd = (
                "trap 'exit 0' TERM INT; "
                "while true; do "
                "aws s3 sync /sync/ s3://$s3bucket/container_data/ "
                "--endpoint-url $s3endpoint --only-show-errors; "
                "sleep $MAMPOK_SYNC_INTERVAL & "
                "wait $!; "
                "done"
            )
            sidecar: dict = {
                "name": _S3SYNC_SIDECAR_NAME,
                "image": _S3SYNC_IMAGE,
                "command": ["/bin/sh", "-c"],
                "args": [sync_cmd],
                "env": [
                    {"name": "AWS_ACCESS_KEY_ID",
                     "valueFrom": {"secretKeyRef": {"name": cfg.secret_name, "key": "s3_key"}}},
                    {"name": "AWS_SECRET_ACCESS_KEY",
                     "valueFrom": {"secretKeyRef": {"name": cfg.secret_name, "key": "s3_secret"}}},
                    {"name": "s3endpoint", "value": cfg.endpoint},
                    {"name": "s3bucket", "value": cfg.bucket},
                    {"name": "MAMPOK_SYNC_INTERVAL", "value": str(cfg.container_data_sync_interval)},
                ],
                "resources": _S3SYNC_RESOURCES,
                "volumeMounts": sync_volume_mounts_sidecar,
            }
            pod_spec["containers"].append(sidecar)

        return {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {
                "name": cfg.deployment_name,
                "namespace": cfg.namespace,
                "labels": {"app": cfg.app_label, **cfg.labels},
            },
            "spec": {
                "replicas": cfg.replicas,
                "selector": {"matchLabels": {"app": cfg.app_label}},
                "template": {
                    "metadata": {
                        "labels": {"app": cfg.app_label, **cfg.labels},
                    },
                    "spec": pod_spec,
                },
            },
        }

    def build_service(self, cfg: DeploymentConfig) -> dict | None:
        """Build the Service manifest.

        Args:
            cfg: Deployment configuration.

        Returns:
            Complete K8s Service manifest, or None if cfg.ports is empty.
        """
        if not cfg.ports:
            return None

        if cfg.auth:
            service_ports = [
                {
                    "name": "main-app-port",
                    "port": cfg.ports[0],
                    "targetPort": cfg.ports[0],
                    "protocol": "TCP",
                },
                {
                    "name": "gatekeeper-port",
                    "port": cfg.proxy_port,
                    "targetPort": cfg.proxy_port,
                    "protocol": "TCP",
                },
            ]
        else:
            service_ports = [
                {"port": 80, "targetPort": cfg.ports[0], "protocol": "TCP"}
            ]

        return {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": cfg.service_name, "namespace": cfg.namespace},
            "spec": {
                "type": "ClusterIP",
                "selector": {"app": cfg.app_label},
                "ports": service_ports,
            },
        }

    def build_ingress(self, cfg: DeploymentConfig) -> dict | None:
        """Build the Ingress manifest.

        Args:
            cfg: Deployment configuration.

        Returns:
            Complete K8s Ingress manifest, or None if url or host is empty.
        """
        if not cfg.url or not cfg.host:
            return None

        annotations = dict(cfg.ingress_annotations)
        if cfg.auth:
            annotations.update(cfg.auth_annotations)

        metadata: dict = {
            "name": cfg.ingress_name,
            "namespace": cfg.namespace,
            "annotations": annotations,
        }

        spec: dict = {
            "rules": [
                {
                    "host": cfg.host,
                    "http": {
                        "paths": [
                            {
                                "path": _ingress_path(urlparse(cfg.url).path, cfg.ingress_annotations),
                                "pathType": _ingress_path_type(cfg.ingress_annotations),
                                "backend": {
                                    "service": {
                                        "name": cfg.service_name,
                                        "port": {"name": "gatekeeper-port"} if cfg.auth else {"number": 80},
                                    },
                                },
                            }
                        ]
                    },
                }
            ],
        }

        if cfg.tls_secret:
            spec["tls"] = [{"hosts": [cfg.host], "secretName": cfg.tls_secret}]

        if cfg.ingress_class:
            spec["ingressClassName"] = cfg.ingress_class

        return {
            "apiVersion": "networking.k8s.io/v1",
            "kind": "Ingress",
            "metadata": metadata,
            "spec": spec,
        }

    def build_all(
        self, cfg: DeploymentConfig, s3_credentials: dict
    ) -> list[dict]:
        """Build all required manifests for this deployment.

        Calls all build_* methods and filters out None values.
        Order: Secret -> Deployment -> Service -> Ingress.
        Note: build_auth_secret is NOT called here (managed separately).

        Args:
            cfg: Deployment configuration.
            s3_credentials: S3 credentials dict.

        Returns:
            List of K8s manifests (no None entries).
        """
        logger.debug("build_all: project_id=%s, image=%s, ports=%s, auth=%s", cfg.project_id, cfg.image, cfg.ports, cfg.auth)
        manifests = [
            self.build_secret(cfg, s3_credentials),
            self.build_deployment(cfg),
            self.build_service(cfg),
            self.build_ingress(cfg),
        ]
        result = [m for m in manifests if m is not None]
        logger.debug("build_all: built %d manifests: %s", len(result), [m.get("kind") for m in result])
        logger.debug("build_all: manifests=%s", result)
        return result


def _sync_volume_name(container_path: str) -> str:
    """Generate a K8s-safe emptyDir volume name from a container path.

    Examples:
        '/app/.cellxgene/annotations/' → 'mampok-sync-app-cellxgene-annotations'
        '/app/results/'                → 'mampok-sync-app-results'
    """
    clean = container_path.strip("/ ")
    clean = re.sub(r"[^a-z0-9]+", "-", clean.lower()).strip("-")
    return f"mampok-sync-{clean}"[:63]


def _sync_sidecar_subpath(container_path: str) -> str:
    """Generate the sidecar mount subdirectory name from a container path.

    This is the subdirectory under /sync/ where the sidecar mounts the volume,
    which also becomes the S3 key prefix under container_data/.

    Examples:
        '/app/.cellxgene/annotations/' → 'app-cellxgene-annotations'
        '/app/results/'                → 'app-results'
    """
    clean = container_path.strip("/ ")
    return re.sub(r"[^a-z0-9]+", "-", clean.lower()).strip("-")


def _has_capture_group_rewrite(annotations: dict) -> bool:
    """Return True if annotations contain a rewrite-target with capture groups ($1/$2)."""
    rewrite = annotations.get("nginx.ingress.kubernetes.io/rewrite-target", "")
    return "$" in rewrite


def _ingress_path(base_path: str, annotations: dict) -> str:
    """Return the ingress path, appending capture group suffix for rewrite-target annotations.

    Trailing slash is stripped from base_path so the rule matches both
    '/path' and '/path/' (with or without trailing slash from the browser).
    """
    if _has_capture_group_rewrite(annotations):
        return base_path.rstrip("/") + "(/|$)(.*)"
    return base_path


def _ingress_path_type(annotations: dict) -> str:
    """Return 'ImplementationSpecific' for regex paths, 'Prefix' otherwise."""
    if _has_capture_group_rewrite(annotations):
        return "ImplementationSpecific"
    return "Prefix"
