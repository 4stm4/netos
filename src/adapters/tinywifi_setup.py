"""TinyWifi appliance provisioner.

Writes all rootfs files for a minimal Wi-Fi AP appliance (zero2w target):
  /etc/hostname, /etc/hosts, /etc/resolv.conf, /etc/fstab, /etc/motd
  /etc/init.d/S00mount, S01mdev, S02modules, S03network, S10tinywifi
  /etc/hostapd/hostapd.conf
  /etc/nftables/tinywifi.nft
  /etc/nanodhcp/nanodhcp.conf
  /etc/tinywifi/tinywifi.toml
  /usr/sbin/tinywifi-web   (собирается из github.com/4stm4/tinyWiFi)
  /etc/init.d/S20tinywifi-web
  runtime dirs: /var/lib/nanodhcp, /var/lib/tinywifi, /var/log, /run, /tmp

Вызывается из main.py при NETOS_APPLIANCE=tinywifi вместо
install_webui_assets / install_nervum_assets / install_ovsdb_assets.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from pathlib import Path

AP_IFACE      = "wlan0"
AP_IP         = "192.168.44.1"
AP_SUBNET     = "192.168.44.0/24"
AP_POOL_START = "192.168.44.10"
AP_POOL_END   = "192.168.44.200"
WAN_IFACE     = "eth0"


class TinyWifiSetup:
    """Provisioner rootfs для TinyWifi AP appliance."""

    def __init__(self) -> None:
        # Read env at provisioning time, after main.py has applied the profile.
        self.hostname = os.environ.get("NETOS_HOSTNAME", "tinywifi")
        self.version = os.environ.get("NETOS_VERSION", "0.1.0")
        self.ap_ssid = os.environ.get("NETOS_WIFI_SSID", "TinyWifi")
        self.ap_psk = os.environ.get("NETOS_WIFI_PSK", "tinywifi123")
        self.ap_country = os.environ.get("NETOS_WIFI_COUNTRY", "US")
        self.ap_channel = os.environ.get("NETOS_WIFI_CHANNEL", "6")

    def install(self, rootfs_path: Path) -> None:
        root = Path(rootfs_path)
        self._directories(root)
        self._base_configs(root)
        self._init_scripts(root)
        self._hostapd_conf(root)
        self._nftables_conf(root)
        self._nanodhcp_conf(root)
        self._tinywifi_conf(root)
        self._web_panel(root)   # tinywifi-web заменяет _www_index
        self._bluetooth_conf(root)
        self._disable_conflicting_inits(root)
        self._set_root_password(root)

    # ------------------------------------------------------------------
    # Directories
    # ------------------------------------------------------------------

    def _directories(self, root: Path) -> None:
        for rel in (
            "etc/init.d",
            "etc/hostapd",
            "etc/nftables",
            "etc/nanodhcp",
            "etc/tinywifi",
            "etc/bluetooth",
            "etc/profile.d",
            "www",
            "var/lib/nanodhcp",
            "var/lib/tinywifi",
            "var/log",
            "run",
            "tmp",
        ):
            (root / rel).mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Base /etc files
    # ------------------------------------------------------------------

    def _base_configs(self, root: Path) -> None:
        (root / "etc" / "hostname").write_text(f"{self.hostname}\n")
        (root / "etc" / "hosts").write_text(
            "127.0.0.1   localhost\n"
            f"127.0.1.1   {self.hostname}\n"
            f"{AP_IP}  {self.hostname}\n"
        )
        (root / "etc" / "resolv.conf").write_text(
            "nameserver 8.8.8.8\nnameserver 8.8.4.4\n"
        )
        (root / "etc" / "fstab").write_text(
            "proc     /proc    proc     defaults  0 0\n"
            "sysfs    /sys     sysfs    defaults  0 0\n"
            "devtmpfs /dev     devtmpfs defaults  0 0\n"
            "tmpfs    /run     tmpfs    defaults  0 0\n"
            "tmpfs    /tmp     tmpfs    defaults  0 0\n"
        )
        (root / "etc" / "motd").write_text(
            f"4stm4 TinyWifi {self.version}\n"
            f"  AP:  {self.ap_ssid}  {AP_IP}/24\n"
            f"  SSH: ssh root@{AP_IP}\n"
            f"  Web: http://{AP_IP}/\n\n"
        )
        (root / "etc" / "profile.d" / "netos.sh").write_text(
            "export PATH=/usr/local/sbin:/usr/local/bin:"
            "/usr/sbin:/usr/bin:/sbin:/bin\n"
        )

    # ------------------------------------------------------------------
    # Init scripts
    # ------------------------------------------------------------------

    def _init_scripts(self, root: Path) -> None:
        d = root / "etc" / "init.d"

        self._write_exec(d / "S00mount", """\
#!/bin/sh
mountpoint -q /proc || mount -t proc proc /proc
mountpoint -q /sys  || mount -t sysfs sysfs /sys
mountpoint -q /dev  || mount -t devtmpfs devtmpfs /dev 2>/dev/null || true
mkdir -p /dev/pts
mountpoint -q /dev/pts || mount -t devpts devpts /dev/pts 2>/dev/null || true
mountpoint -q /run  || mount -t tmpfs tmpfs /run
mountpoint -q /tmp  || mount -t tmpfs tmpfs /tmp
""")

        self._write_exec(d / "S01mdev", """\
#!/bin/sh
if command -v mdev >/dev/null 2>&1; then
    echo /sbin/mdev > /proc/sys/kernel/hotplug
    mdev -s
fi
""")

        self._write_exec(d / "S05expand", """\
#!/bin/sh
# Expand rootfs partition to fill SD card on first boot.
PART_DONE=/var/lib/tinywifi/.partition_resized
FS_DONE=/var/lib/tinywifi/.rootfs_expanded

if [ ! -f "$PART_DONE" ]; then
    printf 'Expanding partition: '
    parted -s /dev/mmcblk0 resizepart 2 100% 2>/dev/null && touch "$PART_DONE" && echo OK || echo SKIP
fi

if [ -f "$PART_DONE" ] && [ ! -f "$FS_DONE" ]; then
    printf 'Expanding filesystem: '
    partprobe /dev/mmcblk0 2>/dev/null || true
    resize2fs /dev/mmcblk0p2 2>/dev/null && touch "$FS_DONE" && echo OK || echo 'retry next boot'
fi
""")

        self._write_exec(d / "S02modules", f"""\
#!/bin/sh
# WiFi driver. Prefer modprobe so module dependencies are loaded; keep insmod
# fallback for minimal rootfs/kmod breakage.
# Ровно один из двух файлов будет найден в зависимости от платформы:
#   zero2w:    brcmfmac.ko  (реальный BCM43436, firmware из /lib/firmware/brcm/)
#   qemu-wifi: mac80211_hwsim.ko (виртуальный WiFi, без firmware)
rfkill unblock wifi 2>/dev/null || true

load_wifi_mod() {{
    mod="$1"
    if command -v modprobe >/dev/null 2>&1; then
        modprobe "$mod" 2>/dev/null && return 0
    fi
    path=$(find /lib/modules -name "$mod.ko" 2>/dev/null | head -1)
    [ -n "$path" ] && insmod "$path" 2>/dev/null && return 0
    return 1
}}

load_wifi_mod brcmfmac || load_wifi_mod mac80211_hwsim || true
# Сетевые фильтры, USB, PPP — через modprobe; ошибки некритичны
for m in nf_tables nft_masq nf_nat nf_conntrack \
          usb_serial cp210x ch341 cdc_acm ppp_async ppp_deflate; do
    modprobe "$m" 2>/dev/null || true
done
""")

        self._write_exec(d / "S03network", f"""\
#!/bin/sh
ip link set lo up 2>/dev/null || true
ip link set {WAN_IFACE} up 2>/dev/null || true
if command -v udhcpc >/dev/null 2>&1; then
    udhcpc -i {WAN_IFACE} -b -q 2>/dev/null || true
fi
""")

        self._write_exec(d / "S10tinywifi", f"""\
#!/bin/sh
#
# S10tinywifi — 4stm4 TinyWifi AP
# Поднимает Wi-Fi AP (hostapd), NAT (nftables), DHCP (nanodhcp), HTTP (uhttpd).
# SSH обрабатывается S50dropbear (Buildroot default).
#

HOSTAPD_CONF=/etc/hostapd/hostapd.conf
NFT_CONF=/etc/nftables/tinywifi.nft
NANODHCP_CONF=/etc/nanodhcp/nanodhcp.conf
WWW_ROOT=/www

case "$1" in
start)
    printf 'Starting TinyWifi: '

    # Wi-Fi module is loaded by S02modules; firmware probe may still be settling.
    rfkill unblock wifi 2>/dev/null || true

    # Ждём появления wlan0 — firmware/probe on SDIO can take longer on cold boot.
    for i in $(seq 1 30); do
        ip link show {AP_IFACE} >/dev/null 2>&1 && break
        sleep 1
    done
    if ! ip link show {AP_IFACE} >/dev/null 2>&1; then
        echo "ERROR: {AP_IFACE} not found after 15s" >&2
        exit 1
    fi

    # Устанавливаем regulatory domain до поднятия AP
    command -v iw >/dev/null 2>&1 && iw reg set {self.ap_country} 2>/dev/null || true

    # IP forwarding (NAT)
    echo 1 > /proc/sys/net/ipv4/ip_forward

    # nftables NAT
    if command -v nft >/dev/null 2>&1 && [ -f "$NFT_CONF" ]; then
        nft -f "$NFT_CONF" || true
    fi

    ip addr flush dev {AP_IFACE} 2>/dev/null || true

    # hostapd — поднимает AP и управляет wlan0. Fail fast: without hostapd
    # there is no Wi-Fi AP, so printing OK hides the real boot failure.
    if ! command -v hostapd >/dev/null 2>&1; then
        echo "ERROR: hostapd not found" >&2
        exit 1
    fi
    if [ ! -f "$HOSTAPD_CONF" ]; then
        echo "ERROR: $HOSTAPD_CONF not found" >&2
        exit 1
    fi
    if ! hostapd -B "$HOSTAPD_CONF" -P /run/hostapd.pid; then
        echo "ERROR: hostapd failed to start" >&2
        exit 1
    fi

    # IP на wlan0 после того как hostapd поднял AP
    ip addr add {AP_IP}/24 dev {AP_IFACE}

    # nanodhcp — DHCP для клиентов AP
    mkdir -p /var/lib/nanodhcp
    if command -v nanodhcp >/dev/null 2>&1 && [ -f "$NANODHCP_CONF" ]; then
        start-stop-daemon --start --quiet --background \\
            --pidfile /run/nanodhcp.pid --make-pidfile \\
            --exec /usr/sbin/nanodhcp -- "$NANODHCP_CONF"
    fi

    # Веб-панель: tinywifi-web если собран (занимает порт 80 сам),
    # иначе uhttpd со статическим /www/index.html.
    if [ -x /usr/sbin/tinywifi-web ]; then
        start-stop-daemon --start --quiet --background \\
            --pidfile /run/tinywifi-web.pid --make-pidfile \\
            --exec /usr/sbin/tinywifi-web -- --config /etc/tinywifi/tinywifi.toml
    elif command -v uhttpd >/dev/null 2>&1 && [ -d "$WWW_ROOT" ]; then
        uhttpd -p {AP_IP}:80 -h "$WWW_ROOT" &
        echo $! > /run/uhttpd.pid
    fi

    echo 'OK'
    echo "TinyWifi: AP={self.ap_ssid} {AP_IP}/24"
    ;;
stop)
    printf 'Stopping TinyWifi: '
    [ -f /run/hostapd.pid ]  && kill "$(cat /run/hostapd.pid)"  2>/dev/null || true
    [ -f /run/nanodhcp.pid ] && kill "$(cat /run/nanodhcp.pid)" 2>/dev/null || true
    [ -f /run/uhttpd.pid ]   && kill "$(cat /run/uhttpd.pid)"   2>/dev/null || true
    ip addr flush dev {AP_IFACE} 2>/dev/null || true
    echo 'OK'
    ;;
restart|reload)
    "$0" stop
    "$0" start
    ;;
status)
    echo "hostapd:  $([ -f /run/hostapd.pid ]  && kill -0 "$(cat /run/hostapd.pid)"  2>/dev/null && echo running || echo stopped)"
    echo "nanodhcp: $([ -f /run/nanodhcp.pid ] && kill -0 "$(cat /run/nanodhcp.pid)" 2>/dev/null && echo running || echo stopped)"
    echo "uhttpd:   $([ -f /run/uhttpd.pid ]   && kill -0 "$(cat /run/uhttpd.pid)"   2>/dev/null && echo running || echo stopped)"
    ;;
*)
    echo "Usage: $0 {{start|stop|restart|status}}"
    exit 1
esac
""")

    def _write_exec(self, path: Path, content: str) -> None:
        path.write_text(content)
        path.chmod(0o755)

    # ------------------------------------------------------------------
    # /etc/hostapd/hostapd.conf
    # ------------------------------------------------------------------

    def _hostapd_conf(self, root: Path) -> None:
        (root / "etc" / "hostapd" / "hostapd.conf").write_text(
            f"# /etc/hostapd/hostapd.conf — 4stm4 TinyWifi\n"
            f"interface={AP_IFACE}\n"
            f"driver=nl80211\n"
            f"ssid={self.ap_ssid}\n"
            f"hw_mode=g\n"
            f"channel={self.ap_channel}\n"
            f"country_code={self.ap_country}\n"
            f"ieee80211d=1\n"
            f"wmm_enabled=1\n"
            f"auth_algs=1\n"
            f"wpa=2\n"
            f"wpa_passphrase={self.ap_psk}\n"
            f"wpa_key_mgmt=WPA-PSK\n"
            f"rsn_pairwise=CCMP\n"
        )

    # ------------------------------------------------------------------
    # /etc/nftables/tinywifi.nft
    # ------------------------------------------------------------------

    def _nftables_conf(self, root: Path) -> None:
        (root / "etc" / "nftables" / "tinywifi.nft").write_text(
            f"#!/usr/sbin/nft -f\n"
            f"# /etc/nftables/tinywifi.nft — TinyWifi NAT\n"
            f"# Masquerade трафика клиентов AP ({AP_IFACE}) через WAN ({WAN_IFACE}).\n\n"
            f"flush ruleset\n\n"
            f"table inet filter {{\n"
            f"    chain input   {{ type filter hook input   priority 0; policy accept; }}\n"
            f"    chain forward {{ type filter hook forward priority 0; policy accept; }}\n"
            f"    chain output  {{ type filter hook output  priority 0; policy accept; }}\n"
            f"}}\n\n"
            f"table ip nat {{\n"
            f"    chain postrouting {{\n"
            f"        type nat hook postrouting priority 100; policy accept;\n"
            f"        oifname \"{WAN_IFACE}\" masquerade\n"
            f"    }}\n"
            f"}}\n"
        )

    # ------------------------------------------------------------------
    # /etc/nanodhcp/nanodhcp.conf
    # ------------------------------------------------------------------

    def _nanodhcp_conf(self, root: Path) -> None:
        (root / "etc" / "nanodhcp" / "nanodhcp.conf").write_text(
            f"# /etc/nanodhcp/nanodhcp.conf — TinyWifi DHCPv4 (AP clients)\n"
            f"interface={AP_IFACE}\n"
            f"server_ip={AP_IP}\n"
            f"subnet={AP_SUBNET}\n"
            f"subnet_mask=255.255.255.0\n"
            f"pool_start={AP_POOL_START}\n"
            f"pool_end={AP_POOL_END}\n"
            f"router={AP_IP}\n"
            f"dns={AP_IP},8.8.8.8\n"
            f"lease_time=86400\n"
            f"lease_file=/var/lib/nanodhcp/leases\n"
        )

    # ------------------------------------------------------------------
    # /etc/tinywifi/tinywifi.toml  (зарезервировано для CLI v0.2+)
    # ------------------------------------------------------------------

    def _tinywifi_conf(self, root: Path) -> None:
        """Конфиг для tinywifi-web (github.com/4stm4/tinyWiFi)."""
        (root / "etc" / "tinywifi" / "tinywifi.toml").write_text(
            "[web]\n"
            "listen = \"0.0.0.0:80\"\n\n"
            "[display]\n"
            "refresh_secs = 10\n\n"
            "[paths]\n"
            "hostapd_conf  = \"/etc/hostapd/hostapd.conf\"\n"
            "nanodhcp_conf = \"/etc/nanodhcp/nanodhcp.conf\"\n"
            "leases_file   = \"/var/lib/nanodhcp/leases.json\"\n\n"
            "[services]\n"
            "hostapd  = \"hostapd\"\n"
            "nanodhcp = \"nanodhcp\"\n"
            "web      = \"tinywifi-web\"\n"
            "display  = \"tinywifi-display\"\n"
        )

    # ------------------------------------------------------------------
    # Web panel — tinywifi-web (github.com/4stm4/tinyWiFi)
    # ------------------------------------------------------------------

    # Путь к кешу бинарника на build-сервере
    # Переопределяются через NETOS_TINYWIFI_CACHE_DIR; по умолчанию рядом с temp/
    _WEB_REPO = "https://github.com/4stm4/tinyWiFi.git"

    @staticmethod
    def _cache_base() -> Path:
        env = os.environ.get("NETOS_TINYWIFI_CACHE_DIR", "")
        if env:
            return Path(env)
        # PROJECT_ROOT = src/../  →  рядом с temp/
        here = Path(__file__).resolve().parent.parent.parent
        return here / "temp" / "tinywifi-cache"

    @property
    def _WEB_REPO_DIR(self) -> Path:          # type: ignore[override]
        return self._cache_base() / "tinywifi-web-src"

    @property
    def _WEB_BIN_DIR(self) -> Path:           # type: ignore[override]
        return self._cache_base() / "tinywifi-web-bin"

    def _web_panel(self, root: Path) -> None:
        """Собирает tinywifi-web на build-сервере и устанавливает в rootfs.

        Если cargo недоступен или сборка упала — пишем статический index.html
        чтобы uhttpd не отдавал 404 на веб-панель роутера.
        """
        binary = self._build_web_binary()
        if binary is None:
            logging.warning("tinywifi-web не собран — используем статическую веб-панель")
            self._www_index(root)
            return
        # Устанавливаем бинарник
        dest = root / "usr" / "sbin" / "tinywifi-web"
        shutil.copy2(binary, dest)
        dest.chmod(0o755)
        logging.info("tinywifi-web установлен: %s", dest)
        # Init-скрипт
        self._write_exec(root / "etc" / "init.d" / "S20tinywifi-web", """\
#!/bin/sh
# S20tinywifi-web — TinyWifi web panel (github.com/4stm4/tinyWiFi)
CONF=/etc/tinywifi/tinywifi.toml
PIDFILE=/run/tinywifi-web.pid
BINARY=/usr/sbin/tinywifi-web

case "$1" in
start)
    printf 'Starting tinywifi-web: '
    if [ ! -x "$BINARY" ]; then
        echo "SKIP (binary not found)"
    else
        start-stop-daemon --start --quiet --background \\
            --pidfile "$PIDFILE" --make-pidfile \\
            --exec "$BINARY" -- --config "$CONF"
        echo 'OK'
    fi
    ;;
stop)
    printf 'Stopping tinywifi-web: '
    start-stop-daemon --stop --quiet --pidfile "$PIDFILE" 2>/dev/null || true
    rm -f "$PIDFILE"
    echo 'OK'
    ;;
restart)
    "$0" stop; sleep 1; "$0" start
    ;;
status)
    [ -f "$PIDFILE" ] && kill -0 "$(cat $PIDFILE)" 2>/dev/null \\
        && echo "running (pid $(cat $PIDFILE))" || echo "stopped"
    ;;
*)
    echo "Usage: $0 {start|stop|restart|status}"
    exit 1
esac
""")

    def _build_web_binary(self) -> Path | None:
        """Клонирует/обновляет tinyWiFi и собирает бинарник cargo build --release.

        Возвращает путь к скомпилированному tinywifi-web или None при ошибке.
        Результат кешируется: повторная сборка запускается только при изменении HEAD.
        """
        repo = self._WEB_REPO_DIR
        bin_cache = self._WEB_BIN_DIR
        cargo = self._find_cargo()
        if cargo is None:
            logging.warning("cargo не найден — пропускаю сборку tinywifi-web")
            return None

        # Клонируем или обновляем репо
        try:
            if not (repo / ".git").exists():
                logging.info("Клонирую tinyWiFi…")
                repo.parent.mkdir(parents=True, exist_ok=True)
                subprocess.run(["git", "clone", "--depth=1", self._WEB_REPO, str(repo)],
                                check=True, timeout=120)
            else:
                logging.info("Обновляю tinyWiFi…")
                subprocess.run(["git", "-C", str(repo), "pull", "--ff-only"],
                                check=True, timeout=60)
        except Exception as exc:
            logging.warning("git clone/pull tinyWiFi: %s", exc)
            # Если репо уже есть — работаем с тем что есть
            if not (repo / "Cargo.toml").exists():
                return None

        # Вычисляем HEAD commit для кеша
        try:
            head = subprocess.run(
                ["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
                capture_output=True, text=True, check=True, timeout=10,
            ).stdout.strip()
        except Exception:
            head = "unknown"

        cached_bin = bin_cache / f"tinywifi-web-{head}"
        if cached_bin.exists():
            logging.info("tinywifi-web кеш актуален (%s)", head)
            return cached_bin

        # Собираем
        logging.info("Собираю tinywifi-web (cargo build --release, commit %s)…", head)
        try:
            subprocess.run(
                [cargo, "build", "--release", "--bin", "tinywifi-web"],
                cwd=str(repo), check=True, timeout=600,
            )
        except Exception as exc:
            logging.error("cargo build tinywifi-web: %s", exc)
            return None

        built = repo / "target" / "release" / "tinywifi-web"
        if not built.exists():
            logging.error("tinywifi-web бинарник не найден после сборки: %s", built)
            return None

        # Кешируем
        bin_cache.mkdir(parents=True, exist_ok=True)
        shutil.copy2(built, cached_bin)
        logging.info("tinywifi-web собран и закеширован: %s", cached_bin)
        return cached_bin

    @staticmethod
    def _find_cargo() -> str | None:
        """Ищет cargo: в PATH, ~/.cargo/bin/, /home/codex/.cargo/bin/, /usr/bin/."""
        candidates = [
            "cargo",
            "/root/.cargo/bin/cargo",
            os.path.expanduser("~/.cargo/bin/cargo"),
            "/home/codex/.cargo/bin/cargo",
            "/usr/bin/cargo",
            "/usr/local/bin/cargo",
        ]
        for candidate in candidates:
            try:
                result = subprocess.run([candidate, "--version"], capture_output=True,
                                        check=True, timeout=5)
                logging.debug("cargo найден: %s (%s)", candidate,
                              result.stdout.decode().strip())
                return candidate
            except Exception:
                continue
        return None

    # ------------------------------------------------------------------
    # Bluetooth — S04bluetooth init + /etc/bluetooth/main.conf
    # ------------------------------------------------------------------

    def _bluetooth_conf(self, root: Path) -> None:
        # bluez5 main.conf — minimal, no agent by default
        (root / "etc" / "bluetooth" / "main.conf").write_text(
            "[Policy]\n"
            "AutoEnable=true\n\n"
            "[General]\n"
            "Name=TinyWifi\n"
            "Class=0x000100\n"
            "DiscoverableTimeout=0\n"
        )

        self._write_exec(root / "etc" / "init.d" / "S04bluetooth", """\
#!/bin/sh
# S04bluetooth — init BCM43436 Bluetooth on Pi Zero 2W
# btattach loads firmware via UART and creates hci0; bluetoothd handles pairing.
BT_UART=/dev/ttyAMA0
BT_SPEED=3000000

# On QEMU virt, ttyAMA0 is the serial console — btattach at 3 Mbaud would
# corrupt the console. Detect QEMU via virtio bus or device-tree compatible.
_is_qemu() {
    grep -q "QEMU\\|virt" /sys/firmware/devicetree/base/compatible 2>/dev/null || \\
    [ -d /sys/bus/platform/devices/virtio-mmio.0 ] || \\
    ls /sys/bus/virtio/devices/ 2>/dev/null | grep -q .
}

case "$1" in
start)
    printf 'Starting Bluetooth: '
    if _is_qemu; then
        echo "QEMU detected — skipping btattach (no real BCM chip)"
    elif [ -e "$BT_UART" ]; then
        # Attach BCM UART HCI (loads firmware, creates hci0)
        btattach -B "$BT_UART" -P bcm -S "$BT_SPEED" &
        echo $! > /run/btattach.pid
        sleep 2
        # Bring hci0 up
        hciconfig hci0 up 2>/dev/null || true
        # Start bluetoothd for pairing support
        if command -v bluetoothd >/dev/null 2>&1; then
            bluetoothd &
            echo $! > /run/bluetoothd.pid
        fi
    else
        echo "UART $BT_UART not found — skipping btattach (kernel may handle HCI)"
    fi
    echo 'OK'
    ;;
stop)
    printf 'Stopping Bluetooth: '
    [ -f /run/bluetoothd.pid ] && kill "$(cat /run/bluetoothd.pid)" 2>/dev/null || true
    [ -f /run/btattach.pid ]   && kill "$(cat /run/btattach.pid)"   2>/dev/null || true
    hciconfig hci0 down 2>/dev/null || true
    echo 'OK'
    ;;
restart)
    "$0" stop; sleep 1; "$0" start
    ;;
status)
    hciconfig hci0 2>/dev/null || echo 'hci0 not found'
    ;;
*)
    echo "Usage: $0 {start|stop|restart|status}"
    exit 1
esac
""")

    # ------------------------------------------------------------------
    # /www/index.html
    # ------------------------------------------------------------------

    def _www_index(self, root: Path) -> None:
        (root / "www" / "index.html").write_text(
            f"<!DOCTYPE html>\n"
            f"<html lang=\"ru\">\n"
            f"<head>\n"
            f"<meta charset=\"UTF-8\">\n"
            f"<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
            f"<title>TinyWifi {self.version}</title>\n"
            f"<style>\n"
            f"  body {{ font-family: monospace; background: #111; color: #0f0; margin: 2em; }}\n"
            f"  h1   {{ color: #0f0; }}\n"
            f"  .box {{ border: 1px solid #0f0; padding: 1em; margin-top: 1em; }}\n"
            f"  code {{ background: #222; padding: 2px 6px; }}\n"
            f"</style>\n"
            f"</head>\n"
            f"<body>\n"
            f"<h1>&#128241; 4stm4 TinyWifi {self.version}</h1>\n"
            f"<div class=\"box\">\n"
            f"  <p><b>AP SSID:</b> {self.ap_ssid}</p>\n"
            f"  <p><b>IP:</b> {AP_IP}/24</p>\n"
            f"  <p><b>DHCP:</b> {AP_POOL_START} &ndash; {AP_POOL_END}</p>\n"
            f"  <p><b>SSH:</b> <code>ssh root@{AP_IP}</code></p>\n"
            f"</div>\n"
            f"<p style=\"color:#060;margin-top:2em;\">Phase 1 &mdash; shell scripts &amp; init.d</p>\n"
            f"</body>\n"
            f"</html>\n"
        )

    # ------------------------------------------------------------------
    # SSH — root password + ~/.ssh
    # ------------------------------------------------------------------

    def _set_root_password(self, root: Path) -> None:
        """Устанавливает пароль root в /etc/shadow для dropbear SSH.

        По умолчанию «tinywifi123» (переопределяется NETOS_SSH_PASSWORD).
        Dropbear отклоняет пустой пароль — без этой правки SSH недоступен.
        """
        password = os.environ.get("NETOS_SSH_PASSWORD", "tinywifi123")

        # Генерируем SHA-512 crypt-хэш через openssl
        pw_hash: str | None = None
        try:
            res = subprocess.run(
                ["openssl", "passwd", "-6", password],
                capture_output=True, text=True, timeout=10,
            )
            if res.returncode == 0:
                pw_hash = res.stdout.strip()
        except Exception as exc:
            logging.warning("openssl passwd failed: %s", exc)

        if not pw_hash:
            logging.warning("root SSH password not set (openssl unavailable)")
            return

        # Обновляем /etc/shadow
        shadow_path = root / "etc" / "shadow"
        lines = shadow_path.read_text().splitlines() if shadow_path.exists() else []
        new_entry = f"root:{pw_hash}:19000:0:99999:7:::"
        new_lines: list[str] = []
        root_found = False
        for line in lines:
            if line.startswith("root:"):
                new_lines.append(new_entry)
                root_found = True
            else:
                new_lines.append(line)
        if not root_found:
            new_lines.insert(0, new_entry)
        shadow_path.write_text("\n".join(new_lines) + "\n")
        shadow_path.chmod(0o640)

        # /etc/passwd — root должен иметь 'x' (пароль в shadow)
        passwd_path = root / "etc" / "passwd"
        if passwd_path.exists():
            passwd_path.write_text(
                re.sub(
                    r"^(root:)[^:]*(:)",
                    r"\1x\2",
                    passwd_path.read_text(),
                    count=1,
                    flags=re.MULTILINE,
                )
            )

        # /root/.ssh — нужна для key-based auth
        # Устанавливаем owner UID/GID=0 (root), потому что сборка может
        # выполняться под непривилегированным пользователем, и dropbear
        # откажется читать authorized_keys из директории, принадлежащей
        # чужому UID.
        ssh_dir = root / "root" / ".ssh"
        ssh_dir.mkdir(parents=True, exist_ok=True)
        ssh_dir.chmod(0o700)
        try:
            os.chown(root / "root", 0, 0)
            os.chown(ssh_dir, 0, 0)
        except PermissionError:
            pass  # В non-root build среде chown недоступен — продолжаем

    # ------------------------------------------------------------------
    # Нейтрализация конфликтующих init-скриптов из пакетов
    # ------------------------------------------------------------------

    def _disable_conflicting_inits(self, root: Path) -> None:
        """Перезаписывает init-скрипты, которые конфликтуют с S10tinywifi.

        S10nanodhcp (из пакета nanodhcp) запускает nanodhcp на eth0 —
        заменяем no-op: S10tinywifi сам стартует nanodhcp на wlan0.
        S39wifi (NetworkAdapter) — не пишется в tinywifi-пути, но на всякий случай.
        """
        noop = "#!/bin/sh\n# managed by S10tinywifi\nexit 0\n"
        for name in ("S10nanodhcp", "S39wifi", "S40network", "S41nftables"):
            p = root / "etc" / "init.d" / name
            if p.exists():
                p.write_text(noop)
