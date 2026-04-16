"""Tests für ManifestBuilder und DeploymentConfig."""

from __future__ import annotations

import base64

import pytest

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
        assert cfg.init_containers == []
        assert cfg.include_s3download is False
        assert cfg.bucket == ""
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
            auth_proxy_image="gk:latest",
            proxy_port=7777,
            labels={"team": "bio"},
            volume_mounts=[{"name": "data", "mountPath": "/data"}],
            volumes=[{"name": "data", "emptyDir": {}}],
            readiness_probe={"httpGet": {"path": "/health", "port": 8080}},
            init_containers=[{"name": "init", "image": "busybox"}],
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

        for key in ("s3_key", "s3_secret"):
            decoded = base64.b64decode(secret["data"][key]).decode()
            assert decoded == sample_s3_credentials[key]
        assert "s3_endpoint" not in secret["data"]
        assert "s3_files" not in secret["data"]


class TestBuildAuthSecret:
    """Tests for ManifestBuilder.build_auth_secret."""

    def test_structure(self, make_config):
        builder = ManifestBuilder()
        cfg = make_config()
        auth_data = {"secret_key": "abc123", "users": ["alice"], "owner": "alice", "groups": []}
        secret = builder.build_auth_secret(cfg, auth_data)

        assert secret["kind"] == "Secret"
        assert secret["metadata"]["name"] == cfg.auth_secret_name
        assert "auth-proxy.json" in secret["data"]

    def test_auth_proxy_json_encoded(self, make_config):
        builder = ManifestBuilder()
        auth_data = {"secret_key": "abc123", "users": ["alice"], "owner": "alice", "groups": []}
        secret = builder.build_auth_secret(make_config(), auth_data)
        decoded = base64.b64decode(secret["data"]["auth-proxy.json"]).decode()
        import json
        assert json.loads(decoded) == auth_data


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
        env_names = [e["name"] for e in container.get("env", [])]
        assert env_names == ["MAMPOK_BASE_PATH"]
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

        assert container["env"] == [{"name": "MAMPOK_BASE_PATH", "value": ""}, {"name": "K", "value": "V"}]
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
        cfg = make_config(init_containers=[init])
        dep = builder.build_deployment(cfg)

        assert dep["spec"]["template"]["spec"]["initContainers"] == [init]

    def test_s3download_init_container(self, make_config):
        from mampok.kubernetes.builder import (
            _FILEDIR_MOUNT_PATH,
            _FILEDIR_VOLUME_NAME,
            _S3DOWNLOAD_ARGS,
            _S3DOWNLOAD_COMMAND,
            _S3DOWNLOAD_IMAGE,
        )

        builder = ManifestBuilder()
        cfg = make_config(include_s3download=True, bucket="my-bucket")
        dep = builder.build_deployment(cfg)
        spec = dep["spec"]["template"]["spec"]

        assert "initContainers" in spec
        ic = spec["initContainers"][0]
        assert ic["name"] == "s3-download"
        assert ic["image"] == _S3DOWNLOAD_IMAGE
        assert ic["command"] == _S3DOWNLOAD_COMMAND
        assert ic["args"] == _S3DOWNLOAD_ARGS
        assert ic["volumeMounts"] == [{"name": _FILEDIR_VOLUME_NAME, "mountPath": _FILEDIR_MOUNT_PATH}]
        env_names = {e["name"] for e in ic["env"]}
        assert env_names == {
            "RCLONE_CONFIG_S3_TYPE",
            "RCLONE_CONFIG_S3_PROVIDER",
            "RCLONE_CONFIG_S3_ENDPOINT",
            "RCLONE_CONFIG_S3_ACCESS_KEY_ID",
            "RCLONE_CONFIG_S3_SECRET_ACCESS_KEY",
            "s3bucket",
        }
        s3bucket_env = next(e for e in ic["env"] if e["name"] == "s3bucket")
        assert s3bucket_env == {"name": "s3bucket", "value": "my-bucket"}

        volumes = spec.get("volumes", [])
        assert any(v["name"] == _FILEDIR_VOLUME_NAME for v in volumes)

    def test_s3download_not_added_when_disabled(self, make_config):
        builder = ManifestBuilder()
        cfg = make_config(include_s3download=False)
        dep = builder.build_deployment(cfg)
        assert "initContainers" not in dep["spec"]["template"]["spec"]

    def test_s3download_before_custom_init_containers(self, make_config):
        builder = ManifestBuilder()
        custom = {"tool": "myjob", "image": "myjob:1.0"}
        cfg = make_config(include_s3download=True, bucket="b", init_containers=[custom])
        dep = builder.build_deployment(cfg)
        ic_list = dep["spec"]["template"]["spec"]["initContainers"]
        assert ic_list[0]["name"] == "s3-download"
        assert ic_list[1]["name"] == "myjob"

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
        assert container["env"] == [{"name": "MAMPOK_BASE_PATH", "value": ""}] + env

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
            url="https://example.com/testproj/nginx",
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
        assert path["path"] == "/testproj/nginx"
        assert path["pathType"] == "Prefix"

    def test_no_tls_when_tls_secret_empty(self, make_config):
        builder = ManifestBuilder()
        cfg = make_config(url="https://example.com/testproj/nginx", host="example.com", tls_secret="")
        ing = builder.build_ingress(cfg)
        assert "tls" not in ing["spec"]

    def test_tls_when_tls_secret_set(self, make_config):
        builder = ManifestBuilder()
        cfg = make_config(url="https://example.com/testproj/nginx", host="example.com", tls_secret="my-tls-secret")
        ing = builder.build_ingress(cfg)
        assert ing["spec"]["tls"] == [{"hosts": ["example.com"], "secretName": "my-tls-secret"}]

    def test_ingress_path_from_url_with_suffix(self, make_config):
        builder = ManifestBuilder()
        cfg = make_config(
            url="https://example.com/testproj/nginx-ab12c",
            host="example.com",
        )
        ing = builder.build_ingress(cfg)
        path = ing["spec"]["rules"][0]["http"]["paths"][0]
        assert path["path"] == "/testproj/nginx-ab12c"

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


# ---------------------------------------------------------------------------
# Gatekeeper — DeploymentConfig-Validierung
# ---------------------------------------------------------------------------


class TestDeploymentConfigGatekeeper:
    """Tests für __post_init__-Validierung und neue auth-Felder."""

    def test_proxy_port_conflict_raises(self):
        with pytest.raises(ValueError, match="proxy_port"):
            DeploymentConfig(
                project_id="p",
                tool="t",
                image="img",
                namespace="ns",
                ports=[8080],
                auth=True,
                auth_proxy_image="gk:latest",
                proxy_port=8080,
            )

    def test_proxy_port_no_conflict_ok(self):
        cfg = DeploymentConfig(
            project_id="p",
            tool="t",
            image="img",
            namespace="ns",
            ports=[8080],
            auth=True,
            auth_proxy_image="gk:latest",
            proxy_port=9090,
        )
        assert cfg.proxy_port == 9090

    def test_auth_fields_defaults(self):
        cfg = DeploymentConfig(project_id="p", tool="t", image="img", namespace="ns")
        assert cfg.auth_proxy_image == ""
        assert cfg.proxy_port == 8080
        assert cfg.proxy_cpu == "100m"
        assert cfg.proxy_memory == "128Mi"
        assert cfg.auth_annotations == {}
        assert cfg.image_pull_secrets == []
        assert cfg.auth_config_mount_path == "/etc/config"


# ---------------------------------------------------------------------------
# Gatekeeper — build_deployment
# ---------------------------------------------------------------------------


class TestBuildDeploymentWithAuth:
    """Tests für Gatekeeper-Sidecar in build_deployment."""

    def test_two_containers_present(self, make_auth_config):
        builder = ManifestBuilder()
        cfg = make_auth_config()
        manifest = builder.build_deployment(cfg)
        containers = manifest["spec"]["template"]["spec"]["containers"]
        assert len(containers) == 2

    def test_gatekeeper_is_first_container(self, make_auth_config):
        builder = ManifestBuilder()
        cfg = make_auth_config()
        manifest = builder.build_deployment(cfg)
        assert manifest["spec"]["template"]["spec"]["containers"][0]["name"] == "gatekeeper"

    def test_gatekeeper_image(self, make_auth_config):
        builder = ManifestBuilder()
        cfg = make_auth_config()
        manifest = builder.build_deployment(cfg)
        gk = manifest["spec"]["template"]["spec"]["containers"][0]
        assert gk["image"] == "registry.example.com/gatekeeper:latest"

    def test_gatekeeper_port(self, make_auth_config):
        builder = ManifestBuilder()
        cfg = make_auth_config()
        manifest = builder.build_deployment(cfg)
        gk = manifest["spec"]["template"]["spec"]["containers"][0]
        assert gk["ports"] == [{"containerPort": 9090}]

    def test_env_reverse_port(self, make_auth_config):
        builder = ManifestBuilder()
        cfg = make_auth_config()
        manifest = builder.build_deployment(cfg)
        env = {e["name"]: e["value"] for e in manifest["spec"]["template"]["spec"]["containers"][0]["env"]}
        assert env["REVERSE_PORT"] == "8080"

    def test_env_redirect_host(self, make_auth_config):
        builder = ManifestBuilder()
        cfg = make_auth_config()
        manifest = builder.build_deployment(cfg)
        env = {e["name"]: e["value"] for e in manifest["spec"]["template"]["spec"]["containers"][0]["env"]}
        assert env["REDIRECT_HOST"] == "https://example.com"

    def test_env_redirect_url_default(self, make_auth_config):
        builder = ManifestBuilder()
        cfg = make_auth_config()
        manifest = builder.build_deployment(cfg)
        env = {e["name"]: e["value"] for e in manifest["spec"]["template"]["spec"]["containers"][0]["env"]}
        assert env["REDIRECT_URL"] == "/mynamespace/testproj/nginx/"

    def test_env_redirect_url_proxy_redirect_annotation(self, make_auth_config):
        builder = ManifestBuilder()
        cfg = make_auth_config(
            auth_annotations={"nginx.ingress.kubernetes.io/proxy-redirect-to": "https://example.com/"}
        )
        manifest = builder.build_deployment(cfg)
        env = {e["name"]: e["value"] for e in manifest["spec"]["template"]["spec"]["containers"][0]["env"]}
        assert env["REDIRECT_URL"] == "/"

    def test_env_project_id(self, make_auth_config):
        builder = ManifestBuilder()
        cfg = make_auth_config()
        manifest = builder.build_deployment(cfg)
        env = {e["name"]: e["value"] for e in manifest["spec"]["template"]["spec"]["containers"][0]["env"]}
        assert env["PROJECT_ID"] == "testproj"

    def test_gatekeeper_volume_mount(self, make_auth_config):
        builder = ManifestBuilder()
        cfg = make_auth_config()
        manifest = builder.build_deployment(cfg)
        gk = manifest["spec"]["template"]["spec"]["containers"][0]
        assert gk["volumeMounts"] == [
            {"name": "testproj-sc-nginx-auth-volume", "mountPath": "/etc/config"}
        ]

    def test_auth_volume_in_pod_spec(self, make_auth_config):
        builder = ManifestBuilder()
        cfg = make_auth_config()
        manifest = builder.build_deployment(cfg)
        volumes = manifest["spec"]["template"]["spec"]["volumes"]
        auth_vol = next((v for v in volumes if v["name"] == "testproj-sc-nginx-auth-volume"), None)
        assert auth_vol is not None
        assert auth_vol["secret"]["secretName"] == "testproj-sc-nginx-auth"

    def test_gatekeeper_resources(self, make_auth_config):
        builder = ManifestBuilder()
        cfg = make_auth_config()
        manifest = builder.build_deployment(cfg)
        gk = manifest["spec"]["template"]["spec"]["containers"][0]
        assert gk["resources"]["limits"] == {"cpu": "100m", "memory": "128Mi"}
        assert gk["resources"]["requests"] == {"cpu": "100m", "memory": "128Mi"}

    def test_image_pull_secrets_added(self, make_auth_config):
        builder = ManifestBuilder()
        cfg = make_auth_config(image_pull_secrets=["regcred"])
        manifest = builder.build_deployment(cfg)
        pod_spec = manifest["spec"]["template"]["spec"]
        assert pod_spec["imagePullSecrets"] == [{"name": "regcred"}]

    def test_image_pull_secrets_empty_not_added(self, make_auth_config):
        builder = ManifestBuilder()
        cfg = make_auth_config(image_pull_secrets=[])
        manifest = builder.build_deployment(cfg)
        pod_spec = manifest["spec"]["template"]["spec"]
        assert "imagePullSecrets" not in pod_spec

    def test_no_gatekeeper_without_auth(self, make_config):
        builder = ManifestBuilder()
        cfg = make_config(auth=False)
        manifest = builder.build_deployment(cfg)
        containers = manifest["spec"]["template"]["spec"]["containers"]
        assert len(containers) == 1
        assert containers[0]["name"] == "main-container"

    def test_auth_volumes_appended_to_existing(self, make_auth_config):
        builder = ManifestBuilder()
        cfg = make_auth_config(
            volumes=[{"name": "existing-vol", "emptyDir": {}}]
        )
        manifest = builder.build_deployment(cfg)
        volumes = manifest["spec"]["template"]["spec"]["volumes"]
        names = [v["name"] for v in volumes]
        assert "existing-vol" in names
        assert "testproj-sc-nginx-auth-volume" in names

    def test_auth_volumes_not_overwritten_by_cfg_volumes(self, make_auth_config):
        builder = ManifestBuilder()
        cfg = make_auth_config(
            volumes=[{"name": "cfg-vol", "emptyDir": {}}],
            init_containers=[{"tool": "my-init", "image": "busybox", "volume": {"name": "init-vol", "mountPath": "/init"}}],
        )
        manifest = builder.build_deployment(cfg)
        volumes = manifest["spec"]["template"]["spec"]["volumes"]
        names = [v["name"] for v in volumes]
        assert "cfg-vol" in names
        assert "init-vol" in names
        assert "testproj-sc-nginx-auth-volume" in names

    def test_empty_proxy_image_raises(self, make_config):
        builder = ManifestBuilder()
        cfg = make_config(auth=True, auth_proxy_image="", proxy_port=9090)
        with pytest.raises(ValueError, match="auth_proxy_image"):
            builder.build_deployment(cfg)

    def test_custom_mount_path(self, make_auth_config):
        builder = ManifestBuilder()
        cfg = make_auth_config(auth_config_mount_path="/custom/path")
        manifest = builder.build_deployment(cfg)
        gk = manifest["spec"]["template"]["spec"]["containers"][0]
        assert gk["volumeMounts"][0]["mountPath"] == "/custom/path"

    def test_gatekeeper_has_no_lifecycle(self, make_auth_config):
        """Gatekeeper must NOT have a preStop — termination handled via Mampok exec + SIGKILL."""
        builder = ManifestBuilder()
        cfg = make_auth_config()
        manifest = builder.build_deployment(cfg)
        gk = manifest["spec"]["template"]["spec"]["containers"][0]
        assert gk["name"] == "gatekeeper"
        assert "lifecycle" not in gk


# ---------------------------------------------------------------------------
# Gatekeeper — build_service
# ---------------------------------------------------------------------------


class TestBuildServiceWithAuth:
    """Tests für zwei Named Ports bei auth=True."""

    def test_two_named_ports(self, make_auth_config):
        builder = ManifestBuilder()
        cfg = make_auth_config()
        manifest = builder.build_service(cfg)
        ports = manifest["spec"]["ports"]
        assert len(ports) == 2
        names = [p["name"] for p in ports]
        assert "main-app-port" in names
        assert "gatekeeper-port" in names

    def test_main_app_port_values(self, make_auth_config):
        builder = ManifestBuilder()
        cfg = make_auth_config()
        manifest = builder.build_service(cfg)
        main_port = next(p for p in manifest["spec"]["ports"] if p["name"] == "main-app-port")
        assert main_port["port"] == 8080
        assert main_port["targetPort"] == 8080

    def test_gatekeeper_port_values(self, make_auth_config):
        builder = ManifestBuilder()
        cfg = make_auth_config()
        manifest = builder.build_service(cfg)
        gk_port = next(p for p in manifest["spec"]["ports"] if p["name"] == "gatekeeper-port")
        assert gk_port["port"] == 9090
        assert gk_port["targetPort"] == 9090

    def test_no_auth_single_port_unchanged(self, make_config):
        builder = ManifestBuilder()
        cfg = make_config(auth=False)
        manifest = builder.build_service(cfg)
        ports = manifest["spec"]["ports"]
        assert len(ports) == 1
        assert ports[0] == {"port": 80, "targetPort": 8080, "protocol": "TCP"}


# ---------------------------------------------------------------------------
# Gatekeeper — build_ingress
# ---------------------------------------------------------------------------


class TestBuildIngressWithAuth:
    """Tests für Ingress-Routing und Annotation-Merge bei auth=True."""

    def test_auth_backend_named_port(self, make_auth_config):
        builder = ManifestBuilder()
        cfg = make_auth_config()
        manifest = builder.build_ingress(cfg)
        path = manifest["spec"]["rules"][0]["http"]["paths"][0]
        assert path["backend"]["service"]["port"] == {"name": "gatekeeper-port"}

    def test_no_auth_backend_number_80(self, make_config):
        builder = ManifestBuilder()
        cfg = make_config(url="https://example.com/p/t", host="example.com")
        manifest = builder.build_ingress(cfg)
        path = manifest["spec"]["rules"][0]["http"]["paths"][0]
        assert path["backend"]["service"]["port"] == {"number": 80}

    def test_auth_annotations_merged(self, make_auth_config):
        builder = ManifestBuilder()
        cfg = make_auth_config(
            auth_annotations={"nginx.ingress.kubernetes.io/auth-type": "basic"}
        )
        manifest = builder.build_ingress(cfg)
        assert manifest["metadata"]["annotations"]["nginx.ingress.kubernetes.io/auth-type"] == "basic"

    def test_base_and_auth_annotations_combined(self, make_auth_config):
        builder = ManifestBuilder()
        cfg = make_auth_config(
            ingress_annotations={"kubernetes.io/ingress.class": "nginx"},
            auth_annotations={"nginx.ingress.kubernetes.io/auth-type": "basic"},
        )
        manifest = builder.build_ingress(cfg)
        annotations = manifest["metadata"]["annotations"]
        assert annotations["kubernetes.io/ingress.class"] == "nginx"
        assert annotations["nginx.ingress.kubernetes.io/auth-type"] == "basic"

    def test_no_auth_no_extra_annotations(self, make_config):
        builder = ManifestBuilder()
        cfg = make_config(
            url="https://example.com/p/t",
            host="example.com",
            ingress_annotations={"kubernetes.io/ingress.class": "nginx"},
            auth_annotations={"nginx.ingress.kubernetes.io/auth-type": "basic"},
        )
        manifest = builder.build_ingress(cfg)
        annotations = manifest["metadata"]["annotations"]
        assert "nginx.ingress.kubernetes.io/auth-type" not in annotations
        assert annotations["kubernetes.io/ingress.class"] == "nginx"


# ---------------------------------------------------------------------------
# Container Data — Sidecar, emptyDir Volumes, terminationGracePeriodSeconds
# ---------------------------------------------------------------------------


class TestBuildDeploymentContainerData:
    """Tests für container_data Sidecar-Sync-Feature."""

    def test_sidecar_added_when_container_data_paths_set(self, make_config):
        builder = ManifestBuilder()
        cfg = make_config(
            container_data_paths=["/app/.cellxgene/annotations/"],
            bucket="my-bucket",
            endpoint="https://s3.example.com",
        )
        dep = builder.build_deployment(cfg)
        containers = dep["spec"]["template"]["spec"]["containers"]
        sidecar_names = [c["name"] for c in containers]
        assert "mampok-s3-sync" in sidecar_names

    def test_no_sidecar_without_container_data_paths(self, make_config):
        builder = ManifestBuilder()
        cfg = make_config()
        dep = builder.build_deployment(cfg)
        containers = dep["spec"]["template"]["spec"]["containers"]
        assert all(c["name"] != "mampok-s3-sync" for c in containers)

    def test_emptydir_volume_created_for_each_path(self, make_config):
        builder = ManifestBuilder()
        cfg = make_config(
            container_data_paths=["/app/annotations/", "/app/results/"],
            bucket="b",
            endpoint="https://s3.example.com",
        )
        dep = builder.build_deployment(cfg)
        volumes = dep["spec"]["template"]["spec"]["volumes"]
        vol_names = [v["name"] for v in volumes]
        assert "mampok-sync-app-annotations" in vol_names
        assert "mampok-sync-app-results" in vol_names

    def test_main_container_mounts_at_native_path(self, make_config):
        builder = ManifestBuilder()
        cfg = make_config(
            container_data_paths=["/app/annotations/"],
            bucket="b",
            endpoint="https://s3.example.com",
        )
        dep = builder.build_deployment(cfg)
        main = dep["spec"]["template"]["spec"]["containers"][0]
        mounts = {m["mountPath"]: m["name"] for m in main.get("volumeMounts", [])}
        assert "/app/annotations" in mounts
        assert mounts["/app/annotations"] == "mampok-sync-app-annotations"

    def test_sidecar_mounts_at_sync_subpath(self, make_config):
        builder = ManifestBuilder()
        cfg = make_config(
            container_data_paths=["/app/annotations/"],
            bucket="b",
            endpoint="https://s3.example.com",
        )
        dep = builder.build_deployment(cfg)
        sidecar = next(c for c in dep["spec"]["template"]["spec"]["containers"] if c["name"] == "mampok-s3-sync")
        mounts = {m["mountPath"]: m["name"] for m in sidecar.get("volumeMounts", [])}
        assert "/sync/app-annotations" in mounts

    def test_sidecar_image_is_pinned(self, make_config):
        """Sidecar image must be pinned to a major version, not 'latest'."""
        builder = ManifestBuilder()
        cfg = make_config(
            container_data_paths=["/app/annotations/"],
            bucket="b",
            endpoint="https://s3.example.com",
        )
        dep = builder.build_deployment(cfg)
        sidecar = next(c for c in dep["spec"]["template"]["spec"]["containers"] if c["name"] == "mampok-s3-sync")
        assert ":" in sidecar["image"]
        assert sidecar["image"].startswith("rclone/rclone:")

    def test_no_termination_grace_period_without_container_data(self, make_config):
        builder = ManifestBuilder()
        cfg = make_config()
        dep = builder.build_deployment(cfg)
        assert "terminationGracePeriodSeconds" not in dep["spec"]["template"]["spec"]

    def test_restore_init_container_added_when_restore_on_deploy(self, make_config):
        builder = ManifestBuilder()
        cfg = make_config(
            include_s3download=True,
            container_data_paths=["/app/annotations/"],
            container_data_restore=True,
            bucket="my-bucket",
            endpoint="https://s3.example.com",
        )
        dep = builder.build_deployment(cfg)
        init_containers = dep["spec"]["template"]["spec"]["initContainers"]
        init_names = [ic["name"] for ic in init_containers]
        assert "s3-restore" in init_names

    def test_no_restore_init_container_without_restore_flag(self, make_config):
        builder = ManifestBuilder()
        cfg = make_config(
            include_s3download=True,
            container_data_paths=["/app/annotations/"],
            container_data_restore=False,
            bucket="b",
            endpoint="https://s3.example.com",
        )
        dep = builder.build_deployment(cfg)
        init_containers = dep["spec"]["template"]["spec"]["initContainers"]
        init_names = [ic["name"] for ic in init_containers]
        assert "s3-restore" not in init_names

    def test_sidecar_sync_interval_env_var(self, make_config):
        builder = ManifestBuilder()
        cfg = make_config(
            container_data_paths=["/app/annotations/"],
            container_data_sync_interval=120,
            bucket="b",
            endpoint="https://s3.example.com",
        )
        dep = builder.build_deployment(cfg)
        sidecar = next(c for c in dep["spec"]["template"]["spec"]["containers"] if c["name"] == "mampok-s3-sync")
        env = {e["name"]: e.get("value") for e in sidecar["env"]}
        assert env["MAMPOK_SYNC_INTERVAL"] == "120"

    def test_sidecar_sync_cmd_uses_rclone_bisync(self, make_config):
        builder = ManifestBuilder()
        cfg = make_config(
            container_data_paths=["/app/annotations/"],
            bucket="b",
            endpoint="https://s3.example.com",
        )
        dep = builder.build_deployment(cfg)
        sidecar = next(c for c in dep["spec"]["template"]["spec"]["containers"] if c["name"] == "mampok-s3-sync")
        sync_script = sidecar["args"][0]
        assert "rclone bisync" in sync_script
        assert "--workdir /tmp/bisync-state/" in sync_script
        assert "--conflict-resolve newer" in sync_script
        # Explicit --resync on startup initialises .lst files without needing prior state
        assert "mkdir -p /tmp/bisync-state" in sync_script
        resync_positions = [i for i in range(len(sync_script)) if sync_script[i:].startswith("--resync")]
        assert len(resync_positions) == 2, "expect --resync on startup and as || fallback"
        # || fallback --resync must come after the while-loop starts
        assert sync_script.index("||") > sync_script.index("while true")

    def test_sidecar_sync_cmd_has_loop_with_sleep(self, make_config):
        builder = ManifestBuilder()
        cfg = make_config(
            container_data_paths=["/app/annotations/"],
            bucket="b",
            endpoint="https://s3.example.com",
        )
        dep = builder.build_deployment(cfg)
        sidecar = next(c for c in dep["spec"]["template"]["spec"]["containers"] if c["name"] == "mampok-s3-sync")
        sync_script = sidecar["args"][0]
        assert "while true" in sync_script
        assert "sleep $MAMPOK_SYNC_INTERVAL" in sync_script

    def test_main_container_has_no_lifecycle(self, make_config):
        """Main container must NOT have preStop — sync is done by Mampok before deletion."""
        builder = ManifestBuilder()
        cfg = make_config(
            container_data_paths=["/app/annotations/"],
            bucket="b",
            endpoint="https://s3.example.com",
        )
        dep = builder.build_deployment(cfg)
        main = dep["spec"]["template"]["spec"]["containers"][0]
        assert main["name"] == "main-container"
        assert "lifecycle" not in main

    def test_sidecar_has_no_lifecycle(self, make_config):
        """Sidecar must NOT have a preStop — no final sync hook needed."""
        builder = ManifestBuilder()
        cfg = make_config(
            container_data_paths=["/app/annotations/"],
            bucket="b",
            endpoint="https://s3.example.com",
        )
        dep = builder.build_deployment(cfg)
        sidecar = next(
            c for c in dep["spec"]["template"]["spec"]["containers"]
            if c["name"] == "mampok-s3-sync"
        )
        assert "lifecycle" not in sidecar

    def test_no_termination_grace_period_override(self, make_config):
        """terminationGracePeriodSeconds must NOT be set — rely on K8s default (30s)."""
        builder = ManifestBuilder()
        cfg = make_config(
            container_data_paths=["/app/annotations/"],
            bucket="b",
            endpoint="https://s3.example.com",
        )
        spec = builder.build_deployment(cfg)["spec"]["template"]["spec"]
        assert "terminationGracePeriodSeconds" not in spec

    def test_normal_sidecar_syncs_to_container_data_prefix(self, make_config):
        """Normaler Mamplan: Sidecar-Command referenziert container_data/ Präfix."""
        builder = ManifestBuilder()
        cfg = make_config(
            container_data_paths=["/app/annotations/"],
            bucket="b",
            endpoint="https://s3.example.com",
        )
        dep = builder.build_deployment(cfg)
        sidecar = next(c for c in dep["spec"]["template"]["spec"]["containers"] if c["name"] == "mampok-s3-sync")
        sync_script = sidecar["args"][0]
        assert "S3:$s3bucket/container_data/" in sync_script
        assert "/sync/ " in sync_script or sync_script.count("/sync/") > 0

    def test_normal_restore_uses_container_data_prefix(self, make_config):
        """Normaler Mamplan: Restore-Init-Container lädt aus container_data/."""
        builder = ManifestBuilder()
        cfg = make_config(
            include_s3download=True,
            container_data_paths=["/app/annotations/"],
            container_data_restore=True,
            bucket="b",
            endpoint="https://s3.example.com",
        )
        dep = builder.build_deployment(cfg)
        restore = next(ic for ic in dep["spec"]["template"]["spec"]["initContainers"] if ic["name"] == "s3-restore")
        restore_script = restore["args"][0]
        assert "S3:$(s3bucket)/container_data/" in restore_script
        assert "container_data" in restore_script


class TestNoAwsEnvInMainContainer:
    """Main-Container darf keine AWS_*-Credentials enthalten (FUSE ist obsolet)."""

    def test_no_aws_access_key_in_env(self, make_config):
        builder = ManifestBuilder()
        cfg = make_config()
        dep = builder.build_deployment(cfg)
        main_env = dep["spec"]["template"]["spec"]["containers"][0].get("env", [])
        env_names = [e["name"] for e in main_env]
        assert "AWS_ACCESS_KEY_ID" not in env_names

    def test_no_aws_secret_key_in_env(self, make_config):
        builder = ManifestBuilder()
        cfg = make_config()
        dep = builder.build_deployment(cfg)
        main_env = dep["spec"]["template"]["spec"]["containers"][0].get("env", [])
        env_names = [e["name"] for e in main_env]
        assert "AWS_SECRET_ACCESS_KEY" not in env_names

    def test_no_aws_endpoint_url_in_env(self, make_config):
        builder = ManifestBuilder()
        cfg = make_config()
        dep = builder.build_deployment(cfg)
        main_env = dep["spec"]["template"]["spec"]["containers"][0].get("env", [])
        env_names = [e["name"] for e in main_env]
        assert "AWS_ENDPOINT_URL" not in env_names


class TestFullBucketOverwrite:
    """Tests für container_data_s3_root=True (full_bucket_overwrite im Mamplate)."""

    def _make_fbo_cfg(self, make_config, mount_path="/home/appuser/"):
        return make_config(
            container_data_paths=[mount_path],
            container_data_restore=True,
            container_data_s3_root=True,
            bucket="user-bucket",
            endpoint="https://s3.example.com",
        )

    def test_sidecar_syncs_to_bucket_root(self, make_config):
        """full_bucket_overwrite: Sidecar synct direkt zum Bucket-Root, kein container_data/."""
        builder = ManifestBuilder()
        cfg = self._make_fbo_cfg(make_config)
        dep = builder.build_deployment(cfg)
        sidecar = next(c for c in dep["spec"]["template"]["spec"]["containers"] if c["name"] == "mampok-s3-sync")
        sync_script = sidecar["args"][0]
        assert "S3:$s3bucket/ " in sync_script or sync_script.endswith("S3:$s3bucket/")
        assert "container_data" not in sync_script

    def test_sidecar_uses_subpath_not_sync_root(self, make_config):
        """full_bucket_overwrite: Sidecar-Command verwendet /sync/{subpath}/, nicht /sync/."""
        builder = ManifestBuilder()
        cfg = self._make_fbo_cfg(make_config, "/home/appuser/")
        dep = builder.build_deployment(cfg)
        sidecar = next(c for c in dep["spec"]["template"]["spec"]["containers"] if c["name"] == "mampok-s3-sync")
        sync_script = sidecar["args"][0]
        assert "/sync/home-appuser/" in sync_script

    def test_restore_copies_from_bucket_root(self, make_config):
        """full_bucket_overwrite: Restore-Init-Container lädt ganzen Bucket (kein container_data/)."""
        builder = ManifestBuilder()
        cfg = self._make_fbo_cfg(make_config)
        dep = builder.build_deployment(cfg)
        init_containers = dep["spec"]["template"]["spec"].get("initContainers", [])
        restore = next((ic for ic in init_containers if ic["name"] == "s3-restore"), None)
        assert restore is not None, "s3-restore muss vorhanden sein"
        restore_script = restore["args"][0]
        assert "S3:$(s3bucket)/ " in restore_script or restore_script.count("S3:$(s3bucket)/") > 0
        assert "container_data" not in restore_script

    def test_restore_targets_mount_path(self, make_config):
        """full_bucket_overwrite: Restore-Ziel ist der Mount-Pfad aus full_bucket_overwrite."""
        builder = ManifestBuilder()
        cfg = self._make_fbo_cfg(make_config, "/home/appuser/")
        dep = builder.build_deployment(cfg)
        init_containers = dep["spec"]["template"]["spec"].get("initContainers", [])
        restore = next(ic for ic in init_containers if ic["name"] == "s3-restore")
        restore_script = restore["args"][0]
        assert "/home/appuser/" in restore_script

    def test_sidecar_bisync_still_bidirectional(self, make_config):
        """full_bucket_overwrite ändert den Pfad, aber nicht die Bidirektionalität."""
        builder = ManifestBuilder()
        cfg = self._make_fbo_cfg(make_config)
        dep = builder.build_deployment(cfg)
        sidecar = next(c for c in dep["spec"]["template"]["spec"]["containers"] if c["name"] == "mampok-s3-sync")
        sync_script = sidecar["args"][0]
        assert "rclone bisync" in sync_script
        assert "--conflict-resolve newer" in sync_script
