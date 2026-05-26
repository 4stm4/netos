"""ArtifactManager — public façade for all artifact operations.

Usage::

    mgr = ArtifactManager(temp_path)

    # Download Buildroot tarball (with SHA-256 verification):
    archive = mgr.fetch(
        url    = "https://buildroot.org/downloads/buildroot-2026.02.1.tar.xz",
        sha256 = "a2216fdc...",
        filename = "buildroot-2026.02.1.tar.xz",
    )

    # Download mainline kernel (hash unknown yet — omit sha256):
    kernel_tar = mgr.fetch(
        url      = "https://cdn.kernel.org/pub/linux/kernel/v6.x/linux-6.12.27.tar.xz",
        filename = "linux-6.12.27.tar.xz",
    )
"""
from __future__ import annotations

import logging
from pathlib import Path

from .cache import DownloadCache
from .sources import ArtifactSource


class ArtifactManager:
    """Orchestrates download, caching and verification of build artifacts.

    All downloaded files land in ``<temp_path>/cache/downloads/`` and are
    re-verified on every cache lookup when a SHA-256 is provided.

    Future milestones will add:
    - Toolchain binary cache  (M3)
    - Rootfs artifact cache   (M5)
    - Remote store backends   (M7)
    """

    def __init__(self, temp_path: Path) -> None:
        self._cache = DownloadCache(Path(temp_path) / "cache")

    # ------------------------------------------------------------------
    # Primary API
    # ------------------------------------------------------------------

    def fetch(
        self,
        *,
        url:      str,
        sha256:   str | None = None,
        filename: str | None = None,
        timeout:  int = 300,
        retries:  int = 3,
    ) -> Path:
        """Return local path to *url*, downloading (and verifying) if needed.

        Parameters
        ----------
        url:      Download URL.
        sha256:   Expected hex digest.  Strongly recommended — omit only
                  for artifacts whose hash is not yet known.
        filename: Override cache filename (default: last URL segment).
        timeout:  Per-attempt network timeout (seconds).
        retries:  Max download attempts.
        """
        if sha256 is None:
            logging.warning(
                "ArtifactManager.fetch: no sha256 for %s — cache hit cannot be verified",
                url,
            )
        return self._cache.get(
            url=url,
            filename=filename,
            sha256=sha256,
            timeout=timeout,
            retries=retries,
        )

    def fetch_source(
        self,
        source:   ArtifactSource,
        filename: str | None = None,
    ) -> Path:
        """Fetch an artifact described by an :class:`ArtifactSource`."""
        if source.type == "url":
            return self.fetch(
                url=source.uri,
                sha256=source.sha256 or None,
                filename=filename,
                timeout=source.timeout,
                retries=source.retries,
            )
        if source.type == "local":
            path = Path(source.uri)
            if not path.exists():
                raise FileNotFoundError(f"Local artifact not found: {path}")
            logging.info("Using local artifact: %s", path)
            return path
        # "git" and future types — placeholder
        raise NotImplementedError(
            f"ArtifactSource type '{source.type}' is not yet implemented"
        )
