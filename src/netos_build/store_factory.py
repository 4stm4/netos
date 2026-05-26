"""StoreFactory — create ArtifactStore from a URL or environment variables.

Usage::

    from netos_build.store_factory import StoreFactory

    store = StoreFactory.from_env()          # reads NETOS_ARTIFACT_STORE
    store = StoreFactory.from_url("http://cache.local:9000")
    store = StoreFactory.from_url("s3://my-bucket/netos")

URL schemes
-----------
(empty / None)    → LocalStore (no remote)
http:// https://  → HttpStore
s3://             → S3Store (requires boto3)
file://           → LocalStore (path is ignored; treated as no-op)
"""
from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from netos_build.store import ArtifactStore


_ENV_STORE_URL    = "NETOS_ARTIFACT_STORE"
_ENV_STORE_TOKEN  = "NETOS_ARTIFACT_STORE_TOKEN"
_ENV_STORE_PUSH   = "NETOS_STORE_PUSH"
_ENV_TIMEOUT      = "NETOS_STORE_TIMEOUT"
_ENV_S3_ENDPOINT  = "NETOS_STORE_S3_ENDPOINT_URL"
_ENV_S3_REGION    = "NETOS_STORE_S3_REGION"
_ENV_S3_ACCESS    = "NETOS_STORE_S3_ACCESS_KEY"
_ENV_S3_SECRET    = "NETOS_STORE_S3_SECRET_KEY"


class StoreFactory:
    """Factory that creates the appropriate ArtifactStore for a URL."""

    @staticmethod
    def from_env() -> "ArtifactStore":
        """Create a store from ``NETOS_ARTIFACT_STORE`` (or LocalStore)."""
        url = os.environ.get(_ENV_STORE_URL, "").strip()
        return StoreFactory.from_url(url)

    @staticmethod
    def from_url(url: str) -> "ArtifactStore":
        """Create a store from *url*.

        Returns ``LocalStore`` when *url* is empty or ``file://`` scheme.
        """
        from netos_build.store import LocalStore, HttpStore

        url = (url or "").strip()
        if not url or url.startswith("file://"):
            return LocalStore()

        timeout = int(os.environ.get(_ENV_TIMEOUT, "120"))

        if url.startswith(("http://", "https://")):
            token = os.environ.get(_ENV_STORE_TOKEN, "")
            return HttpStore(base_url=url, token=token, timeout=timeout)

        if url.startswith("s3://"):
            return StoreFactory._make_s3(url, timeout)

        raise ValueError(
            f"Unsupported artifact store URL scheme: {url!r}. "
            "Supported: http://, https://, s3://, file://, (empty for local)"
        )

    @staticmethod
    def _make_s3(url: str, timeout: int) -> "ArtifactStore":
        from netos_build.store_s3 import S3Store

        # Parse s3://bucket/optional/prefix
        without_scheme = url[len("s3://"):]
        parts          = without_scheme.split("/", 1)
        bucket         = parts[0]
        prefix         = parts[1].strip("/") if len(parts) > 1 else ""

        return S3Store(
            bucket       = bucket,
            prefix       = prefix,
            endpoint_url = os.environ.get(_ENV_S3_ENDPOINT, ""),
            region       = os.environ.get(_ENV_S3_REGION, "us-east-1"),
            access_key   = os.environ.get(_ENV_S3_ACCESS, ""),
            secret_key   = os.environ.get(_ENV_S3_SECRET, ""),
            timeout      = timeout,
        )

    @staticmethod
    def push_enabled() -> bool:
        """Return False when ``NETOS_STORE_PUSH=0`` (read-only mode)."""
        return os.environ.get(_ENV_STORE_PUSH, "1").strip() != "0"
