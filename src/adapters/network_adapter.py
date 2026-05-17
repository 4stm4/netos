from pathlib import Path
import os
from core.interfaces import NetworkConfiguratorPort

class NetworkAdapter(NetworkConfiguratorPort):
    def setup_network(self, rootfs_path: Path):
        address = os.environ.get("NETOS_ETH0_ADDRESS")
        netmask = os.environ.get("NETOS_ETH0_NETMASK", "255.255.255.0")
        gateway = os.environ.get("NETOS_ETH0_GATEWAY")
        dns = os.environ.get("NETOS_ETH0_DNS")
        wifi_ssid = os.environ.get("NETOS_WIFI_SSID")
        wifi_psk = os.environ.get("NETOS_WIFI_PSK", "")
        wifi_country = os.environ.get("NETOS_WIFI_COUNTRY", "US")
        wifi_bootstrap = os.environ.get("NETOS_WIFI_BOOTSTRAP", "1")
        wifi_bootstrap_enabled = wifi_bootstrap.lower() not in {"0", "false", "no", "off"}

        if address:
            lines = [
                "auto lo",
                "iface lo inet loopback",
                "",
                "auto eth0",
                "iface eth0 inet static",
                f"    address {address}",
                f"    netmask {netmask}",
            ]
            if gateway:
                lines.append(f"    gateway {gateway}")
            if dns:
                lines.append(f"    dns-nameservers {dns}")
            interfaces_config = "\n".join(lines) + "\n"
        else:
            interfaces_config = (
                "auto lo\n"
                "iface lo inet loopback\n"
                "\n"
                "auto eth0\n"
                "iface eth0 inet dhcp\n"
            )
        if wifi_ssid or wifi_bootstrap_enabled:
            interfaces_config += "\nallow-hotplug wlan0\niface wlan0 inet dhcp\n"

        network_dir = rootfs_path / "etc/network"
        network_dir.mkdir(parents=True, exist_ok=True)
        (network_dir / "interfaces").write_text(interfaces_config)
        if dns:
            (rootfs_path / "etc" / "resolv.conf").write_text(f"nameserver {dns.split()[0]}\n")
        if wifi_ssid:
            self._write_wifi_config(rootfs_path, wifi_ssid, wifi_psk, wifi_country)
        elif wifi_bootstrap_enabled:
            self._install_wifi_init(rootfs_path)

    def _write_wifi_config(self, rootfs_path: Path, ssid: str, psk: str, country: str):
        def wpa_quote(value: str) -> str:
            return value.replace("\\", "\\\\").replace('"', '\\"')

        network_lines = [f'    ssid="{wpa_quote(ssid)}"']
        if psk:
            network_lines.append(f'    psk="{wpa_quote(psk)}"')
        else:
            network_lines.append("    key_mgmt=NONE")

        (rootfs_path / "etc" / "wpa_supplicant.conf").write_text(
            "ctrl_interface=/var/run/wpa_supplicant\n"
            "update_config=1\n"
            f"country={country}\n"
            "\n"
            "network={\n"
            + "\n".join(network_lines)
            + "\n}\n"
        )
        (rootfs_path / "etc" / "wpa_supplicant.conf").chmod(0o600)

        self._install_wifi_init(rootfs_path)

    def _install_wifi_init(self, rootfs_path: Path):
        init_dir = rootfs_path / "etc" / "init.d"
        init_dir.mkdir(parents=True, exist_ok=True)
        init_path = init_dir / "S39wifi"
        init_path.write_text("""#!/bin/sh

CONF=/etc/wpa_supplicant.conf
BOOT_MNT="${NETOS_BOOT_MNT:-/boot}"
BOOT_DEV="${NETOS_BOOT_DEV:-/dev/mmcblk0p1}"

mount_boot() {
    mkdir -p "$BOOT_MNT"
    mountpoint -q "$BOOT_MNT" && return 0
    mount -t vfat -o ro "$BOOT_DEV" "$BOOT_MNT" 2>/dev/null && return 0
    mount "$BOOT_DEV" "$BOOT_MNT" 2>/dev/null && return 0
    return 1
}

provision_conf() {
    [ -f "$CONF" ] && return 0
    mount_boot || return 1
    for candidate in "$BOOT_MNT/wpa_supplicant.conf" "$BOOT_MNT/netos-wifi.conf"; do
        if [ -f "$candidate" ]; then
            cp "$candidate" "$CONF"
            chmod 600 "$CONF"
            return 0
        fi
    done
    return 1
}

provision_conf || exit 0
command -v wpa_supplicant >/dev/null 2>&1 || exit 0

mkdir -p /var/run/wpa_supplicant
rfkill unblock wifi 2>/dev/null || true
modprobe brcmfmac 2>/dev/null || true
for _ in 1 2 3 4 5 6 7 8 9 10; do
    ip link show wlan0 >/dev/null 2>&1 && break
    sleep 1
done
ip link set wlan0 up 2>/dev/null || true

if ! pgrep -f "wpa_supplicant.*wlan0" >/dev/null 2>&1; then
    wpa_supplicant -B -i wlan0 -c "$CONF" >/var/log/wpa_supplicant.log 2>&1 || true
fi

if command -v udhcpc >/dev/null 2>&1; then
    udhcpc -i wlan0 -b -q -t 20 >/var/log/udhcpc-wlan0.log 2>&1 || true
fi
exit 0
""")
        init_path.chmod(0o755)
