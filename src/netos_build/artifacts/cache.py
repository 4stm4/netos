"""Flat download cache with SHA-256 verification and JSON index.

Layout::

    temp/cache/downloads/
        buildroot-2026.02.1.tar.xz
        linux-6.12.27.tar.xz
        openvswitch-3.4.1.tar.gz
        index.json          ← {filename: {url, sha256, size, cached_at}}

Cache-hit rules:
- sha256 provided  →  hit iff file exists AND hash matches; on mismatch delete + re-download
- sha256 omitted   →  hit iff file exists (no hash check — use only when hash is unknown)
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .downloader import SafeDownloader
from .verifier import sha256_file, verify


class DownloadCache:
    """Manages a local directory of cached source archives."""

    def __init__(self, cache_root: Path) -> None:
        self.cache_dir  = cache_root / "downloads"
        self.index_path = self.cache_dir / "index.json"
        self._dl        = SafeDownloader()

    # ------------------------------------------------------------------
    def get(
        self,
        url: str,
        filename: str | None = None,
        sha256: str | None   = None,
        timeout: int         = 300,
        retries: int         = 3,
    ) -> Path:
        """Return local path to the artifact, downloading if necessary.

        Parameters
        ----------
        url:      Source URL.
        filename: Cache filename (default: last segment of *url*).
        sha256:   Expected hex digest.  If given, the cached file is
                  re-verified on every call; a mismatch triggers
                  deletion and a fresh download.  Pass ``None`` only
                  when the hash is not yet known (legacy paths).
        """
        if filename is None:
            filename = url.rsplit("/", 1)[-1]

        path = self.cache_dir / filename

        if path.exists():
            if sha256 is None:
                logging.info("Cache hit (no sha256 check): %s", filename)
                return path
            if verify(path, sha256):
                logging.info("Cache hit: %s", filename)
                return path
            logging.warning(
                "Cache: sha256 mismatch for %s — deleting and re-downloading", filename
            )
            path.unlink(missing_ok=True)
            self._drop_index(filename)

        # Download ---------------------------------------------------
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._dl.download(url, path, timeout=timeout, retries=retries)

        # Post-download verification ---------------------------------
        if sha256 is not None and not verify(path, sha256):
            actual = sha256_file(path)
            path.unlink(missing_ok=True)
            raise RuntimeError(
                f"SHA-256 mismatch after download for {filename}:\n"
                f"  expected : {sha256}\n"
                f"  actual   : {actual}"
            )

        self._update_index(filename, url, sha256, path.stat().st_size)
        return path

    # ------------------------------------------------------------------
    # Index helpers
    # ------------------------------------------------------------------
    def _load_index(self) -> dict[str, Any]:
        if self.index_path.exists():
            try:
                return json.loads(self.index_path.read_text())
            except Exception:
                return {}
        return {}

    def _save_index(self, data: dict[str, Any]) -> None:
        self.index_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    def _update_index(
        self, filename: str, url: str, sha256: str | None, size: int
    ) -> None:
        data = self._load_index()
        data[filename] = {
            "url":       url,
            "sha256":    sha256 or "",
            "size":      size,
            "cached_at": datetime.now(tz=timezone.utc).isoformat(),
        }
        self._save_index(data)

    def _drop_index(self, filename: str) -> None:
        data = self._load_index()
        if filename in data:
            data.pop(filename)
            self._save_index(data)
