"""ToolchainCache — pack and restore a pre-built Buildroot cross-compiler.

The cross-compiler (GCC + binutils + sysroot) takes 40-50 minutes to
build from source.  After the first successful build we pack it into a
single .tar.gz archive and restore it on subsequent runs — reducing the
toolchain step from ~45 min to ~30 seconds.

What is packed
--------------
From ``buildroot-output-{target}/``:
  host/                           — cross-compiler, headers, sysroot (~400 MB)
  build/**/.stamp_*               — Buildroot stamp files (bytes each)
  build/toolchain-buildroot*/     — virtual package directories (metadata)
  .last_toolchain_hash            — our config-change detection hash

When Buildroot runs ``make`` after restoration, it reads the stamp files
and considers every tool already built — so the entire toolchain stage is
skipped.

Cache key
---------
``{arch}-br{buildroot_version}-{config_hash8}``

Example: ``arm64-br2026.02.1-a2b3c4d5.tar.gz``

The config hash covers: buildroot_arch, cross_compile, buildroot_version,
and the toolchain options (GLIBC + CXX).  A change in any of these
produces a different key and triggers a fresh build + new cache entry.

Layout::

    temp/cache/toolchains/
        arm64-br2026.02.1-a2b3c4d5.tar.gz
        x86_64-br2026.02.1-e5f6a7b8.tar.gz
        index.json
"""
from __future__ import annotations

import hashlib
import json
import logging
import tarfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from netos_build.plan import ResolvedBuildPlan

_INDEX_FILE = "index.json"
# Virtual toolchain package dirs created by Buildroot (tiny, contain only stamps)
_TC_VIRTUAL_DIRS = (
    "toolchain-buildroot",
    "toolchain-buildroot-aux",
    "toolchain-buildroot-initial",
)


class ToolchainCache:
    """Pack and restore a Buildroot cross-compiler toolchain."""

    def __init__(self, cache_root: Path) -> None:
        self.cache_dir = Path(cache_root) / "toolchains"

    # ------------------------------------------------------------------
    # Key / path helpers
    # ------------------------------------------------------------------

    def cache_key(self, plan: "ResolvedBuildPlan", buildroot_version: str) -> str:
        """Stable filename stem for this (plan, buildroot_version) combination."""
        raw = "\n".join([
            plan.buildroot_arch,
            plan.cross_compile,
            buildroot_version,
            "BR2_TOOLCHAIN_BUILDROOT_GLIBC=y",
            "BR2_TOOLCHAIN_BUILDROOT_CXX=y",
        ])
        short = hashlib.md5(raw.encode()).hexdigest()[:8]
        return f"{plan.arch}-br{buildroot_version}-{short}"

    def archive_path(self, plan: "ResolvedBuildPlan", buildroot_version: str) -> Path:
        return self.cache_dir / f"{self.cache_key(plan, buildroot_version)}.tar.gz"

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
        """Pack the toolchain from *output_dir* into the cache.

        Uses gzip level-1 compression (fast; still achieves ~3× reduction).
        Atomic: written to ``*.tar.gz.tmp`` then renamed to the final path.

        Returns the archive path.
        Raises ``FileNotFoundError`` if ``host/`` is absent.
        """
        output_dir = Path(output_dir)
        host_dir   = output_dir / "host"
        build_dir  = output_dir / "build"

        if not host_dir.exists():
            raise FileNotFoundError(
                f"Toolchain host/ not found in {output_dir} — nothing to pack"
            )

        dest = self.archive_path(plan, buildroot_version)
        tmp  = dest.with_suffix(".tar.gz.tmp")
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        logging.info(
            "Packing toolchain %s → %s (compresslevel=1, may take ~30s)…",
            output_dir.name, dest.name,
        )
        t0 = time.monotonic()

        try:
            with tarfile.open(tmp, "w:gz", compresslevel=1) as tar:
                # 1. Cross-compiler binaries, headers, sysroot
                tar.add(host_dir, arcname="host")

                if build_dir.exists():
                    # 2. All .stamp_* files from build/ (bytes each — tell
                    #    Buildroot "this package is already done")
                    for stamp in sorted(build_dir.rglob(".stamp_*")):
                        tar.add(stamp, arcname=str(stamp.relative_to(output_dir)))

                    # 3. Virtual toolchain package dirs (small metadata dirs)
                    for name in _TC_VIRTUAL_DIRS:
                        tc_dir = build_dir / name
                        if tc_dir.exists():
                            tar.add(tc_dir, arcname=str(tc_dir.relative_to(output_dir)))

                # 4. Our config-hash sentinel
                h = output_dir / ".last_toolchain_hash"
                if h.exists():
                    tar.add(h, arcname=".last_toolchain_hash")

            tmp.rename(dest)

        except Exception:
            tmp.unlink(missing_ok=True)
            raise

        elapsed = time.monotonic() - t0
        size_mb = dest.stat().st_size / 1e6
        logging.info(
            "Toolchain packed: %s  (%.1f MB, %.0fs)",
            dest.name, size_mb, elapsed,
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
        """Restore toolchain from cache into *output_dir*.

        Returns ``True`` on success, ``False`` if the cache entry does not
        exist or the archive is corrupt (corrupt archives are deleted so the
        next run triggers a clean rebuild).
        """
        archive = self.archive_path(plan, buildroot_version)
        if not archive.exists():
            return False

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        logging.info(
            "Restoring toolchain from cache: %s → %s", archive.name, output_dir
        )
        t0 = time.monotonic()
        try:
            with tarfile.open(archive, "r:gz") as tar:
                tar.extractall(output_dir)
        except Exception as exc:
            logging.error(
                "Toolchain restore failed (%s) — deleting corrupt cache, "
                "will rebuild from source",
                exc,
            )
            archive.unlink(missing_ok=True)
            return False

        elapsed = time.monotonic() - t0
        logging.info(
            "Toolchain restored in %.0fs — Buildroot will skip ~45min GCC build",
            elapsed,
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
            "cross_compile":     plan.cross_compile,
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
