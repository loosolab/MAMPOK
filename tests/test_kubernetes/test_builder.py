"""Tests für ManifestBuilder und DeploymentConfig."""

from __future__ import annotations

import base64

from mampok.kubernetes.builder import ManifestBuilder
from mampok.kubernetes.config import DeploymentConfig


class TestDeploymentConfig:
    """Tests for DeploymentConfig dataclass."""

    def test_minimal_config(self):
        cfg = DeploymentConfig(
            project_id="proj1", tool="nginx", image="nginx:latest", namespace="ns"
        )
        assert cfg.project_id == "proj1"
        assert cfg.replicas == 1
        assert cfg.cpu == "1"
        assert cfg.memory == "2Gi"
        assert cfg.ports == []
        assert cfg.env == []
        assert cfg.args == []
        assert cfg.command == []
        assert cfg.volumes == []
        assert cfg.volume_mounts == []
        assert cfg.readiness_probe is None
        assert cfg.init_container is None
        assert cfg.request_cpu == ""
        assert cfg.request_memory == ""
        assert cfg.host == ""

    def test_full_config(self):
        cfg = DeploymentConfig(
            project_id="proj1",
            tool="app",
            image="app:v2",
            namespace="prod",
            replicas=3,
            cpu="2",
            memory="4Gi",
            request_cpu="500m",
            request_memory="1Gi",
            ports=[8080, 9090],
            env=[{"name": "KEY", "value": "VAL"}],
            args=["--flag"],
            command=["/bin/sh"],
            url="https://example.com",
            host="example.com",
            auth=True,
            labels={"team": "bio"},
            volume_mounts=[{"name": "data", "mountPath": "/data"}],
            volumes=[{"name": "data", "emptyDir": {}}],
            readiness_probe={"httpGet": {"path": "/health", "port": 8080}},
            init_container={"name": "init", "image": "busybox"},
        )
        assert cfg.replicas == 3
        assert cfg.request_cpu == "500m"
        assert cfg.volumes == [{"name": "data", "emptyDir": {}}]
        assert cfg.readiness_probe is not None

    def test_naming_properties(self, make_config):
        cfg = make_config(project_id="abc", tool="web")
        assert cfg.deployment_name == "abc-dpl-web"
        assert cfg.service_name == "abc-svc-web"
        assert cfg.ingress_name == "abc-ing-web"
        assert cfg.secret_name == "abc-sc-web"
        assert cfg.auth_secret_name == "abc-sc-web-auth"
        assert cfg.app_label == "abc-mampok-web"

    def test_effective_request_cpu_fallback(self, make_config):
        cfg = make_config(cpu="2", request_cpu="")
        assert cfg.effective_request_cpu == "2"

    def test_effective_request_cpu_explicit(self, make_config):
        cfg = make_config(cpu="2", request_cpu="500m")
        assert cfg.effective_request_cpu == "500m"

    def test_effective_request_memory_fallback(self, make_config):
        cfg = make_config(memory="4Gi", request_memory="")
        assert cfg.effective_request_memory == "4Gi"

    def test_effective_request_memory_explicit(self, make_config):
        cfg = make_config(memory="4Gi", request_memory="1Gi")
        assert cfg.effective_request_memory == "1Gi"


class TestBuildSecret:
    """Tests for ManifestBuilder.build_secret."""

    def test_structure(self, make_config, sample_s3_credentials):
        builder = ManifestBuilder()
        cfg = make_config()
        secret = builder.build_secret(cfg, sample_s3_credentials)

        assert secret["apiVersion"] == "v1"
        assert secret["kind"] == "Secret"
        assert secret["type"] == "Opaque"
        assert secret["metadata"]["name"] == cfg.secret_name
        assert secret["metadata"]["namespace"] == cfg.namespace

    def test_base64_encoding(self, make_config, sample_s3_credentials):
        builder = ManifestBuilder()
        secret = builder.build_secret(make_config(), sample_s3_credentials)

        for key in ("s3_endpoint", "s3_key", "s3_secret", "s3_files"):
            decoded = base64.b64decode(secret["data"][key]).decode()
            assert decoded == sample_s3_credentials[key]


class TestBuildAuthSecret:
    """Tests for ManifestBuilder.build_auth_secret."""

    def test_structure(self, make_config):
        builder = ManifestBuilder()
        cfg = make_config()
        secret = builder.build_auth_secret(cfg, "user:$2b$12$hash")

        assert secret["kind"] == "Secret"
        assert secret["type"] == "kubernetes.io/basic-auth"
        assert secret["metadata"]["name"] == cfg.auth_secret_name

    def test_htpasswd_encoded(self, make_config):
        builder = ManifestBuilder()
        content = "admin:$2b$12$somehash"
        secret = builder.build_auth_secret(make_config(), content)
        decoded = base64.b64decode(secret["data"]["auth"]).decode()
        assert decoded == content


class TestBuildDeployment:
    """Tests for ManifestBuilder.build_deployment."""

    def test_minimal(self, make_config):
        builder = ManifestBuilder()
        cfg = make_config()
        dep = builder.build_deployment(cfg)

        assert dep["apiVersion"] == "apps/v1"
        assert dep["kind"] == "Deployment"
        assert dep["metadata"]["name"] == cfg.deployment_name
        assert dep["spec"]["replicas"] == 1
        container = dep["spec"]["template"]["spec"]["containers"][0]
        assert container["name"] == "main-container"
        assert container["image"] == "nginx:latest"
        assert "env" not in container
        assert "args" not in container
        assert "command" not in container
        assert "volumeMounts" not in container
        assert "readinessProbe" not in container
        assert "initContainers" not in dep["spec"]["template"]["spec"]
        assert "volumes" not in dep["spec"]["template"]["spec"]

    def test_all_optional_fields(self, make_config):
        builder = ManifestBuilder()
        cfg = make_config(
            env=[{"name": "K", "value": "V"}],
            args=["--port", "8080"],
            command=["/bin/sh", "-c"],
            volume_mounts=[{"name": "vol", "mountPath": "/mnt"}],
            volumes=[{"name": "vol", "emptyDir": {}}],
            readiness_probe={"tcpSocket": {"port": 8080}},
        )
        dep = builder.build_deployment(cfg)
        container = dep["spec"]["template"]["spec"]["containers"][0]

        assert container["env"] == [{"name": "K", "value": "V"}]
        assert container["args"] == ["--port", "8080"]
        assert container["command"] == ["/bin/sh", "-c"]
        assert container["volumeMounts"] == [{"name": "vol", "mountPath": "/mnt"}]
        assert container["readinessProbe"] == {"tcpSocket": {"port": 8080}}
        assert dep["spec"]["template"]["spec"]["volumes"] == [
            {"name": "vol", "emptyDir": {}}
        ]

    def test_init_container(self, make_config):
        builder = ManifestBuilder()
        init = {"name": "init", "image": "busybox", "command": ["sh", "-c", "echo"]}
        cfg = make_config(init_container=init)
        dep = builder.build_deployment(cfg)

        assert dep["spec"]["template"]["spec"]["initContainers"] == [init]

    def test_env_secret_ref(self, make_config):
        builder = ManifestBuilder()
        env = [
            {"name": "PLAIN", "value": "hello"},
            {
                "name": "SECRET",
                "valueFrom": {
                    "secretKeyRef": {"name": "my-secret", "key": "password"}
                },
            },
        ]
        cfg = make_config(env=env)
        dep = builder.build_deployment(cfg)
        container = dep["spec"]["template"]["spec"]["containers"][0]
        assert container["env"] == env

    def test_labels_consistency(self, make_config):
        builder = ManifestBuilder()
        cfg = make_config(labels={"team": "bio"})
        dep = builder.build_deployment(cfg)

        meta_labels = dep["metadata"]["labels"]
        template_labels = dep["spec"]["template"]["metadata"]["labels"]
        selector = dep["spec"]["selector"]["matchLabels"]

        assert meta_labels["app"] == cfg.app_label
        assert meta_labels["team"] == "bio"
        assert template_labels["app"] == cfg.app_label
        assert template_labels["team"] == "bio"
        assert selector == {"app": cfg.app_label}

    def test_resources_with_request_fallback(self, make_config):
        builder = ManifestBuilder()
        cfg = make_config(cpu="2", memory="4Gi")
        dep = builder.build_deployment(cfg)
        resources = dep["spec"]["template"]["spec"]["containers"][0]["resources"]

        assert resources["limits"] == {"cpu": "2", "memory": "4Gi"}
        assert resources["requests"] == {"cpu": "2", "memory": "4Gi"}

    def test_resources_with_explicit_requests(self, make_config):
        builder = ManifestBuilder()
        cfg = make_config(cpu="2", memory="4Gi", request_cpu="500m", request_memory="1Gi")
        dep = builder.build_deployment(cfg)
        resources = dep["spec"]["template"]["spec"]["containers"][0]["resources"]

        assert resources["requests"] == {"cpu": "500m", "memory": "1Gi"}


class TestBuildService:
    """Tests for ManifestBuilder.build_service."""

    def test_with_ports(self, make_config):
        builder = ManifestBuilder()
        cfg = make_config(ports=[8080])
        svc = builder.build_service(cfg)

        assert svc["apiVersion"] == "v1"
        assert svc["kind"] == "Service"
        assert svc["metadata"]["name"] == cfg.service_name
        assert svc["spec"]["type"] == "ClusterIP"
        assert svc["spec"]["selector"] == {"app": cfg.app_label}
        assert svc["spec"]["ports"] == [
            {"port": 80, "targetPort": 8080, "protocol": "TCP"}
        ]

    def test_without_ports_returns_none(self, make_config):
        builder = ManifestBuilder()
        cfg = make_config(ports=[])
        assert builder.build_service(cfg) is None


class TestBuildIngress:
    """Tests for ManifestBuilder.build_ingress."""

    def test_with_url_and_host(self, make_config):
        builder = ManifestBuilder()
        cfg = make_config(
            url="https://example.com/proj/tool",
            host="example.com",
            tls_secret="tls-cert",
            ingress_annotations={"nginx.ingress.kubernetes.io/rewrite-target": "/"},
            ingress_class="nginx",
        )
        ing = builder.build_ingress(cfg)

        assert ing["apiVersion"] == "networking.k8s.io/v1"
        assert ing["kind"] == "Ingress"
        assert ing["metadata"]["name"] == cfg.ingress_name
        assert ing["spec"]["ingressClassName"] == "nginx"
        assert ing["spec"]["tls"][0]["hosts"] == ["example.com"]
        assert ing["spec"]["tls"][0]["secretName"] == "tls-cert"
        rule = ing["spec"]["rules"][0]
        assert rule["host"] == "example.com"
        path = rule["http"]["paths"][0]
        assert path["path"] == f"/{cfg.project_id}/{cfg.tool}"
        assert path["pathType"] == "Prefix"

    def test_without_url_returns_none(self, make_config):
        builder = ManifestBuilder()
        cfg = make_config(url="", host="example.com")
        assert builder.build_ingress(cfg) is None

    def test_without_host_returns_none(self, make_config):
        builder = ManifestBuilder()
        cfg = make_config(url="https://example.com", host="")
        assert builder.build_ingress(cfg) is None

    def test_without_ingress_class(self, make_config):
        builder = ManifestBuilder()
        cfg = make_config(url="https://example.com", host="example.com")
        ing = builder.build_ingress(cfg)
        assert "ingressClassName" not in ing["spec"]

    def test_annotations(self, make_config):
        builder = ManifestBuilder()
        annotations = {"key": "value"}
        cfg = make_config(
            url="https://example.com",
            host="example.com",
            ingress_annotations=annotations,
        )
        ing = builder.build_ingress(cfg)
        assert ing["metadata"]["annotations"] == annotations


class TestBuildAll:
    """Tests for ManifestBuilder.build_all."""

    def test_full_config(self, make_config, sample_s3_credentials):
        builder = ManifestBuilder()
        cfg = make_config(
            ports=[8080], url="https://example.com", host="example.com"
        )
        manifests = builder.build_all(cfg, sample_s3_credentials)

        assert len(manifests) == 4
        kinds = [m["kind"] for m in manifests]
        assert kinds == ["Secret", "Deployment", "Service", "Ingress"]

    def test_without_url(self, make_config, sample_s3_credentials):
        builder = ManifestBuilder()
        cfg = make_config(ports=[8080], url="")
        manifests = builder.build_all(cfg, sample_s3_credentials)

        assert len(manifests) == 3
        kinds = [m["kind"] for m in manifests]
        assert kinds == ["Secret", "Deployment", "Service"]

    def test_without_ports(self, make_config, sample_s3_credentials):
        builder = ManifestBuilder()
        cfg = make_config(ports=[])
        manifests = builder.build_all(cfg, sample_s3_credentials)

        assert len(manifests) == 2
        kinds = [m["kind"] for m in manifests]
        assert kinds == ["Secret", "Deployment"]

    def test_without_ports_and_url(self, make_config, sample_s3_credentials):
        builder = ManifestBuilder()
        cfg = make_config(ports=[], url="")
        manifests = builder.build_all(cfg, sample_s3_credentials)

        assert len(manifests) == 2
        kinds = [m["kind"] for m in manifests]
        assert kinds == ["Secret", "Deployment"]
