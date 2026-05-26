import logging
import os
import shutil
import subprocess
import tarfile
from pathlib import Path

from netos_branding import NETOS_HOSTNAME, NETOS_ID, NETOS_NAME, NETOS_VERSION
from targets import TargetConfig
from netos_build.artifacts import ArtifactManager


BUILDROOT_VERSION = os.environ.get("NETOS_BUILDROOT_VERSION", "2026.02.1")
BUILDROOT_URL = os.environ.get(
    "NETOS_BUILDROOT_URL",
    f"https://buildroot.org/downloads/buildroot-{BUILDROOT_VERSION}.tar.xz",
)
BUILDROOT_SHA256 = os.environ.get(
    "NETOS_BUILDROOT_SHA256",
    "a2216fdc46b5e81e529acb9077324f7b4a9403366922f350bf7be67f46231b66",
)

_OPENVSWITCH_KNOWN_SHA256: dict[str, tuple[str, str]] = {
    "3.4.1": (
        "6e97ec7dfdda5b40b5103946d53e4f8b11edf66049fedbdcb323e1af67133de8",
        "f41f887b04dd604250193ddd88691ecd168dacdecca2d0d6581d8840e3f0b0dc",
    ),
}

OPENVSWITCH_VERSION = os.environ.get("NETOS_OPENVSWITCH_VERSION", "3.4.1")

if OPENVSWITCH_VERSION not in _OPENVSWITCH_KNOWN_SHA256:
    _custom_sha256 = os.environ.get("NETOS_OPENVSWITCH_SHA256")
    _custom_license_sha256 = os.environ.get("NETOS_OPENVSWITCH_LICENSE_SHA256")
    if not _custom_sha256 or not _custom_license_sha256:
        raise RuntimeError(
            f"NETOS_OPENVSWITCH_VERSION={OPENVSWITCH_VERSION} is not a known version. "
            "Set NETOS_OPENVSWITCH_SHA256 and NETOS_OPENVSWITCH_LICENSE_SHA256 env vars "
            "with the correct checksums for this version."
        )
    OPENVSWITCH_SHA256 = _custom_sha256
    OPENVSWITCH_LICENSE_SHA256 = _custom_license_sha256
else:
    OPENVSWITCH_SHA256, OPENVSWITCH_LICENSE_SHA256 = _OPENVSWITCH_KNOWN_SHA256[OPENVSWITCH_VERSION]

class NetOSBuildrootBuilder:
    """Builds the 4stm4 netOS rootfs from source using Buildroot."""

    def __init__(
        self,
        rootfs_path: Path,
        temp_path: Path,
        target: TargetConfig,
        extra_packages: "list[str] | tuple[str, ...] | None" = None,
        cache_policy: str = "",
        extra_groups: "list[str] | tuple[str, ...] | None" = None,
    ):
        self.rootfs_path = Path(rootfs_path)
        self.temp_path = Path(temp_path)
        self.target = target
        self.extra_packages: list[str] = list(extra_packages) if extra_packages else []
        self.extra_groups: list[str] = list(extra_groups) if extra_groups else []
        # cache_policy: explicit arg > env var > default "use"
        self.cache_policy = (
            cache_policy
            or os.environ.get("NETOS_CACHE_POLICY", "use")
        )
        self.buildroot_dir = self.temp_path / f"buildroot-{BUILDROOT_VERSION}"
        self.external_dir = self.temp_path / "netos-buildroot-external"
        self.output_dir = self.temp_path / f"buildroot-output-{target.name}"
        self.defconfig_name = f"netos_{target.name.replace('-', '_')}_defconfig"

    def bootstrap(self):
        self.temp_path.mkdir(parents=True, exist_ok=True)
        self.rootfs_path.mkdir(parents=True, exist_ok=True)
        self._prepare_buildroot()
        self._write_external_tree()
        self._configure_buildroot()
        self._restore_toolchain_cache()      # M3 — skip ~45min gcc build
        if not self._restore_rootfs_cache(): # M5 — skip ~45min package build
            self._build_rootfs()
            self._pack_rootfs_cache()        # M5 — save rootfs for next run
        self._extract_rootfs()
        self._pack_toolchain_cache()         # M3 — save toolchain for next run
        # Save toolchain hash after a successful build so next run can detect config changes
        self._save_toolchain_hash()

    def _artifact_manager(self) -> ArtifactManager:
        return ArtifactManager(self.temp_path)

    def _prepare_buildroot(self):
        if (self.buildroot_dir / "Makefile").exists():
            logging.info("Buildroot already exists: %s", self.buildroot_dir)
            return

        logging.info("Fetching Buildroot %s", BUILDROOT_VERSION)
        archive = self._artifact_manager().fetch(
            url=BUILDROOT_URL,
            sha256=BUILDROOT_SHA256,
            filename=f"buildroot-{BUILDROOT_VERSION}.tar.xz",
        )

        extract_tmp = self.temp_path / f"buildroot-{BUILDROOT_VERSION}.extract"
        if extract_tmp.exists():
            shutil.rmtree(extract_tmp)
        extract_tmp.mkdir(parents=True)
        with tarfile.open(archive, "r:xz") as tar:
            tar.extractall(extract_tmp)

        children = [p for p in extract_tmp.iterdir() if p.is_dir()]
        if len(children) != 1:
            raise RuntimeError(f"Unexpected Buildroot archive layout in {extract_tmp}")
        if self.buildroot_dir.exists():
            shutil.rmtree(self.buildroot_dir)
        children[0].rename(self.buildroot_dir)
        shutil.rmtree(extract_tmp)

    def _write_external_tree(self):
        if self.external_dir.exists():
            shutil.rmtree(self.external_dir)

        package_dir = self.external_dir / "package" / "openvswitch"
        board_dir = self.external_dir / "board" / "4stm4" / "netos"
        overlay_dir = board_dir / "rootfs_overlay"
        configs_dir = self.external_dir / "configs"
        package_dir.mkdir(parents=True)
        overlay_dir.mkdir(parents=True)
        configs_dir.mkdir(parents=True)

        (self.external_dir / "external.desc").write_text(
            "name: NETOS\n"
            "desc: 4stm4 netOS source-built root filesystem\n"
        )
        (self.external_dir / "Config.in").write_text(
            'source "$BR2_EXTERNAL_NETOS_PATH/package/openvswitch/Config.in"\n'
        )
        (self.external_dir / "external.mk").write_text(
            "include $(sort $(wildcard $(BR2_EXTERNAL_NETOS_PATH)/package/*/*.mk))\n"
        )

        (package_dir / "Config.in").write_text(self._openvswitch_config_in())
        (package_dir / "openvswitch.mk").write_text(self._openvswitch_mk())
        (package_dir / "openvswitch.hash").write_text(self._openvswitch_hash())

        self._write_overlay(overlay_dir)
        post_build = board_dir / "post-build.sh"
        post_build.write_text(self._post_build_script())
        post_build.chmod(0o755)

        (configs_dir / self.defconfig_name).write_text(self._defconfig())

    def _openvswitch_config_in(self) -> str:
        return """config BR2_PACKAGE_OPENVSWITCH
\tbool "openvswitch"
\tdepends on BR2_USE_MMU
\tdepends on BR2_TOOLCHAIN_HAS_THREADS
\tdepends on !BR2_STATIC_LIBS
\tselect BR2_PACKAGE_LIBCAP_NG
\tselect BR2_PACKAGE_OPENSSL
\tselect BR2_PACKAGE_PYTHON3
\tselect BR2_PACKAGE_PYTHON3_SSL
\tselect BR2_PACKAGE_PYTHON3_ZLIB
\thelp
\t  Open vSwitch userspace tools, ovsdb-server, ovs-vswitchd and
\t  Python modules required by 4stm4 netOS agents.

\t  https://www.openvswitch.org/

comment "openvswitch needs a toolchain w/ threads, dynamic library"
\tdepends on BR2_USE_MMU
\tdepends on !BR2_TOOLCHAIN_HAS_THREADS || BR2_STATIC_LIBS
"""

    def _openvswitch_mk(self) -> str:
        return f"""################################################################################
#
# openvswitch
#
################################################################################

OPENVSWITCH_VERSION = {OPENVSWITCH_VERSION}
OPENVSWITCH_SOURCE = openvswitch-$(OPENVSWITCH_VERSION).tar.gz
OPENVSWITCH_SITE = https://www.openvswitch.org/releases
OPENVSWITCH_LICENSE = Apache-2.0
OPENVSWITCH_LICENSE_FILES = LICENSE
OPENVSWITCH_DEPENDENCIES = host-pkgconf host-python3 libcap-ng openssl python3
OPENVSWITCH_CONF_ENV = PYTHON3=$(HOST_DIR)/bin/python3

define OPENVSWITCH_INSTALL_PYTHON_MODULES
\t$(INSTALL) -d $(TARGET_DIR)/usr/lib/python$(PYTHON3_VERSION_MAJOR)/site-packages
\tif [ -d $(TARGET_DIR)/usr/share/openvswitch/python/ovs ]; then \\
\t\tcp -a $(TARGET_DIR)/usr/share/openvswitch/python/ovs \\
\t\t\t$(TARGET_DIR)/usr/lib/python$(PYTHON3_VERSION_MAJOR)/site-packages/; \\
\tfi
endef
OPENVSWITCH_POST_INSTALL_TARGET_HOOKS += OPENVSWITCH_INSTALL_PYTHON_MODULES

$(eval $(autotools-package))
"""

    def _openvswitch_hash(self) -> str:
        return f"""# Locally calculated
sha256  {OPENVSWITCH_SHA256}  openvswitch-{OPENVSWITCH_VERSION}.tar.gz
sha256  {OPENVSWITCH_LICENSE_SHA256}  LICENSE
"""

    def _write_overlay(self, overlay_dir: Path):
        profile_dir = overlay_dir / "etc" / "profile.d"
        profile_dir.mkdir(parents=True)
        (profile_dir / "netos.sh").write_text(
            "export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin\n"
        )
        (overlay_dir / "etc").mkdir(exist_ok=True)
        (overlay_dir / "etc" / "motd").write_text(f"{NETOS_NAME} {NETOS_VERSION}\n")

    def _post_build_script(self) -> str:
        return f"""#!/bin/sh
set -eu

TARGET_DIR="$1"

rm -f "$TARGET_DIR/etc/os-release" "$TARGET_DIR/usr/lib/os-release"

cat > "$TARGET_DIR/etc/issue" <<'EOF'
{NETOS_NAME} {NETOS_VERSION} \\n \\l

EOF

echo "{NETOS_HOSTNAME}" > "$TARGET_DIR/etc/hostname"
sed -i -e 's,^root:[^:]*:,root::,' "$TARGET_DIR/etc/passwd"
if [ -f "$TARGET_DIR/etc/shadow" ]; then
    sed -i -e 's,^root:[^:]*:,root::,' "$TARGET_DIR/etc/shadow"
fi
"""

    def _defconfig(self) -> str:
        from netos_build.catalog import PackageCatalog, DEFAULT_GROUPS
        catalog = PackageCatalog.load()

        # Base packages from catalog default groups
        package_lines: list[str] = catalog.resolve_groups(list(DEFAULT_GROUPS))

        # Extra groups requested via --groups CLI flag (stored in extra_groups)
        if self.extra_groups:
            unknown = [g for g in self.extra_groups if not catalog.has_group(g)]
            if unknown:
                raise ValueError(
                    f"Unknown package group(s): {', '.join(unknown)}. "
                    f"Available: {', '.join(catalog.group_names())}"
                )
            extras = catalog.resolve_groups(list(self.extra_groups))
            for pkg in extras:
                if pkg not in package_lines:
                    package_lines.append(pkg)

        # Target-specific packages (e.g. wireless for zero2w)
        for pkg in self.target.buildroot_package_lines:
            if pkg not in package_lines:
                package_lines.append(pkg)

        # Extra raw BR2_PACKAGE_*=y lines from --packages-file or API callers
        for pkg in self.extra_packages:
            if pkg not in package_lines:
                package_lines.append(pkg)

        if self.target.name == "pi5" and os.environ.get("NETOS_INCLUDE_QEMU", "0") == "1":
            for pkg in [
                "BR2_PACKAGE_QEMU=y",
                "BR2_PACKAGE_QEMU_SYSTEM=y",
                "BR2_PACKAGE_QEMU_SYSTEM_KVM=y",
                "BR2_PACKAGE_QEMU_SYSTEM_TCG=y",
                "BR2_PACKAGE_QEMU_CHOOSE_TARGETS=y",
                "BR2_PACKAGE_QEMU_TARGET_AARCH64=y",
            ]:
                if pkg not in package_lines:
                    package_lines.append(pkg)

        br2_arch = f"BR2_{self.target.buildroot_arch}=y"
        return "\n".join(
            [
                br2_arch,
                "BR2_TOOLCHAIN_BUILDROOT_GLIBC=y",
                "BR2_TOOLCHAIN_BUILDROOT_CXX=y",
                f'BR2_TARGET_GENERIC_HOSTNAME="{NETOS_HOSTNAME}"',
                f'BR2_TARGET_GENERIC_ISSUE="{NETOS_NAME} {NETOS_VERSION}"',
                'BR2_SYSTEM_DHCP="eth0"',
                'BR2_ROOTFS_OVERLAY="$(BR2_EXTERNAL_NETOS_PATH)/board/4stm4/netos/rootfs_overlay"',
                'BR2_ROOTFS_POST_BUILD_SCRIPT="$(BR2_EXTERNAL_NETOS_PATH)/board/4stm4/netos/post-build.sh"',
                *package_lines,
                "",
            ]
        )

    def _toolchain_hash(self) -> str:
        """Hash of toolchain-relevant defconfig fields; used to detect when gcc-final must be rebuilt."""
        import hashlib as _hashlib
        parts = [
            f"arch={self.target.buildroot_arch}",
            f"kernel_source={self.target.kernel_source}",
            f"kernel_arch={self.target.kernel_arch}",
            f"cross_compile={self.target.cross_compile}",
            "BR2_TOOLCHAIN_BUILDROOT_GLIBC=y",
            "BR2_TOOLCHAIN_BUILDROOT_CXX=y",
        ]
        return _hashlib.md5("\n".join(parts).encode()).hexdigest()

    _HASH_FILE = ".last_toolchain_hash"

    def _read_saved_toolchain_hash(self) -> str:
        p = self.output_dir / self._HASH_FILE
        return p.read_text().strip() if p.exists() else ""

    def _save_toolchain_hash(self) -> None:
        (self.output_dir / self._HASH_FILE).write_text(self._toolchain_hash())

    def _clear_gcc_final_stamps(self) -> None:
        """Remove gcc-final build stamps so Buildroot reconfigures GCC with updated options."""
        import glob as _glob
        build_dir = self.output_dir / "build"
        # Virtual toolchain packages
        for d in ["toolchain-buildroot", "toolchain-buildroot-aux", "toolchain-buildroot-initial"]:
            stamp_dir = build_dir / d
            if stamp_dir.exists():
                shutil.rmtree(stamp_dir)
        # host-gcc-final stamps that lock in --enable-languages
        for gcc_dir in _glob.glob(str(build_dir / "host-gcc-final-*")):
            for stamp in ["built", "configured", "host_installed", "installed",
                          "staging_installed", "target_installed"]:
                p = Path(gcc_dir) / f".stamp_{stamp}"
                if p.exists():
                    p.unlink()
        # Remove stale cross-compiler binaries so the stale-check in the configurator resets
        prefix = f"{self.target.buildroot_arch}-buildroot-linux-gnu"
        for suffix in ["-g++", "-c++"]:
            b = self.output_dir / "host" / "bin" / f"{prefix}{suffix}"
            if b.exists():
                b.unlink()
        logging.info("Cleared gcc-final stamps — toolchain will be reconfigured with updated options")

    def _configure_buildroot(self):
        logging.info("Configuring Buildroot defconfig: %s", self.defconfig_name)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Auto-detect toolchain config changes and clear gcc-final stamps before re-configuring
        current_hash = self._toolchain_hash()
        saved_hash   = self._read_saved_toolchain_hash()
        if saved_hash and saved_hash != current_hash:
            logging.warning(
                "Toolchain config changed since last build (hash %s → %s); "
                "clearing gcc-final stamps to force C++ rebuild",
                saved_hash[:8], current_hash[:8],
            )
            self._clear_gcc_final_stamps()

        subprocess.run(
            [
                "make",
                "-C",
                str(self.buildroot_dir),
                f"O={self.output_dir}",
                f"BR2_EXTERNAL={self.external_dir}",
                self.defconfig_name,
            ],
            check=True,
        )

    def _build_rootfs(self):
        jobs = os.environ.get("NETOS_BUILD_JOBS", str(os.cpu_count() or 1))
        logging.info("Building 4stm4 netOS rootfs with Buildroot (-j%s)", jobs)
        self._clear_target_os_release_links()
        subprocess.run(
            ["make", "-C", str(self.buildroot_dir), f"O={self.output_dir}", f"-j{jobs}"],
            check=True,
        )

    def _clear_target_os_release_links(self):
        for rel_path in ("target/etc/os-release", "target/usr/lib/os-release"):
            path = self.output_dir / rel_path
            if path.exists() or path.is_symlink():
                path.unlink()

    # ------------------------------------------------------------------
    # Toolchain cache (M3)
    # ------------------------------------------------------------------

    def _build_plan(self):
        """Return a ResolvedBuildPlan for the current target (lazy import)."""
        from netos_build.plan import ResolvedBuildPlan
        return ResolvedBuildPlan.from_target(
            self.target,
            extra_packages=self.extra_packages,
            cache_policy=self.cache_policy,
        )

    def _restore_toolchain_cache(self) -> None:
        """Try to restore a pre-built toolchain from cache.

        Called after defconfig and before ``make`` so Buildroot sees the
        existing stamps and skips the ~45-min GCC build.
        """
        if self.cache_policy == "rebuild":
            logging.info("cache_policy=rebuild — skipping toolchain cache restore")
            return

        from netos_build.toolchain_cache import ToolchainCache
        plan     = self._build_plan()
        tc_cache = ToolchainCache(self.temp_path / "cache")
        key      = tc_cache.cache_key(plan, BUILDROOT_VERSION)

        if tc_cache.has(plan, BUILDROOT_VERSION):
            logging.info("Toolchain cache hit: %s", key)
            if tc_cache.restore(plan, BUILDROOT_VERSION, self.output_dir):
                return
            # Restore failed (corrupt archive already deleted) — fall through to rebuild

        logging.info("Toolchain cache miss: %s — full GCC build required (~45 min)", key)

    def _pack_toolchain_cache(self) -> None:
        """Pack the just-built toolchain into the cache for future use.

        Non-fatal: if packing fails the build is still considered successful.
        Skipped if the cache already has an entry for this key.
        """
        if self.cache_policy == "rebuild":
            return

        from netos_build.toolchain_cache import ToolchainCache
        plan     = self._build_plan()
        tc_cache = ToolchainCache(self.temp_path / "cache")

        if tc_cache.has(plan, BUILDROOT_VERSION):
            logging.info("Toolchain already cached — skipping pack")
            return

        # Verify that GCC was actually compiled into host/
        prefix  = f"{self.target.buildroot_arch}-buildroot-linux-gnu"
        gcc_bin = self.output_dir / "host" / "bin" / f"{prefix}-gcc"
        if not gcc_bin.exists():
            logging.warning(
                "GCC binary not found at %s — toolchain not cached", gcc_bin
            )
            return

        try:
            tc_cache.pack(plan, BUILDROOT_VERSION, self.output_dir)
        except Exception as exc:
            logging.error(
                "Failed to pack toolchain to cache (non-fatal): %s", exc
            )

    # ------------------------------------------------------------------
    # Rootfs cache (M5)
    # ------------------------------------------------------------------

    def _restore_rootfs_cache(self) -> bool:
        """Try to restore a pre-built rootfs.tar from cache.

        Called after defconfig + toolchain restore and *before* ``make`` so
        the expensive package-compilation step is skipped entirely when the
        package set hasn't changed.

        Returns True if rootfs.tar was successfully restored (caller must
        skip _build_rootfs).  Returns False on cache miss or restore failure.
        """
        if self.cache_policy in ("rebuild", "refresh"):
            logging.info("cache_policy=%s — skipping rootfs cache restore", self.cache_policy)
            return False

        from netos_build.rootfs_cache import RootfsCache
        plan      = self._build_plan()
        rc_cache  = RootfsCache(self.temp_path / "cache")
        key       = rc_cache.cache_key(plan, BUILDROOT_VERSION)

        if rc_cache.has(plan, BUILDROOT_VERSION):
            logging.info("Rootfs cache hit: %s", key)
            if rc_cache.restore(plan, BUILDROOT_VERSION, self.output_dir):
                return True
            # Restore failed (corrupt archive deleted) — fall through to rebuild

        logging.info(
            "Rootfs cache miss: %s — full Buildroot make required (~45 min)", key
        )
        return False

    def _pack_rootfs_cache(self) -> None:
        """Pack the just-built rootfs.tar into the cache for future use.

        Non-fatal: if packing fails the build is still considered successful.
        Skipped if the cache already has an entry for this key, or if
        cache_policy == "rebuild".
        """
        if self.cache_policy == "rebuild":
            return

        from netos_build.rootfs_cache import RootfsCache
        plan     = self._build_plan()
        rc_cache = RootfsCache(self.temp_path / "cache")

        if rc_cache.has(plan, BUILDROOT_VERSION):
            if self.cache_policy != "refresh":
                logging.info("Rootfs already cached — skipping pack")
                return

        rootfs_tar = self.output_dir / "images" / "rootfs.tar"
        if not rootfs_tar.exists():
            logging.warning("rootfs.tar not found — rootfs not cached")
            return

        try:
            rc_cache.pack(plan, BUILDROOT_VERSION, self.output_dir)
        except Exception as exc:
            logging.error(
                "Failed to pack rootfs to cache (non-fatal): %s", exc
            )

    # ------------------------------------------------------------------

    def _extract_rootfs(self):
        rootfs_tar = self.output_dir / "images" / "rootfs.tar"
        if not rootfs_tar.exists():
            raise FileNotFoundError(f"Buildroot rootfs archive not found: {rootfs_tar}")
        logging.info("Extracting Buildroot rootfs into %s", self.rootfs_path)
        # Device nodes and setuid bits require root to extract correctly.
        # Try fakeroot first (preserves metadata without real root), fall back to sudo.
        if shutil.which("fakeroot"):
            subprocess.run(
                ["fakeroot", "tar", "-xf", str(rootfs_tar), "-C", str(self.rootfs_path)],
                check=True,
            )
        else:
            logging.warning(
                "fakeroot not found; falling back to sudo tar for device node extraction"
            )
            subprocess.run(
                ["sudo", "tar", "-xf", str(rootfs_tar), "-C", str(self.rootfs_path)],
                check=True,
            )
