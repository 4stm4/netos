"""Built-in profile presets for the netOS build configurator.

Each preset is a dict with UI metadata + a ``profile`` dict that maps 1-to-1
to the ``Profile`` model. Calling ``applyPreset`` in the frontend deep-merges
the preset.profile fields into the current form state.
"""
from __future__ import annotations

PRESETS: list[dict] = [
    {
        "id": "qemu-x86-mini",
        "name": "QEMU x86 Mini",
        "icon": "🧊",
        "description": "Минимальная x86_64 initramfs — BusyBox + udhcpd. "
                       "Быстрая сборка (~25 мин), образ ~10 МБ. "
                       "Идеально для тестирования DHCP и сетевых скриптов.",
        "tags": ["qemu", "x86_64", "initramfs", "minimal"],
        "estimated_size_mb": 10,
        "estimated_build_min": 25,
        "profile": {
            "name": "qemu-x86-mini",
            "target": "qemu-x86",
            "branding": {
                "hostname": "netos-mini",
                "console": "ttyS0",
                "version": "0.1.0",
            },
            "packages": {
                "enabled": [],
                "custom": [
                    "BR2_TARGET_ROOTFS_CPIO=y",
                    "BR2_TARGET_ROOTFS_CPIO_GZ=y",
                    "BR2_PACKAGE_BUSYBOX=y",
                    "BR2_PACKAGE_BUSYBOX_SHOW_OTHERS=y",
                    "BR2_PACKAGE_IPROUTE2=y",
                ],
            },
            "image": {"size_mb": 64, "boot_mb": 0},
            "nervum": {"enabled": False},
            "webui": {"source": "runtime"},
        },
    },
    {
        "id": "qemu-x86-nanodhcp",
        "name": "QEMU x86 + nanodhcp",
        "icon": "🛜",
        "description": "x86_64 QEMU образ с nanodhcp — минимальным DHCPv4-сервером на Rust. "
                       "Один статический бинарник без зависимостей. "
                       "Идеально для embedded-апплайансов и изолированных сетей.",
        "tags": ["qemu", "x86_64", "dhcp", "rust", "embedded"],
        "estimated_size_mb": 40,
        "estimated_build_min": 40,
        "profile": {
            "name": "qemu-x86-nanodhcp",
            "target": "qemu-x86",
            "branding": {
                "hostname": "netos-dhcp",
                "console": "ttyS0",
                "version": "0.1.0",
            },
            "packages": {
                "enabled": [],
                "custom": [
                    "BR2_PACKAGE_BUSYBOX=y",
                    "BR2_PACKAGE_BUSYBOX_SHOW_OTHERS=y",
                    "BR2_PACKAGE_IPROUTE2=y",
                    "BR2_PACKAGE_NANODHCP=y",
                    "BR2_TARGET_ROOTFS_TAR=y",
                    "BR2_TARGET_ROOTFS_TAR_NONE=y",
                ],
            },
            "image": {"size_mb": 256, "boot_mb": 64},
            "nervum": {"enabled": False},
            "webui": {"source": "runtime"},
        },
    },
    {
        "id": "qemu-x86-mininet",
        "name": "QEMU x86 Mininet",
        "icon": "🌐",
        "description": "x86_64 QEMU образ с mininet, OVS и dnsmasq. "
                       "Полный сетевой стек для тестирования SDN. "
                       "Сборка ~3–4 ч, образ ~200 МБ qcow2.",
        "tags": ["qemu", "x86_64", "mininet", "ovs", "sdn"],
        "estimated_size_mb": 200,
        "estimated_build_min": 180,
        "profile": {
            "name": "qemu-x86-mininet",
            "target": "qemu-x86",
            "branding": {
                "hostname": "netos-mininet",
                "console": "ttyS0",
                "version": "0.1.0",
            },
            "packages": {
                "enabled": [],
                "custom": [
                    "BR2_PACKAGE_BUSYBOX=y",
                    "BR2_PACKAGE_BUSYBOX_SHOW_OTHERS=y",
                    "BR2_PACKAGE_BASH=y",
                    "BR2_PACKAGE_CA_CERTIFICATES=y",
                    "BR2_PACKAGE_IPROUTE2=y",
                    "BR2_PACKAGE_NFTABLES=y",
                    "BR2_PACKAGE_DNSMASQ=y",
                    "BR2_PACKAGE_OPENVSWITCH=y",
                    "BR2_PACKAGE_MININET=y",
                    "BR2_TARGET_ROOTFS_TAR=y",
                    "BR2_TARGET_ROOTFS_TAR_NONE=y",
                ],
            },
            "image": {"size_mb": 512, "boot_mb": 64},
            "nervum": {"enabled": False},
            "webui": {"source": "runtime"},
        },
    },
    {
        "id": "qemu-virt-arm64",
        "name": "QEMU ARM64 virt",
        "icon": "💻",
        "description": "Generic ARM64 QEMU virt-машина. "
                       "Удобна для разработки на Apple Silicon / ARM-хостах. "
                       "Полный netOS-стек с OVS и Python.",
        "tags": ["qemu", "arm64", "virt", "development"],
        "estimated_size_mb": 300,
        "estimated_build_min": 120,
        "profile": {
            "name": "qemu-virt-arm64",
            "target": "qemu-virt",
            "branding": {
                "hostname": "netos-virt",
                "console": "ttyAMA0",
                "version": "0.1.0",
            },
            "packages": {
                "enabled": [],
                "custom": [],
            },
            "image": {"size_mb": 512, "boot_mb": 64},
        },
    },
    {
        "id": "rpi5",
        "name": "Raspberry Pi 5",
        "icon": "🍓",
        "description": "Полный образ для RPi 5 / BCM2712. "
                       "OVS, Python, Web UI, SSH. "
                       "SD-карта или NVMe через PCIe HAT.",
        "tags": ["rpi5", "arm64", "hardware", "production"],
        "estimated_size_mb": 1024,
        "estimated_build_min": 240,
        "profile": {
            "name": "rpi5",
            "target": "pi5",
            "branding": {
                "hostname": "netos-rpi5",
                "console": "ttyAMA0",
                "version": "0.1.0",
            },
            "packages": {
                "enabled": [],
                "custom": [],
            },
            "image": {"size_mb": 1024, "boot_mb": 256},
        },
    },
    {
        "id": "zero2w-wireless",
        "name": "Pi Zero 2W + Wi-Fi",
        "icon": "📡",
        "description": "Компактный образ для Pi Zero 2W с поддержкой Wi-Fi. "
                       "wpa_supplicant, brcmfmac firmware, минимальный footprint.",
        "tags": ["zero2w", "arm64", "wireless", "embedded"],
        "estimated_size_mb": 512,
        "estimated_build_min": 200,
        "profile": {
            "name": "zero2w-wireless",
            "target": "zero2w",
            "branding": {
                "hostname": "netos-zero2w",
                "console": "ttyAMA0",
                "version": "0.1.0",
            },
            "packages": {
                "enabled": [],
                "custom": [
                    "BR2_PACKAGE_WPA_SUPPLICANT=y",
                    "BR2_PACKAGE_WPA_SUPPLICANT_NL80211=y",
                    "BR2_PACKAGE_WPA_SUPPLICANT_CLI=y",
                    "BR2_PACKAGE_IW=y",
                    "BR2_PACKAGE_WIRELESS_TOOLS=y",
                    "BR2_PACKAGE_BRCMFMAC_SDIO_FIRMWARE_RPI=y",
                    "BR2_PACKAGE_BRCMFMAC_SDIO_FIRMWARE_RPI_WIFI=y",
                ],
            },
            "image": {"size_mb": 512, "boot_mb": 256},
        },
    },
]
