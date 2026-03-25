"""ManifestBuilder — Schicht 2: reine Datentransformation Config → K8s-Manifest."""

from __future__ import annotations

import base64
import logging

from mampok.kubernetes.config import DeploymentConfig

logger = logging.getLogger(__name__)


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
            s3_credentials: Dict with s3_endpoint, s3_key, s3_secret, s3_files.

        Returns:
            Complete K8s Secret manifest (type: Opaque).
        """
        return {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {"name": cfg.secret_name, "namespace": cfg.namespace},
            "type": "Opaque",
            "data": {
                "s3_endpoint": self._b64(s3_credentials["s3_endpoint"]),
                "s3_key": self._b64(s3_credentials["s3_key"]),
                "s3_secret": self._b64(s3_credentials["s3_secret"]),
                "s3_files": self._b64(s3_credentials["s3_files"]),
            },
        }

    def build_auth_secret(self, cfg: DeploymentConfig, htpasswd_content: str) -> dict:
        """Build the basic-auth Secret manifest.

        Args:
            cfg: Deployment configuration.
            htpasswd_content: htpasswd file content (bcrypt-hashed passwords).

        Returns:
            Complete K8s Secret manifest (type: kubernetes.io/basic-auth).
        """
        return {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {"name": cfg.auth_secret_name, "namespace": cfg.namespace},
            "type": "kubernetes.io/basic-auth",
            "data": {"auth": self._b64(htpasswd_content)},
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

        if cfg.env:
            container["env"] = cfg.env
        if cfg.args:
            container["args"] = cfg.args
        if cfg.command:
            container["command"] = cfg.command
        if cfg.volume_mounts:
            container["volumeMounts"] = cfg.volume_mounts
        if cfg.readiness_probe:
            container["readinessProbe"] = cfg.readiness_probe

        pod_spec: dict = {"containers": [container]}

        if cfg.init_container:
            _MAMPOK_FIELDS = {"tool", "containertype", "downloadpaths", "volume"}
            k8s_init = {k: v for k, v in cfg.init_container.items() if k not in _MAMPOK_FIELDS}
            pod_spec["initContainers"] = [k8s_init]
        if cfg.volumes:
            pod_spec["volumes"] = cfg.volumes

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
                else f"/{cfg.project_id}/{cfg.tool}/"
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
            "tls": [{"hosts": [cfg.host], "secretName": cfg.tls_secret}],
            "rules": [
                {
                    "host": cfg.host,
                    "http": {
                        "paths": [
                            {
                                "path": f"/{cfg.project_id}/{cfg.tool}",
                                "pathType": "Prefix",
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
        return result
