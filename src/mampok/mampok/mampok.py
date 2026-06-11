"""Mampok — central orchestrator for Kubernetes deployments."""

from __future__ import annotations

import importlib.resources
import json
import logging
import os
import secrets
import string
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from queue import Queue
from typing import Iterator

import jwt

from mampok.config.config import MampokConfig
from mampok.kubernetes.builder import ManifestBuilder
from mampok.kubernetes.config import DeploymentConfig
from mampok.kubernetes.manager import DeploymentManager
from mampok.mamplan.mamplan import Mamplan
from mampok.mamplan.mamplate import Mamplate
from mampok.s3.s3 import S3

logger = logging.getLogger(__name__)


def _load_container_data_defaults() -> dict:
    schema_ref = (
        importlib.resources.files("mampok.mamplan")
        .joinpath("schemas")
        .joinpath("mamplate_schema.json")
    )
    with schema_ref.open("r", encoding="utf-8") as f:
        schema = json.load(f)
    cd_props = schema["definitions"]["MamplateProperties"]["properties"]["container_data"]["properties"]
    return {k: v["default"] for k, v in cd_props.items() if "default" in v}


_CONTAINER_DATA_DEFAULTS = _load_container_data_defaults()


class Mampok:
    """Central orchestrator — connects all Mampok modules.

    Instantiated by the interfaces (CLI, API) and delegates operations
    to the responsible modules (DeploymentManager, S3, Mamplan, Mamplate).
    MampokConfig is not stored, but passed to individual methods.

    Args:
        mamplan: Loaded and validated Mamplan instance.
        mamplate: Matching Mamplate for the tool in the Mamplan.
        kube: Configured DeploymentManager for the target cluster.
        s3: Configured S3 client for the project bucket.
    """

    def __init__(
        self,
        mamplan: Mamplan,
        mamplate: Mamplate,
        kube: DeploymentManager,
        s3: S3,
        init_mamplates: list[Mamplate] | None = None,
    ) -> None:
        """Initialize Mampok.

        Args:
            mamplan: Loaded and validated Mamplan instance.
            mamplate: Matching Mamplate for the tool in the Mamplan.
            kube: Configured DeploymentManager for the target cluster.
            s3: Configured S3 client for the project bucket.
            init_mamplates: Optional list of Mamplates for custom init containers.
        """
        self.mamplan = mamplan
        self.mamplate = mamplate
        self.kube = kube
        self.s3 = s3
        self.init_mamplates: list[Mamplate] = init_mamplates or []

    @property
    def is_expired(self) -> bool:
        """True if deployment.lifetime has passed AND deployment.status=True.

        Returns:
            True if the deployment is active and expired.
        """
        return self.mamplan.is_expired

    def deploy(self, config: MampokConfig, timeout: int = 900, cleanup: bool = True, reupload: bool = False) -> Iterator[dict]:
        """Deploy the project to Kubernetes.

        Steps:
        1. Derive DeploymentConfig from Mamplan + Mamplate + ClusterConfig
        2. Create S3 bucket
        3. Upload files (only if not already present with matching size)
        4. Create Kubernetes resources
        5. Wait until all pods are ready
        6. Update Mamplan (status=True, url)

        If an error occurs during steps 4 or 5, already created K8s resources
        are automatically cleaned up (if cleanup=True).

        Args:
            config: Configuration with cluster and S3 credentials.
            timeout: Maximum wait time in seconds until pods are ready.
            cleanup: If True, K8s resources are automatically deleted on failure.
            reupload: If True, all files are re-uploaded (size comparison is skipped).

        Yields:
            Progress dicts for each step of the deployment:
            - {"stage": "init", "status": "done", "project_id": str}
            - {"stage": "s3_bucket", "status": "created"|"exists"}
            - {"stage": "s3_upload", "status": "starting", "file": str, "size_bytes": int}
            - {"stage": "s3_upload", "status": "progress", "file": str, "transferred_pct": int, "size_bytes": int}
            - {"stage": "s3_upload", "status": "done", "file": str, "size_bytes": int}
            - {"stage": "s3_upload", "status": "complete", "total_files": int, "total_bytes": int}
            - {"stage": "k8s_validate", "status": "done", "count": int}
            - {"stage": "k8s_apply", "status": "done", "resource": str}
            - {"stage": "k8s_init", "status": "running"}  (only with init containers)
            - {"stage": "init_container_progress", "container": str, "status": "progress"|"done",
               "transferred_pct": int, ...rclone_stats}  (only with init containers using --stats)
            - {"stage": "k8s_ready", "status": "running", "ready_replicas": int}
            - {"stage": "k8s_pod_warning", "reason": str, "container": str,
               "restart_count": int, "message": str, "fatal": bool}  (on pod errors)
            - {"stage": "k8s_cleanup", "status": "done", "project_id": str}  (only on error+cleanup)
            - {"stage": "done", "selfservice": {"url": str, "token_url": str|None,
               "project_id": str, "auth": bool}}
        """
        cfg = self._build_deployment_config(config)
        project_id = cfg.project_id
        logger.debug("deploy: project_id=%s, namespace=%s, image=%s, replicas=%s, auth=%s, url=%s",
                     cfg.project_id, cfg.namespace, cfg.image, cfg.replicas, cfg.auth, cfg.url)

        # Create auth secret BEFORE kube.deploy() — pod start fails without it
        token_url: str | None = None
        if cfg.auth:
            token_url = self.update_auth_secret(config)

        step: dict = {"stage": "init", "status": "done", "project_id": project_id}
        logger.debug("step: %s", step)
        yield step

        # S3 bucket
        bucket_existed = self.s3.bucket_exists()
        self.s3.create_bucket()
        self.s3.set_lifecycle_policy()
        step = {"stage": "s3_bucket", "status": "exists" if bucket_existed else "created"}
        logger.debug("step: %s", step)
        yield step

        # S3 upload per file — stored under analysis_data/ prefix
        mamplan_dir = self.mamplan.source_path.parent if self.mamplan.source_path else Path.cwd()
        files = self.mamplan.data["project"].get("files", [])
        total_size_bytes = 0
        for file_path in files:
            local = Path(file_path)
            if not local.is_absolute():
                local = mamplan_dir / local
            key = f"analysis_data/{local.name}"
            file_size = os.path.getsize(local)
            total_size_bytes += file_size
            step = {"stage": "s3_upload", "status": "starting", "file": key, "size_bytes": file_size}
            logger.debug("step: %s", step)
            yield step
            if reupload or not self.s3.compare_size(key, local):
                yield from self._upload_with_progress(local, key, file_size)
            step = {"stage": "s3_upload", "status": "done", "file": key, "size_bytes": file_size}
            logger.debug("step: %s", step)
            yield step
        step = {"stage": "s3_upload", "status": "complete", "total_files": len(files), "total_bytes": total_size_bytes}
        logger.debug("step: %s", step)
        yield step

        # Container data sync setup
        container_data = cfg.container_data_paths
        if container_data:
            step = {"stage": "s3_sync_setup", "status": "done", "paths": container_data}
            logger.debug("step: %s", step)
            yield step

        # K8s deploy
        s3_credentials = {
            "s3_key": config.s3.access_key,
            "s3_secret": config.s3.secret_key,
        }
        logger.debug("s3_credentials: key=%s, secret=***", s3_credentials["s3_key"])
        k8s_started = False
        try:
            for step in self.kube.deploy(cfg, s3_credentials):
                k8s_started = True
                logger.debug("step: %s", step)
                yield step

            # Readiness watch
            for step in self.kube.wait_for_ready(cfg, timeout=timeout):
                logger.debug("step: %s", step)
                yield step
        except Exception:
            if cleanup and k8s_started:
                logger.warning("deploy failed, cleaning up K8s resources: %s", cfg.project_id)
                for _ in self.kube.delete(cfg):
                    pass
                step = {"stage": "k8s_cleanup", "status": "done", "project_id": cfg.project_id}
                logger.debug("step: %s", step)
                yield step
            raise

        # Update mamplan — reset lifetime to now + config.lifetime_days (lease renewal)
        new_lifetime = datetime.now(timezone.utc) + timedelta(days=config.lifetime_days)
        edit_kwargs: dict = {
            "deployment__status": True,
            "deployment__url": cfg.url,
            "deployment__lifetime": new_lifetime.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "deployment__bucket": self.s3.bucket,
        }
        if isinstance(self.mamplan, Mamplan):
            edit_kwargs["project__project_size"] = total_size_bytes // 1024
        self.mamplan.edit(**edit_kwargs)
        step = {"stage": "done", "selfservice": {"url": cfg.url, "token_url": token_url, "project_id": project_id, "auth": cfg.auth}}
        logger.debug("step: %s", step)
        yield step

    def upload(self, reupload: bool = False) -> Iterator[dict]:
        """Upload project files to S3 without starting a Kubernetes deployment.

        Creates the bucket if it does not exist, uploads all files listed in
        project.files[] to analysis_data/, and updates deployment.bucket in the
        mamplan file so download endpoints can locate the data.

        This is used during migration (--full-s3-restore / --include-downloadables)
        and whenever S3 data needs to be (re-)populated without a full deploy.

        Args:
            reupload: If True, re-upload all files even if they already exist in S3
                      with the correct size.

        Yields:
            Progress dicts — same schema as the S3 stages in deploy():
            - {"stage": "init", "status": "done", "project_id": str}
            - {"stage": "s3_bucket", "status": "created"|"exists"}
            - {"stage": "s3_upload", "status": "starting"|"progress"|"done", ...}
            - {"stage": "s3_upload", "status": "complete", "total_files": int, "total_bytes": int}
            - {"stage": "done", "project_id": str, "bucket": str}
        """
        project_id = self.mamplan.data["project"]["project_id"]
        logger.debug("upload: project_id=%s, bucket=%s", project_id, self.s3.bucket)

        step: dict = {"stage": "init", "status": "done", "project_id": project_id}
        logger.debug("step: %s", step)
        yield step

        # Create bucket if needed
        bucket_existed = self.s3.bucket_exists()
        self.s3.create_bucket()
        self.s3.set_lifecycle_policy()
        step = {"stage": "s3_bucket", "status": "exists" if bucket_existed else "created"}
        logger.debug("step: %s", step)
        yield step

        # Upload files to analysis_data/
        mamplan_dir = self.mamplan.source_path.parent if self.mamplan.source_path else Path.cwd()
        files = self.mamplan.data["project"].get("files", [])
        total_size_bytes = 0
        for file_path in files:
            local = Path(file_path)
            if not local.is_absolute():
                local = mamplan_dir / local
            key = f"analysis_data/{local.name}"
            file_size = os.path.getsize(local)
            total_size_bytes += file_size
            step = {"stage": "s3_upload", "status": "starting", "file": key, "size_bytes": file_size}
            logger.debug("step: %s", step)
            yield step
            if reupload or not self.s3.compare_size(key, local):
                yield from self._upload_with_progress(local, key, file_size)
            step = {"stage": "s3_upload", "status": "done", "file": key, "size_bytes": file_size}
            logger.debug("step: %s", step)
            yield step
        step = {"stage": "s3_upload", "status": "complete", "total_files": len(files), "total_bytes": total_size_bytes}
        logger.debug("step: %s", step)
        yield step

        # Update deployment.bucket so download endpoints can locate the data
        if isinstance(self.mamplan, Mamplan):
            self.mamplan.edit(
                deployment__bucket=self.s3.bucket,
                project__project_size=total_size_bytes // 1024,
            )

        step = {"stage": "done", "project_id": project_id, "bucket": self.s3.bucket}
        logger.debug("step: %s", step)
        yield step

    def _upload_with_progress(self, local: Path, key: str, file_size: int) -> Iterator[dict]:
        """Run S3 upload in a daemon thread and yield progress events per percent step.

        Because boto3's callback runs synchronously in the upload thread, yield cannot
        be called from within it. The upload runs in a daemon thread; progress updates
        are passed via a Queue to the generator thread. Exceptions from the upload
        thread are propagated via the Queue and re-raised in the main thread so that
        the normal error flow in deploy() is preserved.

        Args:
            local: Path to the local file.
            key: S3 object key (target name in the bucket).
            file_size: File size in bytes (for percentage calculation).

        Yields:
            {"stage": "s3_upload", "status": "progress", "file": str,
             "transferred_pct": int, "size_bytes": int}
        """
        q: Queue = Queue()
        transferred = [0]
        last_pct = [-1]

        def callback(bytes_amount: int) -> None:
            transferred[0] += bytes_amount
            pct = min(100, int(transferred[0] / file_size * 100)) if file_size > 0 else 100
            if pct != last_pct[0]:
                last_pct[0] = pct
                q.put(pct)

        def run() -> None:
            try:
                self.s3.upload(local, key, callback=callback)
                q.put(None)  # Sentinel: upload complete
            except Exception as e:
                q.put(e)  # propagate exception to main thread

        t = threading.Thread(target=run, daemon=True)
        t.start()
        for item in iter(q.get, None):
            if isinstance(item, Exception):
                raise item
            yield {"stage": "s3_upload", "status": "progress", "file": key,
                   "transferred_pct": item, "size_bytes": file_size}
        t.join()

    def stop(self, config: MampokConfig) -> Iterator[dict]:
        """Stop the deployment — removes K8s resources, S3 bucket is preserved.

        Yields progress dicts (analogous to deploy()). Caller must iterate to drive execution.
        Mamplan status is updated only after the generator is fully consumed.

        Args:
            config: Configuration with cluster credentials.

        Yields:
            Progress dicts from DeploymentManager.delete().

        Raises:
            RuntimeError: If K8s resource deletion fails. Mamplan status is NOT
                          updated in this case to preserve accurate state reflection.
        """
        cfg = self._build_deployment_config(config)
        logger.debug("stop: project_id=%s, namespace=%s", cfg.project_id, cfg.namespace)
        try:
            yield from self.kube.delete(cfg)
        except Exception:
            logger.error("stop failed for '%s' — mamplan status NOT updated", cfg.project_id)
            raise
        self.mamplan.edit(deployment__status=False)

    def download(self, output_dir: Path) -> Iterator[dict]:
        """Download container_data from the S3 bucket to a local directory.

        Downloads only container_data/ from the project bucket.
        Local structure: output_dir/<project_id>/container_data/...

        Args:
            output_dir: Target directory. Subdirectory <project_id> is created.

        Yields:
            - {"stage": "s3_download", "status": "starting", "project_id": str, "total": int}
            - {"stage": "s3_download", "status": "done", "key": str, "local_path": str}
            - {"stage": "s3_download", "status": "complete", "total": int, "dest": str}
        """
        project_id = self.mamplan.data["project"]["project_id"]
        dest = output_dir / project_id
        logger.debug("download: project_id=%s, dest=%s", project_id, dest)
        keys = self.s3.list_objects(prefix="container_data/")
        yield {"stage": "s3_download", "status": "starting", "project_id": project_id, "total": len(keys)}
        for key in keys:
            local_path = dest / key
            local_path.parent.mkdir(parents=True, exist_ok=True)
            self.s3.download_to_local(key, local_path)
            yield {"stage": "s3_download", "status": "done", "key": key, "local_path": str(local_path)}
        yield {"stage": "s3_download", "status": "complete", "total": len(keys), "dest": str(dest)}

    def check_status(self, config: MampokConfig) -> dict:
        """Compare the local Mamplan status with the actual K8s state.

        Args:
            config: Configuration with cluster credentials.

        Returns:
            Dict mit project_id, expected_active, actually_deployed, healthy.
        """
        cfg = self._build_deployment_config(config)
        expected_active = self.mamplan.data["deployment"]["status"]
        actually_deployed = self.kube.deployment_exists(cfg)
        result = {
            "project_id": cfg.project_id,
            "expected_active": expected_active,
            "actually_deployed": actually_deployed,
            "healthy": expected_active == actually_deployed,
        }
        logger.debug("check_status: %s", result)
        return result

    def update_auth_secret(self, config: MampokConfig) -> str:
        """Generate a new JWT auth secret and update it on the cluster.

        Creates a random secret_key, builds the K8s secret in the format of the
        bcu-container-auth-proxy, persists the secret_key in project_auth.json,
        and returns an initial token URL.

        Args:
            users: List of usernames/organisations with access.
            config: Configuration with cluster credentials.

        Returns:
            Initial token URL (cfg.url + ?token=<jwt>) for immediate access.
        """
        cfg = self._build_deployment_config(config)
        service = self.mamplan.data["service"]
        owner = service["owner"]
        groups = service.get("organization", [])
        users = service.get("users", [])

        secret_key = _generate_secret_key()
        auth_data = {
            "secret_key": secret_key,
            "users": users,
            "owner": owner,
            "groups": groups,
        }

        # Create/update K8s secret
        builder = ManifestBuilder()
        manifest = builder.build_auth_secret(cfg, auth_data)
        self.kube._kube.apply(manifest)

        # Persist secret_key in project_auth.json (for Flask API /openProject)
        auth_proxy = config.auth_proxy
        if auth_proxy and auth_proxy.project_auth_path:
            path = Path(auth_proxy.project_auth_path)
            existing: dict = {}
            if path.exists():
                with path.open("r", encoding="utf-8") as f:
                    existing = json.load(f)
            existing[cfg.project_id] = secret_key
            with path.open("w", encoding="utf-8") as f:
                json.dump(existing, f, indent=2)

        # Generate initial JWT for immediate access
        payload = {
            "groups": groups,
            "username": owner,
            "iat": datetime.now(timezone.utc),
        }
        token = jwt.encode(payload, secret_key, algorithm="HS256")
        return f"{cfg.url}?token={token}"

    def _build_deployment_config(self, config: MampokConfig) -> DeploymentConfig:
        """Derive a DeploymentConfig from Mamplan, Mamplate, and ClusterConfig.

        Args:
            config: MampokConfig with cluster and S3 data.

        Returns:
            Fully populated DeploymentConfig.
        """
        cluster_name = self.mamplan.data["deployment"]["cluster"]
        cluster_cfg = config.get_cluster(cluster_name)
        auth_proxy = config.auth_proxy

        merged = self.mamplan.merge_container_config(
            self.mamplate, self.mamplan.data, self.init_mamplates
        )
        main = merged["main"]

        # ports: Mamplate schema uses single int → convert to list
        raw_ports = main.get("ports")
        ports = [raw_ports] if isinstance(raw_ports, int) else (raw_ports or [])

        # resources
        resources = main.get("resources", {})
        limits = resources.get("limits", {})
        requests = resources.get("requests", {})

        # volume: {mountPath, name} → volume_mounts + volumes (emptyDir)
        volume = main.get("volume")
        if volume:
            volume_mounts = [{"name": volume["name"], "mountPath": volume["mountPath"]}]
            volumes = [{"name": volume["name"], "emptyDir": {}}]
        else:
            volume_mounts = []
            volumes = []

        project_id = self.mamplan.data["project"]["project_id"]
        tool = self.mamplan.data["project"]["tool"]
        env = main.get("env", [])

        raw_init_list = merged.get("init", [])
        init_containers = list(raw_init_list)

        files = self.mamplan.data["project"].get("files", [])
        include_s3download = bool(files)

        custom_url_id = self.mamplan.data["deployment"].get("custom_url_id")
        random_url_suffix = self.mamplan.data["deployment"].get("random_url_suffix", False)
        base = custom_url_id if custom_url_id else project_id
        if random_url_suffix:
            suffix = "".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(5))
            path_segment = f"{base}-{suffix}"
        else:
            path_segment = base
        url = f"https://{cluster_cfg.host}/{cluster_cfg.namespace}/{path_segment}/{tool}/" if cluster_cfg.host else ""

        container_data = main.get("container_data", {})
        container_data_paths = container_data.get("paths", [])
        merged_cd = {**_CONTAINER_DATA_DEFAULTS, **container_data}
        container_data_restore = bool(merged_cd["restore_on_deploy"])
        container_data_sync_interval = int(merged_cd["sync_interval_seconds"])
        container_data_sync_timeout = int(merged_cd["sync_timeout_seconds"])
        is_bucket_overwrite = False
        container_data_s3_subpath = ""

        bucket_overwrite = main.get("bucket_overwrite")
        if bucket_overwrite:
            container_data_paths = [bucket_overwrite["path_in_container"]]
            container_data_restore = True
            is_bucket_overwrite = True
            container_data_s3_subpath = bucket_overwrite.get("s3_subpath", "")
            include_s3download = False

        return DeploymentConfig(
            project_id=project_id,
            tool=tool,
            image=main["image"],
            namespace=cluster_cfg.namespace,
            cpu=str(limits.get("cpu", "1")),
            memory=str(limits.get("memory", "2Gi")),
            request_cpu=str(requests["cpu"]) if "cpu" in requests else "",
            request_memory=str(requests["memory"]) if "memory" in requests else "",
            ports=ports,
            env=env,
            args=main.get("args", []),
            command=main.get("command", []),
            url=url,
            host=cluster_cfg.host,
            auth=self.mamplan.auth,
            volume_mounts=volume_mounts,
            volumes=volumes,
            readiness_probe=main.get("readinessProbe"),
            ingress_annotations={**cluster_cfg.annotations, **main.get("annotation", {})},
            ingress_class=cluster_cfg.ingress_class,
            tls_issuer=cluster_cfg.dnsissuer,
            tls_secret=cluster_cfg.dnssecret,
            s3_secret_name=config.s3.secretname,
            init_containers=init_containers,
            include_s3download=include_s3download,
            bucket=self.s3.bucket,
            endpoint=config.s3.endpoint,
            is_bucket_overwrite=is_bucket_overwrite,
            container_data_s3_subpath=container_data_s3_subpath,
            auth_proxy_image=auth_proxy.auth_proxy_image if auth_proxy else "",
            proxy_port=auth_proxy.proxy_port if auth_proxy else 8080,
            auth_annotations=auth_proxy.auth_annotations if auth_proxy else {},
            image_pull_secrets=auth_proxy.image_pull_secrets if auth_proxy else [],
            container_data_paths=container_data_paths,
            container_data_restore=container_data_restore,
            container_data_sync_interval=container_data_sync_interval,
            container_data_sync_timeout=container_data_sync_timeout,
        )



def _generate_secret_key(length: int = 32) -> str:
    """Generate a cryptographically secure random secret key.

    Args:
        length: Length of the key.

    Returns:
        Random alphanumeric string.
    """
    characters = string.ascii_letters + string.digits
    return "".join(secrets.choice(characters) for _ in range(length))
