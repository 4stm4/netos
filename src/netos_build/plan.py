"""ResolvedBuildPlan — central model describing everything needed to build a netOS image.

This is the contract between:
  - Build frontends  (main.py, web configurator, future CLI)
  - Build backends   (Buildroot, future Yocto, artifact-store)

Design principles:
  - Plain dataclass: no side effects, easy to serialise / test
  - Compat adapter  ``from_target()`` converts the legacy TargetConfig so
    existing call-sites continue to work unchanged
  - ``cache_policy`` controls how the artifact/toolchain caches are used
    (``"use"`` → normal, ``"rebuild"`` → ignore cache, ``"refresh"`` → re-verify)
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from targets import TargetConfig  # only for type-checkers, avoids runtime coupling


# ---------------------------------------------------------------------------
# Canonical arch mapping
# ---------------------------------------------------------------------------

_BUILDROOT_ARCH_TO_ARCH: dict[str, str] = {
    "aarch64": "arm64",
    "x86_64":  "x86_64",
    "arm":     "arm",
}

_CACHE_POLICIES = frozenset({"use", "rebuild", "refresh"})
_IMAGE_FORMATS  = frozenset({"raw", "qcow2", "iso"})


# ---------------------------------------------------------------------------

@dataclass
class ResolvedBuildPlan:
    """Everything the build pipeline needs to know about a single build.

    Created once per build via :meth:`from_target` (compat path) or
    directly by the configurator / future CLI.
    """

    # ── Identity ──────────────────────────────────────────────────────────
    target: str         # "qemu-virt" | "pi5" | "qemu-x86" | …
    arch:   str         # "arm64" | "x86_64"

    # ── Kernel ────────────────────────────────────────────────────────────
    kernel_arch:      str   # ARCH= value for make ("arm64" | "x86")
    kernel_source:    str   # "mainline" | "rpi"
    kernel_defconfig: str   # "defconfig" | "bcm2712_defconfig" | …
    kernel_filename:  str   # filename in /boot  ("Image" | "bzImage" | …)
    cross_compile:    str   # CROSS_COMPILE= ("aarch64-linux-gnu-" | …)

    # ── Buildroot ─────────────────────────────────────────────────────────
    buildroot_arch: str             # "aarch64" | "x86_64"
    packages:       tuple[str, ...] # BR2_PACKAGE_* lines

    # ── Image ─────────────────────────────────────────────────────────────
    image_name:         str
    image_format:       str   # "raw" (future: "qcow2" | "iso")
    image_size_mb:      int
    boot_size_mb:       int
    install_boot_files: bool
    boot_cmdline:       str

    # ── Build control ─────────────────────────────────────────────────────
    cache_policy: str = "use"   # "use" | "rebuild" | "refresh"

    # ── QEMU metadata ─────────────────────────────────────────────────────
    qemu_machine:     Optional[str] = None
    qemu_cpu:         Optional[str] = None
    qemu_root_device: Optional[str] = None

    # ── Extra packages (CLI --packages-file or configurator) ──────────────
    extra_packages: tuple[str, ...] = field(default_factory=tuple)

    # ── External tree / overlay content hash ──────────────────────────────
    # Hash of the generated external-tree content (overlay files, .mk files,
    # post-build scripts, NETOS_VERSION, etc.).  When any of these change the
    # rootfs cache key changes automatically, preventing stale cache hits after
    # nervum or other in-tree packages are updated.
    # Empty string means "not provided" → old behaviour (hash only packages).
    external_hash: str = ""

    # ── Future fields (stubs, filled in by later milestones) ──────────────
    # edition:   str = "base"        # M6+: base | hypervisor | storage | gui
    # ui_profile: str = "testum"     # M6+
    # backend:   str = "buildroot"   # M6+: buildroot | yocto | artifact-store

    # ------------------------------------------------------------------
    def __post_init__(self) -> None:
        if self.cache_policy not in _CACHE_POLICIES:
            raise ValueError(
                f"Invalid cache_policy {self.cache_policy!r}. "
                f"Allowed: {sorted(_CACHE_POLICIES)}"
            )
        if self.image_format not in _IMAGE_FORMATS:
            raise ValueError(
                f"Invalid image_format {self.image_format!r}. "
                f"Allowed: {sorted(_IMAGE_FORMATS)}"
            )

    # ------------------------------------------------------------------
    @classmethod
    def from_target(
        cls,
        t: "TargetConfig",
        extra_packages: "list[str] | tuple[str, ...] | None" = None,
        cache_policy: str = "use",
        external_hash: str = "",
    ) -> "ResolvedBuildPlan":
        """Compatibility adapter: ``TargetConfig`` → ``ResolvedBuildPlan``.

        All existing call-sites that use ``TargetConfig`` continue to work
        by passing the config through this method.

        ``external_hash`` should be the output of
        ``NetOSBuildrootBuilder._external_content_hash()`` so that rootfs cache
        keys change automatically when overlay / .mk / NETOS_VERSION changes.
        """
        return cls(
            target            = t.name,
            arch              = _BUILDROOT_ARCH_TO_ARCH.get(t.buildroot_arch, t.buildroot_arch),
            kernel_arch       = t.kernel_arch,
            kernel_source     = t.kernel_source,
            kernel_defconfig  = t.kernel_defconfig,
            kernel_filename   = t.kernel_filename,
            cross_compile     = t.cross_compile,
            buildroot_arch    = t.buildroot_arch,
            packages          = tuple(t.buildroot_package_lines),
            image_name        = t.image_name,
            image_format      = "qcow2" if t.qemu_machine is not None else "raw",
            image_size_mb     = t.image_size_mb,
            boot_size_mb      = t.boot_size_mb,
            install_boot_files = t.install_boot_files,
            boot_cmdline      = t.boot_cmdline,
            qemu_machine      = t.qemu_machine,
            qemu_cpu          = t.qemu_cpu,
            qemu_root_device  = t.qemu_root_device,
            extra_packages    = tuple(extra_packages or []),
            cache_policy      = cache_policy,
            external_hash     = external_hash,
        )

    # ------------------------------------------------------------------
    # Derived helpers used by the cache layer (M3)
    # ------------------------------------------------------------------

    @property
    def all_packages(self) -> tuple[str, ...]:
        """Combined package list: target packages + extra CLI packages."""
        return self.packages + self.extra_packages

    def packages_hash(self) -> str:
        """Stable 16-char hex hash covering packages + external tree content.

        Mixing in ``external_hash`` ensures the rootfs cache key changes
        whenever generated overlay files, .mk recipes, NETOS_VERSION, or any
        other in-tree content changes — even if the package *list* stays the same.
        """
        joined = "\n".join(sorted(self.all_packages))
        if self.external_hash:
            joined += "\n__external__\n" + self.external_hash
        return hashlib.md5(joined.encode()).hexdigest()[:16]

    def toolchain_cache_key(self) -> str:
        """Cache key for the pre-built cross-compiler (used by M3 toolchain cache)."""
        parts = "\n".join([
            self.buildroot_arch,
            self.cross_compile,
            "BR2_TOOLCHAIN_BUILDROOT_GLIBC=y",
            "BR2_TOOLCHAIN_BUILDROOT_CXX=y",
        ])
        short = hashlib.md5(parts.encode()).hexdigest()[:8]
        return f"{self.arch}-{short}"
