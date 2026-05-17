import hashlib
import logging
import os
import shutil
import subprocess
import tarfile
import urllib.request
from pathlib import Path

from netos_branding import NETOS_HOSTNAME, NETOS_ID, NETOS_NAME, NETOS_VERSION
from targets import TargetConfig


BUILDROOT_VERSION = os.environ.get("NETOS_BUILDROOT_VERSION", "2026.02.1")
BUILDROOT_URL = os.environ.get(
    "NETOS_BUILDROOT_URL",
    f"https://buildroot.org/downloads/buildroot-{BUILDROOT_VERSION}.tar.xz",
)
BUILDROOT_SHA256 = os.environ.get(
    "NETOS_BUILDROOT_SHA256",
    "a2216fdc46b5e81e529acb9077324f7b4a9403366922f350bf7be67f46231b66",
)

OPENVSWITCH_VERSION = os.environ.get("NETOS_OPENVSWITCH_VERSION", "3.4.1")
OPENVSWITCH_SHA256 = "6e97ec7dfdda5b40b5103946d53e4f8b11edf66049fedbdcb323e1af67133de8"
OPENVSWITCH_LICENSE_SHA256 = "f41f887b04dd604250193ddd88691ecd168dacdecca2d0d6581d8840e3f0b0dc"

class NetOSBuildrootBuilder:
    """Builds the 4stm4 NetOS rootfs from source using Buildroot."""

    def __init__(self, rootfs_path: Path, temp_path: Path, target: TargetConfig):
        self.rootfs_path = Path(rootfs_path)
        self.temp_path = Path(temp_path)
        self.target = target
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
        self._build_rootfs()
        self._extract_rootfs()

    def _prepare_buildroot(self):
        if (self.buildroot_dir / "Makefile").exists():
            logging.info("Buildroot already exists: %s", self.buildroot_dir)
            return

        archive = self.temp_path / f"buildroot-{BUILDROOT_VERSION}.tar.xz"
        logging.info("Downloading Buildroot %s from %s", BUILDROOT_VERSION, BUILDROOT_URL)
        self._download(BUILDROOT_URL, archive)
        self._verify_sha256(archive, BUILDROOT_SHA256)

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

    def _download(self, url: str, destination: Path):
        if destination.exists():
            logging.info("Using cached archive: %s", destination)
            return
        destination.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(url) as response, destination.open("wb") as out:
            shutil.copyfileobj(response, out)

    def _verify_sha256(self, path: Path, expected: str):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != expected:
            raise RuntimeError(f"SHA256 mismatch for {path}: got {digest}, expected {expected}")

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
            "desc: 4stm4 NetOS source-built root filesystem\n"
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
\t  Python modules required by 4stm4 NetOS agents.

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
"""

    def _defconfig(self) -> str:
        package_lines = [
            "BR2_PACKAGE_BUSYBOX=y",
            "BR2_PACKAGE_BUSYBOX_SHOW_OTHERS=y",
            "BR2_PACKAGE_BASH=y",
            "BR2_PACKAGE_CA_CERTIFICATES=y",
            "BR2_PACKAGE_GIT=y",
            "BR2_PACKAGE_LIBCURL=y",
            "BR2_PACKAGE_LIBCURL_CURL=y",
            "BR2_PACKAGE_LIBCURL_OPENSSL=y",
            "BR2_PACKAGE_IPROUTE2=y",
            "BR2_PACKAGE_IPSET=y",
            "BR2_PACKAGE_NFTABLES=y",
            "BR2_PACKAGE_NFTABLES_JSON=y",
            "BR2_PACKAGE_CONNTRACK_TOOLS=y",
            "BR2_PACKAGE_WIREGUARD_TOOLS=y",
            "BR2_PACKAGE_DNSMASQ=y",
            "BR2_PACKAGE_VNSTAT=y",
            "BR2_PACKAGE_TCPDUMP=y",
            "BR2_PACKAGE_IFTOP=y",
            "BR2_PACKAGE_NETHOGS=y",
            "BR2_PACKAGE_SYSSTAT=y",
            "BR2_PACKAGE_ETHTOOL=y",
            "BR2_PACKAGE_BIND=y",
            "BR2_PACKAGE_BIND_TOOLS=y",
            "BR2_PACKAGE_UTIL_LINUX=y",
            "BR2_PACKAGE_UTIL_LINUX_BINARIES=y",
            "BR2_PACKAGE_UTIL_LINUX_AGETTY=y",
            "BR2_PACKAGE_UTIL_LINUX_MOUNT=y",
            "BR2_PACKAGE_UTIL_LINUX_MOUNTPOINT=y",
            "BR2_PACKAGE_UTIL_LINUX_LOSETUP=y",
            "BR2_PACKAGE_E2FSPROGS=y",
            "BR2_PACKAGE_E2FSPROGS_FSCK=y",
            "BR2_PACKAGE_E2FSPROGS_RESIZE2FS=y",
            "BR2_PACKAGE_KMOD=y",
            "BR2_PACKAGE_KMOD_TOOLS=y",
            "BR2_PACKAGE_DROPBEAR=y",
            "BR2_PACKAGE_PYTHON3=y",
            "BR2_PACKAGE_PYTHON3_SSL=y",
            "BR2_PACKAGE_PYTHON3_ZLIB=y",
            "BR2_PACKAGE_PYTHON3_PYEXPAT=y",
            "BR2_PACKAGE_PYTHON3_READLINE=y",
            "BR2_PACKAGE_PYTHON3_SQLITE=y",
            "BR2_PACKAGE_PYTHON_PIP=y",
            "BR2_PACKAGE_PYTHON_ALEMBIC=y",
            "BR2_PACKAGE_PYTHON_AIOSQLITE=y",
            "BR2_PACKAGE_PYTHON_ASYNCSSH=y",
            "BR2_PACKAGE_PYTHON_BCRYPT=y",
            "BR2_PACKAGE_PYTHON_BOTO3=y",
            "BR2_PACKAGE_PYTHON_CRYPTOGRAPHY=y",
            "BR2_PACKAGE_PYTHON_DATEUTIL=y",
            "BR2_PACKAGE_PYTHON_DJANGO=y",
            "BR2_PACKAGE_PYTHON_DOTENV=y",
            "BR2_PACKAGE_PYTHON_FASTAPI=y",
            "BR2_PACKAGE_PYTHON_GUNICORN=y",
            "BR2_PACKAGE_PYTHON_HTTPX=y",
            "BR2_PACKAGE_PYTHON_ITSDANGEROUS=y",
            "BR2_PACKAGE_PYTHON_JINJA2=y",
            "BR2_PACKAGE_PYTHON_PACKAGING=y",
            "BR2_PACKAGE_PYTHON_PASSLIB=y",
            "BR2_PACKAGE_PYTHON_PYDANTIC=y",
            "BR2_PACKAGE_PYTHON_PYJWT=y",
            "BR2_PACKAGE_PYTHON_PYYAML=y",
            "BR2_PACKAGE_PYTHON_REQUESTS=y",
            "BR2_PACKAGE_PYTHON_SQLALCHEMY=y",
            "BR2_PACKAGE_PYTHON_STARLETTE=y",
            "BR2_PACKAGE_PYTHON_UVICORN=y",
            "BR2_PACKAGE_OPENVSWITCH=y",
            "BR2_PACKAGE_OPEN_ISCSI=y",
            "BR2_PACKAGE_SOCAT=y",
            "BR2_TARGET_ROOTFS_TAR=y",
            "BR2_TARGET_ROOTFS_TAR_NONE=y",
        ]

        package_lines.extend(self.target.buildroot_package_lines)

        if self.target.name == "pi5" and os.environ.get("NETOS_INCLUDE_QEMU", "0") == "1":
            package_lines.extend(
                [
                    "BR2_PACKAGE_QEMU=y",
                    "BR2_PACKAGE_QEMU_SYSTEM=y",
                    "BR2_PACKAGE_QEMU_SYSTEM_KVM=y",
                    "BR2_PACKAGE_QEMU_SYSTEM_TCG=y",
                    "BR2_PACKAGE_QEMU_CHOOSE_TARGETS=y",
                    "BR2_PACKAGE_QEMU_TARGET_AARCH64=y",
                ]
            )

        return "\n".join(
            [
                "BR2_aarch64=y",
                "BR2_TOOLCHAIN_BUILDROOT_GLIBC=y",
                f'BR2_TARGET_GENERIC_HOSTNAME="{NETOS_HOSTNAME}"',
                f'BR2_TARGET_GENERIC_ISSUE="{NETOS_NAME} {NETOS_VERSION}"',
                'BR2_SYSTEM_DHCP="eth0"',
                'BR2_ROOTFS_OVERLAY="$(BR2_EXTERNAL_NETOS_PATH)/board/4stm4/netos/rootfs_overlay"',
                'BR2_ROOTFS_POST_BUILD_SCRIPT="$(BR2_EXTERNAL_NETOS_PATH)/board/4stm4/netos/post-build.sh"',
                *package_lines,
                "",
            ]
        )

    def _configure_buildroot(self):
        logging.info("Configuring Buildroot defconfig: %s", self.defconfig_name)
        self.output_dir.mkdir(parents=True, exist_ok=True)
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
        logging.info("Building 4stm4 NetOS rootfs with Buildroot (-j%s)", jobs)
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

    def _extract_rootfs(self):
        rootfs_tar = self.output_dir / "images" / "rootfs.tar"
        if not rootfs_tar.exists():
            raise FileNotFoundError(f"Buildroot rootfs archive not found: {rootfs_tar}")
        logging.info("Extracting Buildroot rootfs into %s", self.rootfs_path)
        subprocess.run(["tar", "-xf", str(rootfs_tar), "-C", str(self.rootfs_path)], check=True)
