"""RootfsCache — pack and restore a pre-built Buildroot rootfs.tar.

Building all packages from source (Python3, OpenVSwitch, curl, Git …)
takes 30-60 minutes.  After the first successful build we compress the
``images/rootfs.tar`` and restore it on subsequent runs — reducing the
full-build step to ~10 seconds.

What is packed
--------------
From ``buildroot-output-{target}/images/``:
  rootfs.tar    — the entire target filesystem (~150-300 MB uncompressed)

The archive is stored as ``{key}.rootfs.tar.gz`` (gzip level-1, fast).

Cache key
---------
``{arch}-br{buildroot_version}-{packages_hash16}``

  packages_hash16  — 16-char MD5 of sorted all_packages (see plan.packages_hash())

A change in *any* package, in the arch, or in the Buildroot version
produces a different key and triggers a fresh build + new cache entry.

Layout::

    temp/cache/rootfs/
        arm64-br2026.02.1-a1b2c3d4e5f60708.rootfs.tar.gz
        x86_64-br2026.02.1-1122334455667788.rootfs.tar.gz
        index.json
"""
from __future__ import annotations

import gzip
import json
import logging
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from netos_build.plan import ResolvedBuildPlan

_INDEX_FILE = "index.json"
_CHUNK = 1 << 20  # 1 MiB streaming chunks


class RootfsCache:
    """Pack and restore a Buildroot rootfs.tar archive."""

    def __init__(self, cache_root: Path) -> None:
        self.cache_dir = Path(cache_root) / "rootfs"

    # ------------------------------------------------------------------
    # Key / path helpers
    # ------------------------------------------------------------------

    def cache_key(self, plan: "ResolvedBuildPlan", buildroot_version: str) -> str:
        """Stable filename stem: ``{arch}-br{buildroot_version}-{packages_hash16}``."""
        return f"{plan.arch}-br{buildroot_version}-{plan.packages_hash()}"

    def archive_path(self, plan: "ResolvedBuildPlan", buildroot_version: str) -> Path:
        return self.cache_dir / f"{self.cache_key(plan, buildroot_version)}.rootfs.tar.gz"

    def has(self, plan: "ResolvedBuildPlan", buildroot_version: str) -> bool:
        """Return True iff a cache archive exists for this key."""
        return self.archive_path(plan, buildroot_version).exists()

    # ------------------------------------------------------------------
    # Pack
    # ------------------------------------------------------------------

    def pack(
        self,
        plan: "ResolvedBuildPlan",
        buildroot_version: str,
        output_dir: Path,
    ) -> Path:
        """Compress ``images/rootfs.tar`` from *output_dir* into the cache.

        Uses gzip level-1 (fast; typically ~2-3× size reduction).
        Atomic: written to ``*.tmp`` then renamed.

        Returns the archive path.
        Raises ``FileNotFoundError`` if ``images/rootfs.tar`` is absent.
        """
        output_dir = Path(output_dir)
        rootfs_tar = output_dir / "images" / "rootfs.tar"

        if not rootfs_tar.exists():
            raise FileNotFoundError(
                f"Buildroot rootfs.tar not found at {rootfs_tar} — nothing to pack"
            )

        dest = self.archive_path(plan, buildroot_version)
        tmp  = dest.with_suffix(".tmp")
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        logging.info(
            "Packing rootfs cache %s → %s (gzip level=1, may take ~20s)…",
            output_dir.name, dest.name,
        )
        t0 = time.monotonic()

        try:
            with rootfs_tar.open("rb") as src, \
                 gzip.open(tmp, "wb", compresslevel=1) as gz:
                shutil.copyfileobj(src, gz, length=_CHUNK)
            tmp.rename(dest)
        except Exception:
            tmp.unlink(missing_ok=True)
            raise

        elapsed = time.monotonic() - t0
        size_mb = dest.stat().st_size / 1e6
        orig_mb = rootfs_tar.stat().st_size / 1e6
        logging.info(
            "Rootfs cached: %s  (%.1f MB from %.1f MB, %.0fs)",
            dest.name, size_mb, orig_mb, elapsed,
        )
        self._update_index(plan, buildroot_version, dest)
        return dest

    # ------------------------------------------------------------------
    # Restore
    # ------------------------------------------------------------------

    def restore(
        self,
        plan: "ResolvedBuildPlan",
        buildroot_version: str,
        output_dir: Path,
    ) -> bool:
        """Decompress cached rootfs into ``output_dir/images/rootfs.tar``.

        Returns ``True`` on success, ``False`` if the cache entry does not
        exist or the archive is corrupt (corrupt archives are deleted so the
        next run triggers a clean rebuild).
        """
        archive = self.archive_path(plan, buildroot_version)
        if not archive.exists():
            return False

        output_dir = Path(output_dir)
        images_dir = output_dir / "images"
        images_dir.mkdir(parents=True, exist_ok=True)

        dest = images_dir / "rootfs.tar"
        tmp  = dest.with_suffix(".tmp")

        logging.info(
            "Restoring rootfs from cache: %s → %s", archive.name, dest
        )
        t0 = time.monotonic()
        try:
            with gzip.open(archive, "rb") as gz, tmp.open("wb") as out:
                shutil.copyfileobj(gz, out, length=_CHUNK)
            tmp.rename(dest)
        except Exception as exc:
            logging.error(
                "Rootfs restore failed (%s) — deleting corrupt cache, "
                "will rebuild from source",
                exc,
            )
            tmp.unlink(missing_ok=True)
            archive.unlink(missing_ok=True)
            return False

        elapsed = time.monotonic() - t0
        size_mb = dest.stat().st_size / 1e6
        logging.info(
            "Rootfs restored in %.0fs (%.1f MB) — Buildroot make skipped",
            elapsed, size_mb,
        )
        return True

    # ------------------------------------------------------------------
    # Index
    # ------------------------------------------------------------------

    def _update_index(
        self,
        plan: "ResolvedBuildPlan",
        buildroot_version: str,
        archive: Path,
    ) -> None:
        data = self._load_index()
        data[self.cache_key(plan, buildroot_version)] = {
            "arch":              plan.arch,
            "buildroot_version": buildroot_version,
            "packages_hash":     plan.packages_hash(),
            "size_bytes":        archive.stat().st_size,
            "packed_at":         datetime.now(tz=timezone.utc).isoformat(),
        }
        self._save_index(data)

    def _load_index(self) -> dict[str, Any]:
        p = self.cache_dir / _INDEX_FILE
        if p.exists():
            try:
                return json.loads(p.read_text())
            except Exception:
                pass
        return {}

    def _save_index(self, data: dict[str, Any]) -> None:
        (self.cache_dir / _INDEX_FILE).write_text(
            json.dumps(data, indent=2, ensure_ascii=False)
        )
