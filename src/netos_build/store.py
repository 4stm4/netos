"""Artifact Store — pluggable remote backend for cache archives.

The local filesystem caches created by ToolchainCache (M3) and
RootfsCache (M5) become a **two-tier** system when a remote store is
configured:

  1. Check local cache first (fast, no network).
  2. On cache miss: try to *pull* from remote store → populate local.
  3. After a new local pack: *push* to remote store for other builders.

This enables shared CI caches without changing the local-cache logic.

Implementations
---------------
LocalStore  — no-op (always miss on pull, always succeeds on push)
HttpStore   — HTTP GET / PUT / HEAD via stdlib urllib (zero extra deps)
S3Store     — S3-compatible storage via boto3 (see store_s3.py)

Configuration (env vars)
------------------------
NETOS_ARTIFACT_STORE      URL of the remote store, e.g.:
                             http://cache.local:9000
                             https://cache.example.com/netos
                             s3://my-bucket/netos-cache
NETOS_ARTIFACT_STORE_TOKEN  Bearer token for HTTP store auth (optional)
NETOS_STORE_TIMEOUT         HTTP timeout in seconds (default 120)
NETOS_STORE_PUSH            Set to "0" to disable push (read-only mode)
"""
from __future__ import annotations

import logging
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from pathlib import Path

_CHUNK = 1 << 20  # 1 MiB


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class ArtifactStore(ABC):
    """Interface for remote artifact stores."""

    @abstractmethod
    def exists(self, remote_key: str) -> bool:
        """Return True iff the key exists in the store (HEAD check)."""

    @abstractmethod
    def download(self, remote_key: str, local_path: Path) -> bool:
        """Download *remote_key* to *local_path*.

        Returns True on success, False if the key does not exist.
        Raises on network or server error.
        """

    @abstractmethod
    def upload(self, remote_key: str, local_path: Path) -> bool:
        """Upload *local_path* to *remote_key*.

        Returns True on success, False if upload was skipped.
        Raises on network or server error.
        """

    @property
    def is_local(self) -> bool:
        """True for LocalStore (no network I/O)."""
        return False


# ---------------------------------------------------------------------------
# LocalStore — null object, never has a remote copy
# ---------------------------------------------------------------------------

class LocalStore(ArtifactStore):
    """No-op store — acts as if the remote is always empty.

    Useful as a default when no ``NETOS_ARTIFACT_STORE`` is set.
    """

    def exists(self, remote_key: str) -> bool:
        return False

    def download(self, remote_key: str, local_path: Path) -> bool:
        return False

    def upload(self, remote_key: str, local_path: Path) -> bool:
        return False

    @property
    def is_local(self) -> bool:
        return True

    def __repr__(self) -> str:
        return "LocalStore()"


# ---------------------------------------------------------------------------
# HttpStore — HTTP GET / PUT / HEAD
# ---------------------------------------------------------------------------

class HttpStore(ArtifactStore):
    """Store backed by an HTTP server that supports GET, PUT and HEAD.

    Compatible with nginx ``dav_module``, MinIO, Caddy file server, or
    any custom endpoint.  All requests are plain HTTP(S) — no S3 signing.

    Auth
    ----
    Pass ``token`` (or set ``NETOS_ARTIFACT_STORE_TOKEN``) to send a
    ``Authorization: Bearer <token>`` header with every request.
    """

    def __init__(
        self,
        base_url: str,
        token: str = "",
        timeout: int = 120,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token    = token
        self.timeout  = timeout

    def _url(self, key: str) -> str:
        return f"{self.base_url}/{key}"

    def _headers(self) -> dict[str, str]:
        h: dict[str, str] = {"User-Agent": "netos-build/1.0"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def _request(self, method: str, url: str, data=None) -> "urllib.request.Request":
        req = urllib.request.Request(url, data=data, method=method)
        for k, v in self._headers().items():
            req.add_header(k, v)
        return req

    # ------------------------------------------------------------------

    def exists(self, remote_key: str) -> bool:
        url = self._url(remote_key)
        try:
            req = self._request("HEAD", url)
            with urllib.request.urlopen(req, timeout=self.timeout):
                return True
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return False
            raise
        except OSError:
            return False

    def download(self, remote_key: str, local_path: Path) -> bool:
        url = self._url(remote_key)
        tmp = local_path.with_suffix(local_path.suffix + ".dl")
        try:
            req = self._request("GET", url)
            logging.info("Store: downloading %s", remote_key)
            t0 = time.monotonic()
            with urllib.request.urlopen(req, timeout=self.timeout) as resp, \
                 tmp.open("wb") as out:
                while True:
                    chunk = resp.read(_CHUNK)
                    if not chunk:
                        break
                    out.write(chunk)
            tmp.rename(local_path)
            elapsed = time.monotonic() - t0
            size_mb = local_path.stat().st_size / 1e6
            logging.info(
                "Store: downloaded %s (%.1f MB, %.0fs)", remote_key, size_mb, elapsed
            )
            return True
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return False
            raise
        except Exception:
            tmp.unlink(missing_ok=True)
            raise

    def upload(self, remote_key: str, local_path: Path) -> bool:
        if not local_path.exists():
            logging.warning("Store: upload skipped — file not found: %s", local_path)
            return False
        url = self._url(remote_key)
        size_mb = local_path.stat().st_size / 1e6
        logging.info("Store: uploading %s (%.1f MB) → %s", local_path.name, size_mb, url)
        t0 = time.monotonic()
        try:
            data = local_path.read_bytes()
            req  = self._request("PUT", url, data=data)
            req.add_header("Content-Type", "application/octet-stream")
            with urllib.request.urlopen(req, timeout=self.timeout):
                pass
            elapsed = time.monotonic() - t0
            logging.info("Store: uploaded %s (%.0fs)", remote_key, elapsed)
            return True
        except urllib.error.HTTPError as exc:
            logging.error(
                "Store: upload failed for %s — HTTP %s: %s",
                remote_key, exc.code, exc.reason,
            )
            raise

    def __repr__(self) -> str:
        return f"HttpStore({self.base_url!r})"
