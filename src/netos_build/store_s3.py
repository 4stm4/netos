"""S3Store — S3-compatible artifact store backed by boto3.

This module is intentionally separate so that the rest of the build
tool does not hard-depend on boto3.  Import is deferred to runtime and
a clear error is raised if boto3 is not installed.

Compatible with:
  * AWS S3
  * MinIO (set endpoint_url)
  * Backblaze B2 S3-compatible API
  * Any other S3-compatible service

Configuration (env vars)
------------------------
NETOS_ARTIFACT_STORE          s3://bucket-name/optional/prefix
NETOS_STORE_S3_ENDPOINT_URL   Override endpoint (for MinIO / Backblaze)
NETOS_STORE_S3_REGION         AWS region (default us-east-1)
NETOS_STORE_S3_ACCESS_KEY     AWS_ACCESS_KEY_ID
NETOS_STORE_S3_SECRET_KEY     AWS_SECRET_ACCESS_KEY
NETOS_STORE_TIMEOUT           Operation timeout in seconds (default 120)

Example (MinIO running locally on port 9000)::

    export NETOS_ARTIFACT_STORE=s3://netos-cache
    export NETOS_STORE_S3_ENDPOINT_URL=http://localhost:9000
    export NETOS_STORE_S3_ACCESS_KEY=minioadmin
    export NETOS_STORE_S3_SECRET_KEY=minioadmin
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

from netos_build.store import ArtifactStore

_CHUNK = 8 << 20  # 8 MiB multipart threshold


class S3Store(ArtifactStore):
    """Artifact store backed by S3-compatible object storage.

    Parameters
    ----------
    bucket:
        S3 bucket name.
    prefix:
        Key prefix (without trailing slash).  All remote keys are stored
        as ``{prefix}/{remote_key}`` when prefix is non-empty.
    endpoint_url:
        Override the default AWS endpoint (for MinIO, Backblaze, etc.).
    region:
        AWS region string.
    access_key / secret_key:
        Credentials.  Falls back to standard boto3 credential chain
        (env vars, ``~/.aws/credentials``, IAM role) when not supplied.
    timeout:
        Per-operation timeout in seconds.
    """

    def __init__(
        self,
        bucket: str,
        prefix: str = "",
        endpoint_url: str = "",
        region: str = "us-east-1",
        access_key: str = "",
        secret_key: str = "",
        timeout: int = 120,
    ) -> None:
        self.bucket       = bucket
        self.prefix       = prefix.strip("/")
        self.endpoint_url = endpoint_url or None
        self.region       = region
        self.access_key   = access_key or None
        self.secret_key   = secret_key or None
        self.timeout      = timeout
        self._client      = None  # lazy-initialised

    # ------------------------------------------------------------------
    # boto3 client (lazy)
    # ------------------------------------------------------------------

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            import boto3  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "S3Store requires boto3.  Install it with: pip install boto3"
            ) from exc

        kwargs: dict = {
            "region_name": self.region,
            "config": boto3.session.Config(  # type: ignore[attr-defined]
                connect_timeout=self.timeout,
                read_timeout=self.timeout,
                retries={"max_attempts": 3},
            ),
        }
        if self.endpoint_url:
            kwargs["endpoint_url"] = self.endpoint_url
        if self.access_key and self.secret_key:
            kwargs["aws_access_key_id"]     = self.access_key
            kwargs["aws_secret_access_key"] = self.secret_key

        self._client = boto3.client("s3", **kwargs)  # type: ignore[assignment]
        return self._client

    def _s3_key(self, remote_key: str) -> str:
        return f"{self.prefix}/{remote_key}" if self.prefix else remote_key

    # ------------------------------------------------------------------

    def exists(self, remote_key: str) -> bool:
        import botocore.exceptions  # type: ignore[import]
        key = self._s3_key(remote_key)
        try:
            self._get_client().head_object(Bucket=self.bucket, Key=key)
            return True
        except botocore.exceptions.ClientError as exc:
            if exc.response["Error"]["Code"] in ("404", "NoSuchKey"):
                return False
            raise

    def download(self, remote_key: str, local_path: Path) -> bool:
        import botocore.exceptions  # type: ignore[import]
        key = self._s3_key(remote_key)
        tmp = local_path.with_suffix(local_path.suffix + ".dl")
        try:
            logging.info("S3Store: downloading s3://%s/%s", self.bucket, key)
            t0 = time.monotonic()
            self._get_client().download_file(self.bucket, key, str(tmp))
            tmp.rename(local_path)
            elapsed = time.monotonic() - t0
            size_mb = local_path.stat().st_size / 1e6
            logging.info(
                "S3Store: downloaded %s (%.1f MB, %.0fs)", remote_key, size_mb, elapsed
            )
            return True
        except botocore.exceptions.ClientError as exc:
            if exc.response["Error"]["Code"] in ("404", "NoSuchKey"):
                return False
            tmp.unlink(missing_ok=True)
            raise
        except Exception:
            tmp.unlink(missing_ok=True)
            raise

    def upload(self, remote_key: str, local_path: Path) -> bool:
        if not local_path.exists():
            logging.warning("S3Store: upload skipped — %s not found", local_path)
            return False
        key     = self._s3_key(remote_key)
        size_mb = local_path.stat().st_size / 1e6
        logging.info(
            "S3Store: uploading %s (%.1f MB) → s3://%s/%s",
            local_path.name, size_mb, self.bucket, key,
        )
        t0 = time.monotonic()
        self._get_client().upload_file(str(local_path), self.bucket, key)
        elapsed = time.monotonic() - t0
        logging.info("S3Store: uploaded %s (%.0fs)", remote_key, elapsed)
        return True

    def __repr__(self) -> str:
        prefix = f"/{self.prefix}" if self.prefix else ""
        ep     = f" endpoint={self.endpoint_url}" if self.endpoint_url else ""
        return f"S3Store(s3://{self.bucket}{prefix}{ep})"
