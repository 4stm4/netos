"""TinyWifi appliance provisioner.

Writes all rootfs files for a minimal Wi-Fi AP appliance (zero2w target):
  /etc/hostname, /etc/hosts, /etc/resolv.conf, /etc/fstab, /etc/motd
  /etc/init.d/S00mount, S01mdev, S02modules, S03network, S10tinywifi
  /etc/hostapd/hostapd.conf
  /etc/nftables/tinywifi.nft
  /etc/nanodhcp/nanodhcp.conf
  /etc/tinywifi/tinywifi.toml  (зарезервировано для CLI v0.2+)
  /www/index.html
  runtime dirs: /var/lib/nanodhcp, /var/lib/tinywifi, /var/log, /run, /tmp

Вызывается из main.py при NETOS_APPLIANCE=tinywifi вместо
install_webui_assets / install_nervum_assets / install_ovsdb_assets.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

# Branding — переопределяется env-переменными из профиля
_HOSTNAME = os.environ.get("NETOS_HOSTNAME", "tinywifi")
_VERSION  = os.environ.get("NETOS_VERSION",  "0.1.0")

# AP параметры — жёсткие дефолты; переопределяются env из профиля
AP_SSID    = os.environ.get("NETOS_WIFI_SSID",    "TinyWifi")
AP_PSK     = os.environ.get("NETOS_WIFI_PSK",     "tinywifi123")
AP_COUNTRY = os.environ.get("NETOS_WIFI_COUNTRY", "US")
AP_CHANNEL = os.environ.get("NETOS_WIFI_CHANNEL", "6")

AP_IFACE      = "wlan0"
AP_IP         = "192.168.44.1"
AP_SUBNET     = "192.168.44.0/24"
AP_POOL_START = "192.168.44.10"
AP_POOL_END   = "192.168.44.200"
WAN_IFACE     = "eth0"


class TinyWifiSetup:
    """Provisioner rootfs для TinyWifi AP appliance."""

    def install(self, rootfs_path: Path) -> None:
        root = Path(rootfs_path)
        self._directories(root)
        self._base_configs(root)
        self._init_scripts(root)
        self._hostapd_conf(root)
        self._nftables_conf(root)
        self._nanodhcp_conf(root)
        self._tinywifi_conf(root)
        self._www_index(root)
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
        (root / "etc" / "hostname").write_text(f"{_HOSTNAME}\n")
        (root / "etc" / "hosts").write_text(
            "127.0.0.1   localhost\n"
            f"127.0.1.1   {_HOSTNAME}\n"
            f"{AP_IP}  {_HOSTNAME}\n"
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
            f"4stm4 TinyWifi {_VERSION}\n"
            f"  AP:  {AP_SSID}  {AP_IP}/24\n"
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
# WiFi драйвер — загружаем через insmod (обходит modprobe/libcrypto).
# Ровно один из двух файлов будет найден в зависимости от платформы:
#   zero2w:    brcmfmac.ko  (реальный BCM43436, firmware из /lib/firmware/brcm/)
#   qemu-wifi: mac80211_hwsim.ko (виртуальный WiFi, без firmware)
for wifi_mod in brcmfmac.ko mac80211_hwsim.ko; do
    path=$(find /lib/modules -name "$wifi_mod" 2>/dev/null | head -1)
    [ -n "$path" ] && insmod "$path" 2>/dev/null || true
done
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

    # brcmfmac загружен как модуль (S02modules insmod), firmware уже прогружена.
    # Ждём появления wlan0 — обычно появляется через 1-3с после insmod.
    for i in $(seq 1 15); do
        ip link show {AP_IFACE} >/dev/null 2>&1 && break
        sleep 1
    done
    if ! ip link show {AP_IFACE} >/dev/null 2>&1; then
        echo "ERROR: {AP_IFACE} not found after 15s" >&2
        exit 1
    fi

    # Устанавливаем regulatory domain до поднятия AP
    command -v iw >/dev/null 2>&1 && iw reg set {AP_COUNTRY} 2>/dev/null || true

    # IP forwarding (NAT)
    echo 1 > /proc/sys/net/ipv4/ip_forward

    # nftables NAT
    if command -v nft >/dev/null 2>&1 && [ -f "$NFT_CONF" ]; then
        nft -f "$NFT_CONF" || true
    fi

    # hostapd — поднимает AP и управляет wlan0
    if command -v hostapd >/dev/null 2>&1 && [ -f "$HOSTAPD_CONF" ]; then
        hostapd -B "$HOSTAPD_CONF" -P /run/hostapd.pid
    fi

    # IP на wlan0 после того как hostapd поднял AP
    ip addr flush dev {AP_IFACE}
    ip addr add {AP_IP}/24 dev {AP_IFACE}

    # nanodhcp — DHCP для клиентов AP
    mkdir -p /var/lib/nanodhcp
    if command -v nanodhcp >/dev/null 2>&1 && [ -f "$NANODHCP_CONF" ]; then
        start-stop-daemon --start --quiet --background \\
            --pidfile /run/nanodhcp.pid --make-pidfile \\
            --exec /usr/sbin/nanodhcp -- "$NANODHCP_CONF"
    fi

    # uhttpd — веб-страница на AP-адресе
    if command -v uhttpd >/dev/null 2>&1 && [ -d "$WWW_ROOT" ]; then
        uhttpd -p {AP_IP}:80 -h "$WWW_ROOT" &
        echo $! > /run/uhttpd.pid
    fi

    echo 'OK'
    echo "TinyWifi: AP={AP_SSID} {AP_IP}/24"
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
            f"ssid={AP_SSID}\n"
            f"hw_mode=g\n"
            f"channel={AP_CHANNEL}\n"
            f"country_code={AP_COUNTRY}\n"
            f"ieee80211d=1\n"
            f"wmm_enabled=1\n"
            f"auth_algs=1\n"
            f"wpa=2\n"
            f"wpa_passphrase={AP_PSK}\n"
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
        (root / "etc" / "tinywifi" / "tinywifi.toml").write_text(
            f"# /etc/tinywifi/tinywifi.toml — зарезервировано для tinywifi CLI (v0.2+)\n\n"
            f"[ap]\n"
            f"ssid = \"{AP_SSID}\"\n"
            f"passphrase = \"{AP_PSK}\"\n"
            f"country = \"{AP_COUNTRY}\"\n"
            f"channel = {AP_CHANNEL}\n"
            f"interface = \"{AP_IFACE}\"\n\n"
            f"[network]\n"
            f"ap_ip = \"{AP_IP}\"\n"
            f"ap_subnet = \"{AP_SUBNET}\"\n"
            f"wan_iface = \"{WAN_IFACE}\"\n\n"
            f"[dhcp]\n"
            f"pool_start = \"{AP_POOL_START}\"\n"
            f"pool_end = \"{AP_POOL_END}\"\n"
            f"lease_time = 86400\n"
        )

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

case "$1" in
start)
    printf 'Starting Bluetooth: '
    # Attach BCM UART HCI (loads firmware, creates hci0) — only if UART exists
    if [ -e "$BT_UART" ]; then
        btattach -B "$BT_UART" -P bcm -S "$BT_SPEED" &
        echo $! > /run/btattach.pid
    else
        echo "UART $BT_UART not found — skipping btattach (kernel may handle HCI)"
    fi
    sleep 2
    # Bring hci0 up
    hciconfig hci0 up 2>/dev/null || true
    # Start bluetoothd for pairing support
    if command -v bluetoothd >/dev/null 2>&1; then
        bluetoothd &
        echo $! > /run/bluetoothd.pid
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
            f"<title>TinyWifi {_VERSION}</title>\n"
            f"<style>\n"
            f"  body {{ font-family: monospace; background: #111; color: #0f0; margin: 2em; }}\n"
            f"  h1   {{ color: #0f0; }}\n"
            f"  .box {{ border: 1px solid #0f0; padding: 1em; margin-top: 1em; }}\n"
            f"  code {{ background: #222; padding: 2px 6px; }}\n"
            f"</style>\n"
            f"</head>\n"
            f"<body>\n"
            f"<h1>&#128241; 4stm4 TinyWifi {_VERSION}</h1>\n"
            f"<div class=\"box\">\n"
            f"  <p><b>AP SSID:</b> {AP_SSID}</p>\n"
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
        import logging
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
        ssh_dir = root / "root" / ".ssh"
        ssh_dir.mkdir(parents=True, exist_ok=True)
        ssh_dir.chmod(0o700)

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
