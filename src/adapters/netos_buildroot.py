import collections
import logging
import os
import re
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

NANODHCP_VERSION = os.environ.get(
    "NETOS_NANODHCP_VERSION",
    "ec0081fbf50185d90475a2ce929dbd93244a1ef9",
)
NANODHCP_SHA256 = os.environ.get(
    "NETOS_NANODHCP_SHA256",
    "8570b6b3ed92a2d722c75fe6964eeefb42c5374ce8396ddb07b1fb1143ce9670",
)

# nanodns и tinywifi пинятся веткой (по умолчанию main) — сборщик берёт свежий
# код с GitHub при каждой сборке. SHA256 для ветки не фиксируем: тарбол ветки
# меняется, поэтому проверка хэша только мешала бы (цена — невоспроизводимость).
NANODNS_VERSION = os.environ.get("NETOS_NANODNS_VERSION", "main")
TINYWIFI_VERSION = os.environ.get("NETOS_TINYWIFI_VERSION", "main")

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
        cache_dir: "Path | None" = None,
        groups_override: "list[str] | None" = None,
    ):
        self.rootfs_path = Path(rootfs_path)
        self.temp_path = Path(temp_path)
        self.target = target
        self.extra_packages: list[str] = list(extra_packages) if extra_packages else []
        self.extra_groups: list[str] = list(extra_groups) if extra_groups else []
        # None → используем DEFAULT_GROUPS; [] → только extra_packages + target lines
        self.groups_override: "list[str] | None" = groups_override
        # cache_policy: explicit arg > env var > default "use"
        self.cache_policy = (
            cache_policy
            or os.environ.get("NETOS_CACHE_POLICY", "use")
        )
        self.buildroot_dir = self.temp_path / f"buildroot-{BUILDROOT_VERSION}"
        self.external_dir = self.temp_path / "netos-buildroot-external"
        self.output_dir = self.temp_path / f"buildroot-output-{target.name}"
        self.defconfig_name = f"netos_{target.name.replace('-', '_')}_defconfig"
        # cache_dir: explicit arg > NETOS_CACHE_DIR env var > <temp_path>/cache
        _env_cache = os.environ.get("NETOS_CACHE_DIR", "")
        self._cache_root: Path = (
            cache_dir
            or (Path(_env_cache) if _env_cache else self.temp_path / "cache")
        )

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

        ovs_dir        = self.external_dir / "package" / "openvswitch"
        mininet_dir    = self.external_dir / "package" / "mininet"
        nanodhcp_dir   = self.external_dir / "package" / "nanodhcp"
        nanodns_dir    = self.external_dir / "package" / "nanodns"
        tinywifi_dir   = self.external_dir / "package" / "tinywifi"
        board_dir      = self.external_dir / "board" / "4stm4" / "netos"
        overlay_dir    = board_dir / "rootfs_overlay"
        configs_dir    = self.external_dir / "configs"

        for d in (ovs_dir, mininet_dir, nanodhcp_dir, nanodns_dir, tinywifi_dir, overlay_dir, configs_dir):
            d.mkdir(parents=True)

        (self.external_dir / "external.desc").write_text(
            "name: NETOS\n"
            "desc: 4stm4 netOS source-built root filesystem\n"
        )
        (self.external_dir / "Config.in").write_text(
            'source "$BR2_EXTERNAL_NETOS_PATH/package/openvswitch/Config.in"\n'
            'source "$BR2_EXTERNAL_NETOS_PATH/package/mininet/Config.in"\n'
            'source "$BR2_EXTERNAL_NETOS_PATH/package/nanodhcp/Config.in"\n'
            'source "$BR2_EXTERNAL_NETOS_PATH/package/nanodns/Config.in"\n'
            'source "$BR2_EXTERNAL_NETOS_PATH/package/tinywifi/Config.in"\n'
        )
        (self.external_dir / "external.mk").write_text(
            "include $(sort $(wildcard $(BR2_EXTERNAL_NETOS_PATH)/package/*/*.mk))\n"
        )

        # openvswitch package
        (ovs_dir / "Config.in").write_text(self._openvswitch_config_in())
        (ovs_dir / "openvswitch.mk").write_text(self._openvswitch_mk())
        (ovs_dir / "openvswitch.hash").write_text(self._openvswitch_hash())

        # mininet package — shell-script package, local source in external tree
        (mininet_dir / "Config.in").write_text(self._mininet_config_in())
        (mininet_dir / "mininet.mk").write_text(self._mininet_mk())
        # Script files that mininet.mk will install into the rootfs
        (mininet_dir / "mininet").write_text(self._mininet_script())
        (mininet_dir / "mininet").chmod(0o755)
        (mininet_dir / "S99mininet").write_text(self._mininet_init_script())
        (mininet_dir / "S99mininet").chmod(0o755)
        (mininet_dir / "config.startup").write_text(self._mininet_default_config())

        # nanodhcp package — Rust/Cargo, downloaded from GitHub
        (nanodhcp_dir / "Config.in").write_text(self._nanodhcp_config_in())
        (nanodhcp_dir / "nanodhcp.mk").write_text(self._nanodhcp_mk())
        (nanodhcp_dir / "nanodhcp.hash").write_text(self._nanodhcp_hash())
        (nanodhcp_dir / "0001-fix-Cargo.lock-version.patch").write_text(self._nanodhcp_cargo_lock_patch())
        (nanodhcp_dir / "S10nanodhcp").write_text(self._nanodhcp_init_script())
        (nanodhcp_dir / "S10nanodhcp").chmod(0o755)
        (nanodhcp_dir / "nanodhcp.conf").write_text(self._nanodhcp_default_config())

        # nanodns package — Rust/Cargo, downloaded from GitHub (branch-tracked)
        (nanodns_dir / "Config.in").write_text(self._nanodns_config_in())
        (nanodns_dir / "nanodns.mk").write_text(self._nanodns_mk())
        (nanodns_dir / "S11nanodns").write_text(self._nanodns_init_script())
        (nanodns_dir / "S11nanodns").chmod(0o755)
        (nanodns_dir / "nanodns.conf").write_text(self._nanodns_default_config())
        (nanodns_dir / "blocklist").write_text(self._nanodns_default_blocklist())

        # tinywifi package — Rust/Cargo web panel, downloaded from GitHub (branch-tracked)
        (tinywifi_dir / "Config.in").write_text(self._tinywifi_config_in())
        (tinywifi_dir / "tinywifi.mk").write_text(self._tinywifi_mk())

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

    # ------------------------------------------------------------------
    # Mininet package generators
    # ------------------------------------------------------------------

    def _mininet_config_in(self) -> str:
        return """\
config BR2_PACKAGE_MININET
\tbool "mininet"
\tdepends on BR2_USE_MMU
\tselect BR2_PACKAGE_IPROUTE2
\tselect BR2_PACKAGE_DNSMASQ
\thelp
\t  Minimal network configurator for netos/QEMU images.
\t  Reads /etc/mininet/config.startup at boot, configures
\t  interfaces with iproute2, and starts dnsmasq as a DHCP
\t  server for each interface that has a dhcp-range directive.
\t
\t  Installs:
\t    /usr/sbin/mininet         — config applier + DHCP launcher
\t    /etc/mininet/config.startup — startup configuration template
\t    /etc/init.d/S99mininet    — BusyBox init script
\t    /var/lib/mininet/         — persistent state directory
"""

    def _mininet_mk(self) -> str:
        return """\
################################################################################
#
# mininet — netos minimal network configurator
#
################################################################################

MININET_VERSION       = 1.0
MININET_SITE          = $(BR2_EXTERNAL_NETOS_PATH)/package/mininet
MININET_SITE_METHOD   = local
MININET_LICENSE       = MIT

# No upstream source to configure or compile — pure shell-script package.
MININET_CONFIGURE_CMDS =
MININET_BUILD_CMDS     =

define MININET_INSTALL_TARGET_CMDS
\t$(INSTALL) -D -m 0755 $(@D)/mininet        $(TARGET_DIR)/usr/sbin/mininet
\t$(INSTALL) -D -m 0755 $(@D)/S99mininet     $(TARGET_DIR)/etc/init.d/S99mininet
\t$(INSTALL) -D -m 0644 $(@D)/config.startup $(TARGET_DIR)/etc/mininet/config.startup
\tmkdir -p $(TARGET_DIR)/var/lib/mininet
endef

$(eval $(generic-package))
"""

    def _mininet_script(self) -> str:
        return """\
#!/bin/sh
# /usr/sbin/mininet — netos network configurator
#
# Reads /etc/mininet/config.startup, configures interfaces via iproute2,
# and starts dnsmasq for interfaces with a dhcp-range directive.
#
# Usage: mininet {start|stop|restart|status}
set -e

CFG=/etc/mininet/config.startup
RUN=/run/mininet
LOG=/var/log/mininet.log
DNSMASQ_CONF=$RUN/dnsmasq.conf
DNSMASQ_PID=$RUN/dnsmasq.pid
DNSMASQ_LEASES=$RUN/dnsmasq.leases

_log() { printf '[mininet] %s\\n' "$*" | tee -a "$LOG"; }

_parse_and_apply() {
    [ -f "$CFG" ] || { _log "no config at $CFG — nothing to do"; return 0; }
    local iface=""
    while IFS= read -r raw; do
        # Strip comments and blank lines
        local line="${raw%%#*}"
        line="${line#"${line%%[! ]*}"}"
        [ -z "$line" ] && continue

        local key="${line%% *}"
        local val="${line#"$key"}"
        val="${val#"${val%%[! ]*}"}"   # ltrim val

        case "$key" in
            interface)
                iface="$val"
                _log "interface $iface: up"
                ip link set "$iface" up 2>/dev/null || true
                ;;
            address)
                _log "$iface: address $val"
                ip addr replace "$val" dev "$iface" 2>/dev/null || true
                ;;
            gateway)
                _log "default gateway $val"
                ip route replace default via "$val" 2>/dev/null || true
                ;;
            dhcp-range)
                # Syntax: <start>,<end>,<lease>  e.g. 10.0.0.10,10.0.0.100,12h
                printf 'interface=%s\\ndhcp-range=%s\\n' "$iface" "$val" \
                    >> "$DNSMASQ_CONF"
                ;;
            dns)
                # Syntax: <ip> [<ip>...]  upstream resolvers forwarded by dnsmasq
                for ns in $val; do
                    printf 'server=%s\\n' "$ns" >> "$DNSMASQ_CONF"
                done
                ;;
            route)
                # Syntax: <dest/prefix> via <gw>
                _log "route $val"
                ip route replace $val 2>/dev/null || true
                ;;
        esac
    done < "$CFG"
}

_start_dnsmasq() {
    grep -q '^dhcp-range=' "$DNSMASQ_CONF" 2>/dev/null || return 0
    _log "starting dnsmasq"
    dnsmasq --conf-file="$DNSMASQ_CONF"
}

start() {
    _log "starting mininet"
    mkdir -p "$RUN" /var/lib/mininet
    # Base dnsmasq config (overwritten on each start)
    cat > "$DNSMASQ_CONF" <<CONF
# Generated by mininet — do not edit manually
pid-file=$DNSMASQ_PID
dhcp-leasefile=$DNSMASQ_LEASES
no-resolv
no-hosts
log-dhcp
CONF
    ip link set lo up 2>/dev/null || true
    _parse_and_apply
    _start_dnsmasq
    _log "mininet ready"
}

stop() {
    _log "stopping mininet"
    if [ -f "$DNSMASQ_PID" ]; then
        kill "$(cat "$DNSMASQ_PID")" 2>/dev/null || true
        rm -f "$DNSMASQ_PID"
    fi
}

status() {
    if [ -f "$DNSMASQ_PID" ] && kill -0 "$(cat "$DNSMASQ_PID")" 2>/dev/null; then
        echo "mininet: running  (dnsmasq pid=$(cat "$DNSMASQ_PID"))"
        echo "config:  $CFG"
        if command -v ip >/dev/null 2>&1; then
            echo "--- interfaces ---"
            ip -brief addr show
            echo "--- routes ---"
            ip route show
        fi
    else
        echo "mininet: stopped"
    fi
}

case "${1:-help}" in
    start)   start   ;;
    stop)    stop    ;;
    restart) stop; start ;;
    status)  status  ;;
    *) echo "usage: mininet {start|stop|restart|status}"; exit 1 ;;
esac
"""

    def _mininet_init_script(self) -> str:
        return """\
#!/bin/sh
#
# /etc/init.d/S99mininet — BusyBox init script for mininet
# Applies /etc/mininet/config.startup and starts DHCP at boot.
#

case "$1" in
    start)
        printf 'Starting mininet: '
        /usr/sbin/mininet start
        echo "OK"
        ;;
    stop)
        printf 'Stopping mininet: '
        /usr/sbin/mininet stop
        echo "OK"
        ;;
    restart|reload)
        "$0" stop
        "$0" start
        ;;
    status)
        /usr/sbin/mininet status
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status}"
        exit 1
esac

exit $?
"""

    def _mininet_default_config(self) -> str:
        return """\
# /etc/mininet/config.startup — netos network startup configuration
#
# Applied at boot by /etc/init.d/S99mininet.
# Edit this file to configure interfaces, IP addresses, and DHCP pools.
#
# Directives (one per line, # = comment):
#
#   interface <name>               — select interface context for following lines
#   address   <ip/prefix>          — assign IP address (e.g. 10.0.0.1/24)
#   gateway   <ip>                 — default route (e.g. 10.0.0.254)
#   dhcp-range <start>,<end>,<ttl> — enable DHCP server (e.g. 10.0.0.10,10.0.0.100,12h)
#   dns       <ip> [<ip>...]       — upstream DNS servers forwarded by dnsmasq
#   route     <dest/prefix> via <gw> — static route
#
# Example:
#   interface eth0
#   address   10.0.0.1/24
#   dhcp-range 10.0.0.10,10.0.0.100,12h
#   dns       8.8.8.8 8.8.4.4
#
# ── Default QEMU virtio-net configuration ──────────────────────────────────

interface eth0
address   10.0.0.1/24
dhcp-range 10.0.0.10,10.0.0.200,12h
dns       8.8.8.8
"""

    # ------------------------------------------------------------------
    # nanodhcp package generators
    # ------------------------------------------------------------------

    def _nanodhcp_config_in(self) -> str:
        return """\
config BR2_PACKAGE_NANODHCP
\tbool "nanodhcp"
\tdepends on BR2_USE_MMU
\tdepends on BR2_TOOLCHAIN_HAS_THREADS
\tselect BR2_PACKAGE_HOST_RUSTC
\thelp
\t  Minimal DHCPv4 server for homelab / embedded Linux / appliance OS.
\t  Pure Rust, no external crates — single static binary.
\t
\t  Reads /etc/nanodhcp.conf at startup, serves DHCP on the
\t  configured interface.  Lease state is persisted to
\t  /var/lib/nanodhcp/leases.
\t
\t  Installs:
\t    /usr/sbin/nanodhcp       — DHCPv4 server binary
\t    /etc/nanodhcp.conf       — default configuration
\t    /etc/init.d/S10nanodhcp  — BusyBox init script
\t    /var/lib/nanodhcp/       — lease state directory
\t
\t  https://github.com/4stm4/nanodhcp

comment "nanodhcp needs a toolchain w/ threads"
\tdepends on BR2_USE_MMU
\tdepends on !BR2_TOOLCHAIN_HAS_THREADS
"""

    def _nanodhcp_mk(self) -> str:
        return f"""\
################################################################################
#
# nanodhcp — minimal DHCPv4 server (Rust)
#
################################################################################

NANODHCP_VERSION      = {NANODHCP_VERSION}
NANODHCP_SITE         = https://github.com/4stm4/nanodhcp/archive/$(NANODHCP_VERSION)
NANODHCP_SOURCE       = nanodhcp-$(NANODHCP_VERSION).tar.gz
NANODHCP_LICENSE      = AGPL-3.0
NANODHCP_LICENSE_FILES = LICENSE

define NANODHCP_INSTALL_TARGET_CMDS
\t$(INSTALL) -D -m 0755 \\
\t\t$(@D)/target/$(RUSTC_TARGET_NAME)/release/nanodhcp \\
\t\t$(TARGET_DIR)/usr/sbin/nanodhcp
\t$(INSTALL) -D -m 0644 \\
\t\t$(BR2_EXTERNAL_NETOS_PATH)/package/nanodhcp/nanodhcp.conf \\
\t\t$(TARGET_DIR)/etc/nanodhcp.conf
\t$(INSTALL) -D -m 0755 \\
\t\t$(BR2_EXTERNAL_NETOS_PATH)/package/nanodhcp/S10nanodhcp \\
\t\t$(TARGET_DIR)/etc/init.d/S10nanodhcp
\tmkdir -p $(TARGET_DIR)/var/lib/nanodhcp
endef

$(eval $(cargo-package))
"""

    def _nanodhcp_hash(self) -> str:
        return f"""\
# Locally calculated — nanodhcp commit {NANODHCP_VERSION[:12]}
sha256  {NANODHCP_SHA256}  nanodhcp-{NANODHCP_VERSION}.tar.gz
"""

    def _nanodhcp_cargo_lock_patch(self) -> str:
        return """\
From: fix <fix@fix.com>
Date: Sat, 14 Jun 2026 00:00:00 +0000
Subject: [PATCH] fix Cargo.lock version to match Cargo.toml 0.2.0

--- a/Cargo.lock
+++ b/Cargo.lock
@@ -3,5 +3,5 @@
 version = 4

 [[package]]
 name = "nanodhcp"
-version = "0.1.0"
+version = "0.2.0"
"""

    def _nanodhcp_init_script(self) -> str:
        return """\
#!/bin/sh
#
# /etc/init.d/S10nanodhcp — BusyBox init script for nanodhcp
# Starts the minimal DHCPv4 server at boot.
#

CONF=/etc/nanodhcp.conf
PIDFILE=/var/run/nanodhcp.pid

case "$1" in
    start)
        printf 'Starting nanodhcp: '
        mkdir -p /var/lib/nanodhcp
        start-stop-daemon --start --quiet --background \\
            --pidfile "$PIDFILE" --make-pidfile \\
            --exec /usr/sbin/nanodhcp -- "$CONF"
        echo "OK"
        ;;
    stop)
        printf 'Stopping nanodhcp: '
        start-stop-daemon --stop --quiet --pidfile "$PIDFILE"
        rm -f "$PIDFILE"
        echo "OK"
        ;;
    restart|reload)
        "$0" stop
        "$0" start
        ;;
    status)
        if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
            echo "nanodhcp: running (pid=$(cat "$PIDFILE"))"
        else
            echo "nanodhcp: stopped"
        fi
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status}"
        exit 1
esac

exit $?
"""

    def _nanodhcp_default_config(self) -> str:
        return """\
# /etc/nanodhcp.conf — nanodhcp DHCPv4 server configuration
# https://github.com/4stm4/nanodhcp
#
# Format: key=value, one per line. Blank lines and # comments are ignored.
#
# ── Interface ─────────────────────────────────────────────────────────────────
interface=eth0

# ── Server identity ───────────────────────────────────────────────────────────
# DHCP option 54 — must match the IP assigned to `interface`
server_ip=10.0.0.1

# ── Subnet ────────────────────────────────────────────────────────────────────
subnet=10.0.0.0/24
subnet_mask=255.255.255.0

# ── Dynamic pool ──────────────────────────────────────────────────────────────
pool_start=10.0.0.10
pool_end=10.0.0.200

# ── Default gateway and DNS ───────────────────────────────────────────────────
router=10.0.0.1
dns=10.0.0.1,8.8.8.8

# ── Lease duration (seconds) ──────────────────────────────────────────────────
lease_time=86400

# ── Lease persistence ─────────────────────────────────────────────────────────
lease_file=/var/lib/nanodhcp/leases

# ── Static bindings ───────────────────────────────────────────────────────────
# static=<name>,<mac>,<ip>
# static=myserver,aa:bb:cc:dd:ee:ff,10.0.0.5
"""

    # ------------------------------------------------------------------
    # nanodns package (Rust, branch-tracked from GitHub)
    # ------------------------------------------------------------------

    def _nanodns_config_in(self) -> str:
        return """\
config BR2_PACKAGE_NANODNS
\tbool "nanodns"
\tdepends on BR2_USE_MMU
\tdepends on BR2_TOOLCHAIN_HAS_THREADS
\tselect BR2_PACKAGE_HOST_RUSTC
\thelp
\t  Minimal DNS server for small local networks. Pure Rust, no external
\t  crates — single static binary.
\t
\t  Serves the local .lan zone, resolves nanodhcp leases, forwards unknown
\t  domains upstream, optional response cache and a domain blocklist
\t  (ad/tracking sinkhole) with mtime hot-reload.
\t
\t  Installs:
\t    /usr/sbin/nanodns        — DNS server binary
\t    /etc/nanodns/config      — default configuration
\t    /etc/nanodns/blocklist   — domain blocklist (managed by web UI)
\t    /etc/init.d/S11nanodns   — BusyBox init script
\t
\t  https://github.com/4stm4/nanoDNS

comment "nanodns needs a toolchain w/ threads"
\tdepends on BR2_USE_MMU
\tdepends on !BR2_TOOLCHAIN_HAS_THREADS
"""

    def _nanodns_mk(self) -> str:
        # Branch-tracked (VERSION=main по умолчанию): тарбол ветки меняется,
        # поэтому .hash не пишем — Buildroot предупредит и продолжит.
        return f"""\
################################################################################
#
# nanodns — minimal DNS server with domain blocking (Rust)
#
################################################################################

NANODNS_VERSION      = {NANODNS_VERSION}
NANODNS_SITE         = https://github.com/4stm4/nanoDNS/archive/$(NANODNS_VERSION)
NANODNS_SOURCE       = nanodns-$(NANODNS_VERSION).tar.gz
NANODNS_LICENSE      = AGPL-3.0
NANODNS_LICENSE_FILES = LICENSE

define NANODNS_INSTALL_TARGET_CMDS
\t$(INSTALL) -D -m 0755 \\
\t\t$(@D)/target/$(RUSTC_TARGET_NAME)/release/nanodns \\
\t\t$(TARGET_DIR)/usr/sbin/nanodns
\t$(INSTALL) -D -m 0644 \\
\t\t$(BR2_EXTERNAL_NETOS_PATH)/package/nanodns/nanodns.conf \\
\t\t$(TARGET_DIR)/etc/nanodns/config
\t$(INSTALL) -D -m 0644 \\
\t\t$(BR2_EXTERNAL_NETOS_PATH)/package/nanodns/blocklist \\
\t\t$(TARGET_DIR)/etc/nanodns/blocklist
\t$(INSTALL) -D -m 0755 \\
\t\t$(BR2_EXTERNAL_NETOS_PATH)/package/nanodns/S11nanodns \\
\t\t$(TARGET_DIR)/etc/init.d/S11nanodns
endef

$(eval $(cargo-package))
"""

    def _nanodns_init_script(self) -> str:
        return """\
#!/bin/sh
#
# /etc/init.d/S11nanodns — BusyBox init script for nanodns
# Starts after S10nanodhcp so the lease file already exists.
#

CONF=/etc/nanodns/config
PIDFILE=/var/run/nanodns.pid

case "$1" in
    start)
        printf 'Starting nanodns: '
        start-stop-daemon --start --quiet --background \\
            --pidfile "$PIDFILE" --make-pidfile \\
            --exec /usr/sbin/nanodns -- --config "$CONF"
        echo "OK"
        ;;
    stop)
        printf 'Stopping nanodns: '
        start-stop-daemon --stop --quiet --pidfile "$PIDFILE"
        rm -f "$PIDFILE"
        echo "OK"
        ;;
    restart|reload)
        "$0" stop
        "$0" start
        ;;
    status)
        if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
            echo "nanodns: running (pid=$(cat "$PIDFILE"))"
        else
            echo "nanodns: stopped"
        fi
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status}"
        exit 1
esac

exit $?
"""

    def _nanodns_default_config(self) -> str:
        # Установится как /etc/nanodns/config. На TinyWifi AP nanodns слушает 53,
        # резолвит .lan и читает leases от nanodhcp.
        return """\
# /etc/nanodns/config — nanodns configuration
# https://github.com/4stm4/nanoDNS
#
# Format: key=value, one per line. Blank lines and # comments are ignored.

listen=0.0.0.0:53
domain=lan
router_name=router
router_ip=192.168.44.1

# Upstream resolvers (tried in order)
upstream=1.1.1.1:53
upstream=8.8.8.8:53

# DHCP leases written by nanodhcp -> hostname.lan resolution
lease_file=/var/lib/nanodhcp/leases

# Response cache
cache=true
cache_max_entries=4096
cache_ttl=60

# Domain blocking (ad/tracking). Managed by the TinyWifi web panel; the file is
# hot-reloaded on change. block_response: sinkhole IP (0.0.0.0) or NXDOMAIN.
block_file=/etc/nanodns/blocklist
block_response=0.0.0.0
"""

    def _nanodns_default_blocklist(self) -> str:
        return """\
# /etc/nanodns/blocklist — one domain per line, '#' comments, '*.domain' wildcard.
# Managed by the TinyWifi web panel (downloads StevenBlack/AdGuard lists).
# Empty by default — add domains or let the web UI populate it.
"""

    # ------------------------------------------------------------------
    # tinywifi-web package (Rust, branch-tracked from GitHub)
    # ------------------------------------------------------------------

    def _tinywifi_config_in(self) -> str:
        return """\
config BR2_PACKAGE_TINYWIFI
\tbool "tinywifi-web"
\tdepends on BR2_USE_MMU
\tdepends on BR2_TOOLCHAIN_HAS_THREADS
\tselect BR2_PACKAGE_HOST_RUSTC
\thelp
\t  TinyWifi web management panel (Rust). Builds the tinywifi-web crate
\t  from the tinyWiFi workspace and installs the binary. The init script
\t  (S20tinywifi-web) is provisioned by the TinyWifi appliance setup.
\t
\t  Installs:
\t    /usr/sbin/tinywifi-web    — web panel binary
\t
\t  https://github.com/4stm4/tinyWiFi

comment "tinywifi-web needs a toolchain w/ threads"
\tdepends on BR2_USE_MMU
\tdepends on !BR2_TOOLCHAIN_HAS_THREADS
"""

    def _tinywifi_mk(self) -> str:
        # tinyWiFi — это cargo workspace; собираем только крейт tinywifi-web,
        # чтобы не тянуть tinywifi-display (железо-специфичные зависимости).
        return f"""\
################################################################################
#
# tinywifi-web — TinyWifi web management panel (Rust)
#
################################################################################

TINYWIFI_VERSION      = {TINYWIFI_VERSION}
TINYWIFI_SITE         = https://github.com/4stm4/tinyWiFi/archive/$(TINYWIFI_VERSION)
TINYWIFI_SOURCE       = tinywifi-$(TINYWIFI_VERSION).tar.gz
TINYWIFI_LICENSE      = MIT
TINYWIFI_LICENSE_FILES = LICENSE

# Собирать только web-крейт из workspace
TINYWIFI_CARGO_BUILD_OPTS = -p tinywifi-web

define TINYWIFI_INSTALL_TARGET_CMDS
\t$(INSTALL) -D -m 0755 \\
\t\t$(@D)/target/$(RUSTC_TARGET_NAME)/release/tinywifi-web \\
\t\t$(TARGET_DIR)/usr/sbin/tinywifi-web
endef

$(eval $(cargo-package))
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

        # groups_override=None → DEFAULT_GROUPS; [] → только extra_packages + target
        base_groups = self.groups_override if self.groups_override is not None else list(DEFAULT_GROUPS)
        package_lines: list[str] = catalog.resolve_groups(base_groups) if base_groups else []

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
                self.target.toolchain_libc_symbol,
                "BR2_TOOLCHAIN_BUILDROOT_CXX=y",
                f'BR2_TARGET_GENERIC_HOSTNAME="{NETOS_HOSTNAME}"',
                f'BR2_TARGET_GENERIC_ISSUE="{NETOS_NAME} {NETOS_VERSION}"',
                'BR2_SYSTEM_DHCP="eth0"',
                'BR2_ROOTFS_OVERLAY="$(BR2_EXTERNAL_NETOS_PATH)/board/4stm4/netos/rootfs_overlay"',
                'BR2_ROOTFS_POST_BUILD_SCRIPT="$(BR2_EXTERNAL_NETOS_PATH)/board/4stm4/netos/post-build.sh"',
                # Primary mirror: use sources.buildroot.net first for all packages.
                # This skips slow/unreliable upstream VCS clones (e.g. sourceware.org/glibc.git)
                # and goes straight to pre-packaged tarballs.
                'BR2_PRIMARY_SITE="https://sources.buildroot.net"',
                # Aggressive retry: -t 0 = unlimited retries, --waitretry=10 waits between attempts,
                # --read-timeout=600 handles slow connections, partial downloads are resumed automatically.
                'BR2_WGET="wget -nd --passive-ftp -t 0 --waitretry=5 --connect-timeout=30 --read-timeout=120"',
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
            self.target.toolchain_libc_symbol,
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
        # gcc-final stamps that lock in --enable-languages
        for gcc_dir in _glob.glob(str(build_dir / "gcc-final-*")):
            for stamp in ["built", "configured", "host_installed", "installed",
                          "staging_installed", "target_installed"]:
                p = Path(gcc_dir) / f".stamp_{stamp}"
                if p.exists():
                    p.unlink()
        # Remove stale cross-compiler binaries so the stale-check in the configurator resets
        prefix = self.target.toolchain_triple
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

    _ROOTFS_DEFCONFIG_HASH_FILE = ".last_rootfs_defconfig_hash"

    def _rootfs_defconfig_hash(self) -> str:
        import hashlib as _hashlib
        return _hashlib.sha256(self._defconfig().encode()).hexdigest()[:16]

    def _clean_target_if_defconfig_changed(self) -> None:
        """Remove output/target/ and install stamps when the package set changes.

        Without this, switching from a DEFAULT_GROUPS build to groups_override=["tinywifi"]
        leaves python-web and other stale packages in output/target/ because Buildroot
        make only adds packages, never removes ones dropped from the config.
        """
        hash_file = self.output_dir / self._ROOTFS_DEFCONFIG_HASH_FILE
        current_hash = self._rootfs_defconfig_hash()
        saved_hash = hash_file.read_text().strip() if hash_file.exists() else ""
        if saved_hash == current_hash:
            return
        logging.info(
            "Defconfig package set changed (%s → %s) — cleaning output/target/ to prevent stale packages",
            saved_hash or "none", current_hash,
        )
        target_dir = self.output_dir / "target"
        if target_dir.exists():
            shutil.rmtree(target_dir)
        # target/ was just wiped, so EVERY package — including the toolchain
        # runtime (glibc → libc.so.6 + ld-linux-*.so.*, gcc → libgcc_s /
        # libstdc++) — must re-run its install-target step to repopulate it.
        # We delete only .stamp_target_installed, never .stamp_built /
        # .stamp_configured, so this re-triggers the *cheap* copy step
        # (copy_toolchain_lib_root copies a handful of .so files from the
        # staging sysroot) — NOT a 45-min GCC rebuild: the build artifacts and
        # staging sysroot are untouched, and host packages have no target stamp
        # so they are unaffected.
        #
        # The previous version excluded glibc/gcc/toolchain-buildroot from this
        # reset, which left libc.so.6 + ld-linux out of the fresh target →
        # /bin/busybox (a dynamic PIE) could not be exec'd → kernel panic
        # "No working init found" on every boot.
        build_dir = self.output_dir / "build"
        if build_dir.exists():
            for stamp in build_dir.glob("*/.stamp_target_installed"):
                stamp.unlink()
        hash_file.write_text(current_hash)

    def _ensure_toolchain_libs_in_target(self) -> None:
        """Guarantee the C library is staged for target/ before ``make``.

        ``copy_toolchain_lib_root`` (glibc → libc.so.6 + ld-linux-*.so.*, gcc →
        libgcc_s / libstdc++) is gated by each package's
        ``.stamp_target_installed``.  If a previous run left those stamps set
        while target/ ended up *without* the C library (stale toolchain cache,
        an interrupted clean, or the historical exclusion bug above), ``make``
        considers the copy done and ships a rootfs whose /bin/busybox cannot be
        exec'd → kernel panic "No working init found".

        This runs on every build (not just on defconfig change): it checks for
        the loader + libc in target/ and, if missing, resets only the relevant
        ``.stamp_target_installed`` so the next ``make`` re-copies the runtime.
        No rebuild — build artifacts and the staging sysroot stay intact.
        """
        import glob as _glob

        target_lib = self.output_dir / "target" / "lib"
        loader = list(target_lib.glob("ld-linux-*.so.*")) if target_lib.exists() else []
        # glibc → libc.so.6 ; musl → libc.so ; cover both flavours
        libc_present = bool(loader) and target_lib.exists() and (
            (target_lib / "libc.so.6").exists() or (target_lib / "libc.so").exists()
        )
        if libc_present:
            return

        build_dir = self.output_dir / "build"
        if not build_dir.exists():
            return
        reset: list[str] = []
        for pattern in (
            "glibc-*", "musl-*", "uclibc-*",
            "toolchain-buildroot", "toolchain-buildroot-aux",
            "toolchain-buildroot-initial",
        ):
            for d in _glob.glob(str(build_dir / pattern)):
                stamp = Path(d) / ".stamp_target_installed"
                if stamp.exists():
                    stamp.unlink()
                    reset.append(Path(d).name)
        if reset:
            logging.warning(
                "target/ is missing the C library (libc + ld-linux) — reset "
                "target-install stamps so 'make' re-copies the toolchain "
                "runtime: %s",
                ", ".join(sorted(reset)),
            )

        # Also verify that the host toolchain has the C++ runtime.
        # gcc-final's target-install copies libstdc++ from host/<triple>/lib*/.
        # If it's absent (e.g. gcc was previously configured without C++), force
        # a rebuild rather than letting `make` fail mid-run.
        self._ensure_cxx_libs_in_host()

    def _ensure_cxx_libs_in_host(self) -> None:
        """Force gcc-final rebuild if libstdc++ is absent from host/<triple>/lib*.

        gcc-final's target-install step copies libatomic, libgcc_s and libstdc++
        from host/<triple>/lib*/ into target/.  If gcc was ever built without C++
        (stale .stamp_configured, wrong --enable-languages at configure time, or a
        bad toolchain cache) libstdc++ won't be there and the step fails with:
          cp: cannot stat '.../lib*/libstdc++.so*': No such file or directory

        Detecting the absence here and clearing the gcc-final stamps (so Buildroot
        reconfigures gcc with BR2_TOOLCHAIN_BUILDROOT_CXX=y) is far better than
        letting `make` fall over 30 min into a rootfs build.
        """
        triple = self.target.toolchain_triple
        host_triple = self.output_dir / "host" / triple
        if not host_triple.exists():
            return
        lib_dirs = list(host_triple.glob("lib*"))
        has_stdcxx = any(list(d.glob("libstdc++.so*")) for d in lib_dirs)
        if has_stdcxx:
            return
        logging.warning(
            "host/%s/lib*/ is missing libstdc++.so — gcc-final was built without "
            "C++ support. Clearing gcc-final stamps to force a proper rebuild "
            "with CXX=y (this adds ~30 min to the current build).",
            triple,
        )
        self._clear_gcc_final_stamps()
        # Invalidate any stale toolchain cache archive that also lacks libstdc++
        try:
            from netos_build.toolchain_cache import ToolchainCache
            plan    = self._build_plan()
            tc_cache = ToolchainCache(self._cache_root)
            archive = tc_cache.archive_path(plan, BUILDROOT_VERSION)
            if archive.exists():
                archive.unlink()
                logging.warning("Deleted incomplete toolchain cache: %s", archive.name)
        except Exception as exc:
            logging.debug("Could not check/delete toolchain cache: %s", exc)

    def _build_rootfs(self):
        jobs = os.environ.get("NETOS_BUILD_JOBS", str(os.cpu_count() or 1))
        logging.info("Building 4stm4 netOS rootfs with Buildroot (-j%s)", jobs)
        self._clean_target_if_defconfig_changed()
        self._ensure_toolchain_libs_in_target()
        self._clear_target_os_release_links()

        cmd = ["make", "-C", str(self.buildroot_dir), f"O={self.output_dir}", f"-j{jobs}"]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        assert proc.stdout is not None

        tail: collections.deque[str] = collections.deque(maxlen=80)
        current_pkg = ""
        had_download = False

        for raw in proc.stdout:
            line = raw.rstrip("\n")
            print(line, flush=True)
            tail.append(line)
            m = re.match(r">>> (\S+)", line)
            if m:
                current_pkg = m.group(1)
            if "Downloading" in line:
                had_download = True

        proc.wait()
        if proc.returncode == 0:
            return

        tail_lines = list(tail)

        if had_download and any(
            "Giving up" in l or "404 Not Found" in l for l in tail_lines
        ):
            pkg_hint = f" [{current_pkg}]" if current_pkg else ""
            raise RuntimeError(
                f"Buildroot: не удалось скачать пакет{pkg_hint} — сетевая ошибка.\n"
                "  Все зеркала недоступны или вернули 404. Проверь интернет на сервере сборки\n"
                "  и перезапусти сборку."
            )

        err_lines = [l for l in tail_lines if "*** [" in l or ": error:" in l]
        hint = ("\n  " + "\n  ".join(err_lines[-5:])) if err_lines else " Смотри лог выше."
        raise RuntimeError(
            f"Buildroot завершился с ошибкой (код {proc.returncode}).{hint}"
        )

    def _clear_target_os_release_links(self):
        for rel_path in ("target/etc/os-release", "target/usr/lib/os-release"):
            path = self.output_dir / rel_path
            if path.exists() or path.is_symlink():
                path.unlink()

    # ------------------------------------------------------------------
    # Toolchain cache (M3)
    # ------------------------------------------------------------------

    def _external_content_hash(self) -> str:
        """Stable hash of all generated external-tree / overlay content.

        Covers: openvswitch .mk + Config.in + .hash, post-build script,
        overlay content generators, NETOS_VERSION, NETOS_HOSTNAME.

        Changing any of these (e.g. bumping NETOS_VERSION when nervum ships)
        produces a new rootfs cache key automatically — no manual cache flush.
        """
        import hashlib as _hashlib
        parts = [
            # openvswitch external package
            self._openvswitch_mk(),
            self._openvswitch_config_in(),
            self._openvswitch_hash(),
            # mininet external package
            self._mininet_mk(),
            self._mininet_config_in(),
            self._mininet_script(),
            self._mininet_init_script(),
            self._mininet_default_config(),
            # nanodhcp external package
            self._nanodhcp_mk(),
            self._nanodhcp_config_in(),
            self._nanodhcp_hash(),
            self._nanodhcp_init_script(),
            self._nanodhcp_default_config(),
            # post-build & overlay scripts
            self._post_build_script(),
            # branding constants baked into the image
            f"NETOS_VERSION={NETOS_VERSION}",
            f"NETOS_HOSTNAME={NETOS_HOSTNAME}",
            f"NETOS_NAME={NETOS_NAME}",
            f"OPENVSWITCH_VERSION={OPENVSWITCH_VERSION}",
            f"NANODHCP_VERSION={NANODHCP_VERSION}",
        ]
        return _hashlib.md5("\n---\n".join(parts).encode()).hexdigest()[:16]

    def _build_plan(self):
        """Return a ResolvedBuildPlan for the current target (lazy import)."""
        from netos_build.plan import ResolvedBuildPlan
        from netos_build.catalog import PackageCatalog, DEFAULT_GROUPS

        # Mirror _defconfig() group resolution so the cache key covers the full
        # package selection — otherwise different groups_override values (e.g.
        # ["tinywifi"] vs DEFAULT_GROUPS) produce the same cache key and a fat
        # full-build rootfs gets served to a slim TinyWifi build.
        catalog = PackageCatalog.load()
        base_groups = self.groups_override if self.groups_override is not None else list(DEFAULT_GROUPS)
        group_pkgs: list[str] = catalog.resolve_groups(base_groups) if base_groups else []
        if self.extra_groups:
            for pkg in catalog.resolve_groups(list(self.extra_groups)):
                if pkg not in group_pkgs:
                    group_pkgs.append(pkg)

        return ResolvedBuildPlan.from_target(
            self.target,
            extra_packages=group_pkgs + list(self.extra_packages),
            cache_policy=self.cache_policy,
            external_hash=self._external_content_hash(),
        )

    def _cache_sync(self):
        """Return a CacheSync instance configured from environment variables.

        Returns None when no remote store is configured (LocalStore).
        """
        from netos_build.store_factory import StoreFactory
        from netos_build.cache_sync import CacheSync
        store = StoreFactory.from_env()
        if store.is_local:
            return None
        return CacheSync(store, push_enabled=StoreFactory.push_enabled())

    def _restore_toolchain_cache(self) -> None:
        """Try to restore a pre-built toolchain from cache.

        Called after defconfig and before ``make`` so Buildroot sees the
        existing stamps and skips the ~45-min GCC build.
        Order: remote pull (M7) → local cache hit → local restore.
        """
        if self.cache_policy == "rebuild":
            logging.info("cache_policy=rebuild — skipping toolchain cache restore")
            return

        from netos_build.toolchain_cache import ToolchainCache
        plan     = self._build_plan()
        tc_cache = ToolchainCache(self._cache_root)
        key      = tc_cache.cache_key(plan, BUILDROOT_VERSION)
        archive  = tc_cache.archive_path(plan, BUILDROOT_VERSION)

        # M7: try to pull from remote store into local cache before checking has()
        sync = self._cache_sync()
        if sync:
            sync.pull(archive.name, archive)

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
        After local pack, pushes to remote store (M7).
        """
        if self.cache_policy == "rebuild":
            return

        from netos_build.toolchain_cache import ToolchainCache
        plan     = self._build_plan()
        tc_cache = ToolchainCache(self._cache_root)

        if tc_cache.has(plan, BUILDROOT_VERSION):
            logging.info("Toolchain already cached — skipping pack")
            # Still push to remote in case it's missing there
            sync = self._cache_sync()
            if sync:
                archive = tc_cache.archive_path(plan, BUILDROOT_VERSION)
                sync.push(archive.name, archive)
            return

        # Verify that GCC was actually compiled into host/
        prefix  = self.target.toolchain_triple
        gcc_bin = self.output_dir / "host" / "bin" / f"{prefix}-gcc"
        if not gcc_bin.exists():
            logging.warning(
                "GCC binary not found at %s — toolchain not cached", gcc_bin
            )
            return

        try:
            dest = tc_cache.pack(plan, BUILDROOT_VERSION, self.output_dir)
            # M7: push new archive to remote store
            sync = self._cache_sync()
            if sync:
                sync.push(dest.name, dest)
            # Evict old toolchain archives if policy is configured
            from netos_build.cache_eviction import evict_from_env
            evict_from_env(tc_cache.cache_dir)
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

        Order: remote pull (M7) → local cache hit → local restore.
        Returns True if rootfs.tar was successfully restored (caller must
        skip _build_rootfs).  Returns False on cache miss or restore failure.
        """
        if self.cache_policy in ("rebuild", "refresh"):
            logging.info("cache_policy=%s — skipping rootfs cache restore", self.cache_policy)
            return False

        from netos_build.rootfs_cache import RootfsCache
        plan      = self._build_plan()
        rc_cache  = RootfsCache(self._cache_root)
        key       = rc_cache.cache_key(plan, BUILDROOT_VERSION)
        archive   = rc_cache.archive_path(plan, BUILDROOT_VERSION)

        # M7: pull from remote store into local cache before checking has()
        sync = self._cache_sync()
        if sync:
            sync.pull(archive.name, archive)

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
        After local pack, pushes to remote store (M7).
        """
        if self.cache_policy == "rebuild":
            return

        from netos_build.rootfs_cache import RootfsCache
        plan     = self._build_plan()
        rc_cache = RootfsCache(self._cache_root)

        if rc_cache.has(plan, BUILDROOT_VERSION):
            if self.cache_policy != "refresh":
                logging.info("Rootfs already cached — skipping pack")
                # Still push to remote in case it's missing there
                sync = self._cache_sync()
                if sync:
                    archive = rc_cache.archive_path(plan, BUILDROOT_VERSION)
                    sync.push(archive.name, archive)
                return

        rootfs_tar = self.output_dir / "images" / "rootfs.tar"
        if not rootfs_tar.exists():
            logging.warning("rootfs.tar not found — rootfs not cached")
            return

        try:
            dest = rc_cache.pack(plan, BUILDROOT_VERSION, self.output_dir)
            # M7: push new archive to remote store
            sync = self._cache_sync()
            if sync:
                sync.push(dest.name, dest)
            # Evict old rootfs archives if policy is configured
            from netos_build.cache_eviction import evict_from_env
            evict_from_env(rc_cache.cache_dir)
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
        # sudo tar is required to correctly restore device nodes (char/block) and
        # setuid bits. fakeroot only simulates root in userspace and cannot create
        # real device nodes on the host filesystem.
        subprocess.run(
            ["sudo", "tar", "-xf", str(rootfs_tar), "-C", str(self.rootfs_path)],
            check=True,
        )
        # Return ownership to current user so subsequent writes (fstab, configs, etc.)
        # don't need root. Device nodes keep their correct type — only ownership changes.
        import getpass
        subprocess.run(
            ["sudo", "chown", "-R", f"{getpass.getuser()}:", str(self.rootfs_path)],
            check=True,
        )
        self._verify_rootfs_has_libc()

    def _verify_rootfs_has_libc(self) -> None:
        """Fail the build if the extracted rootfs has no C library / loader.

        netOS always uses a dynamic glibc toolchain (BR2_TOOLCHAIN_BUILDROOT_GLIBC,
        and openvswitch forbids BR2_STATIC_LIBS), so /bin/busybox is a dynamic PIE
        that needs the loader (ld-linux-*.so.*) + libc (libc.so.6) to exec.  If
        they are absent the kernel panics "No working init found" at boot.
        Catching it here turns a silent, un-bootable image (and a wasted flash)
        into an explicit build failure naming the exact cause.
        """
        rootfs = self.rootfs_path
        lib_dirs = [rootfs / "lib", rootfs / "usr" / "lib", rootfs / "lib64"]

        def _present(globs: "tuple[str, ...]") -> bool:
            for d in lib_dirs:
                if d.exists() and any(any(d.glob(g)) for g in globs):
                    return True
            return False

        has_loader = _present(("ld-linux-*.so.*", "ld-musl-*.so.*"))
        has_libc = _present(("libc.so.6", "libc.so"))
        if has_loader and has_libc:
            return

        missing = []
        if not has_loader:
            missing.append("dynamic loader (ld-linux-*.so.*)")
        if not has_libc:
            missing.append("C library (libc.so.6)")
        raise RuntimeError(
            "Rootfs is missing " + " and ".join(missing) + " — a dynamically "
            "linked busybox/init cannot exec, so the kernel would panic "
            "'No working init found' at boot.  Root cause is almost always a "
            "skipped copy_toolchain_lib_root (stale .stamp_target_installed "
            "after a target/ wipe).  Rebuild with cache_policy=refresh to "
            "regenerate the rootfs."
        )
