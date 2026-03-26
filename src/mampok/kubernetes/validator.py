"""Manifest validator — client-side K8s schema validation using official models."""

from __future__ import annotations

import json
import logging

from kubernetes.client import ApiClient

logger = logging.getLogger(__name__)

_KIND_TO_MODEL: dict[str, str] = {
    "Deployment": "V1Deployment",
    "Service": "V1Service",
    "Secret": "V1Secret",
    "Ingress": "V1Ingress",
}


class ManifestValidationError(ValueError):
    """Raised when one or more manifests fail K8s schema validation."""


class ManifestValidator:
    """Validates K8s manifest dicts against the official kubernetes Python client models.

    Uses ``ApiClient.deserialize()`` which converts manifest dicts into the official
    V1* model objects, validating required fields and types in the process.
    No cluster connection required.
    """

    @staticmethod
    def validate(manifest: dict) -> None:
        """Validate a single manifest dict against its K8s schema model.

        Args:
            manifest: Complete K8s manifest dict (with apiVersion, kind, metadata, spec).

        Raises:
            ManifestValidationError: If the kind is unsupported or schema validation fails.
        """
        kind = manifest.get("kind", "")
        model_name = _KIND_TO_MODEL.get(kind)
        if not model_name:
            raise ManifestValidationError(
                f"Unsupported kind: {kind!r}. Supported: {list(_KIND_TO_MODEL)}"
            )

        encoded = json.dumps(manifest).encode()

        class _FakeResponse:
            data = encoded
            status = 200
            reason = "OK"

            def getheaders(self) -> dict:
                return {}

        try:
            ApiClient().deserialize(_FakeResponse(), model_name)
        except Exception as e:
            name = manifest.get("metadata", {}).get("name", "?")
            raise ManifestValidationError(f"{kind}/{name}: {e}") from e

    @staticmethod
    def validate_all(manifests: list[dict]) -> None:
        """Validate all manifests. Collects all errors before raising.

        Args:
            manifests: List of K8s manifest dicts.

        Raises:
            ManifestValidationError: If any manifest fails validation. All errors
                are collected and reported together.
        """
        errors = []
        for manifest in manifests:
            kind = manifest.get("kind", "?")
            name = manifest.get("metadata", {}).get("name", "?")
            logger.debug("validating %s/%s", kind, name)
            try:
                ManifestValidator.validate(manifest)
            except ManifestValidationError as e:
                errors.append(str(e))
        if errors:
            raise ManifestValidationError(
                "Manifest validation failed:\n" + "\n".join(f"  - {e}" for e in errors)
            )
