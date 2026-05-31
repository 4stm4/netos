from dataclasses import dataclass
from typing import Optional


COMMON_KERNEL_OPTIONS = (
    "CONFIG_CGROUPS=y",
    "CONFIG_NAMESPACES=y",
    "CONFIG_OVERLAY_FS=y",
    "CONFIG_TMPFS=y",
    "CONFIG_IPV6=y",
    "CONFIG_KVM=y",
    "CONFIG_VHOST_NET=y",
    "CONFIG_VFIO=y",
    "CONFIG_VFIO_PCI=y",
    "CONFIG_OPENVSWITCH=y",
    "CONFIG_ISCSI_TCP=y",
    "CONFIG_MULTIPATH=y",
    "CONFIG_WATCHDOG=y",
    "CONFIG_EXT4_FS=y",
    "CONFIG_FAT_FS=y",
    "CONFIG_MSDOS_FS=y",
    "CONFIG_VFAT_FS=y",
    "CONFIG_NLS_CODEPAGE_437=y",
    "CONFIG_NLS_ISO8859_1=y",
    "CONFIG_DEVTMPFS=y",
    "CONFIG_DEVTMPFS_MOUNT=y",
)


QEMU_WIFI_KERNEL_OPTIONS = COMMON_KERNEL_OPTIONS + (
    "CONFIG_KVM=n",
    "CONFIG_VHOST_NET=n",
    "CONFIG_VFIO=n",
    "CONFIG_VFIO_PCI=n",
    "CONFIG_PCI=y",
    "CONFIG_PCI_HOST_GENERIC=y",
    "CONFIG_VIRTIO=y",
    "CONFIG_VIRTIO_PCI=y",
    "CONFIG_VIRTIO_MMIO=y",
    "CONFIG_VIRTIO_BLK=y",
    "CONFIG_VIRTIO_NET=y",
    "CONFIG_SERIAL_AMBA_PL011=y",
    "CONFIG_SERIAL_AMBA_PL011_CONSOLE=y",
    "CONFIG_RTC_DRV_PL031=y",
    # WiFi simulation via mac80211_hwsim — для TinyWifi AP тестов в QEMU
    "CONFIG_RFKILL=y",
    "CONFIG_WIRELESS=y",
    "CONFIG_CFG80211=y",
    "CONFIG_MAC80211=y",
    "CONFIG_MAC80211_HWSIM=m",  # виртуальный WiFi: создаёт wlan0, работает с hostapd/nl80211
    "CONFIG_MODULES=y",
    "CONFIG_MODULE_UNLOAD=y",
    "CONFIG_MODULE_COMPRESS_XZ=n",
    "CONFIG_MODULE_COMPRESS_NONE=y",
)


QEMU_VIRT_KERNEL_OPTIONS = COMMON_KERNEL_OPTIONS + (
    "CONFIG_KVM=n",
    "CONFIG_VHOST_NET=n",
    "CONFIG_VFIO=n",
    "CONFIG_VFIO_PCI=n",
    "CONFIG_PCI=y",
    "CONFIG_PCI_HOST_GENERIC=y",
    "CONFIG_VIRTIO=y",
    "CONFIG_VIRTIO_PCI=y",
    "CONFIG_VIRTIO_MMIO=y",
    "CONFIG_VIRTIO_BLK=y",
    "CONFIG_VIRTIO_NET=y",
    "CONFIG_SERIAL_AMBA_PL011=y",
    "CONFIG_SERIAL_AMBA_PL011_CONSOLE=y",
    "CONFIG_RTC_DRV_PL031=y",
)


QEMU_X86_KERNEL_OPTIONS = COMMON_KERNEL_OPTIONS + (
    "CONFIG_KVM=n",
    "CONFIG_VHOST_NET=n",
    "CONFIG_VFIO=n",
    "CONFIG_VFIO_PCI=n",
    "CONFIG_PCI=y",
    "CONFIG_PCI_MSI=y",
    "CONFIG_VIRTIO=y",
    "CONFIG_VIRTIO_PCI=y",
    "CONFIG_VIRTIO_BLK=y",
    "CONFIG_VIRTIO_NET=y",
    "CONFIG_HW_RANDOM_VIRTIO=y",
    "CONFIG_SERIAL_8250=y",
    "CONFIG_SERIAL_8250_CONSOLE=y",
    "CONFIG_SERIAL_8250_PCI=y",
)


ZERO2W_KERNEL_OPTIONS = COMMON_KERNEL_OPTIONS + (
    "CONFIG_KVM=n",
    "CONFIG_VFIO=n",
    "CONFIG_VFIO_PCI=n",
    "CONFIG_RFKILL=y",
    "CONFIG_WIRELESS=y",
    "CONFIG_CFG80211=y",
    "CONFIG_MAC80211=y",
    # brcmfmac as a module (=m): driver loads AFTER rootfs is mounted, so
    # firmware in /lib/firmware/brcm/ is accessible at probe time.
    # Built-in (=y) caused error -2: driver probed at ~2.9s, rootfs at ~3.37s.
    # cfg80211/mac80211/brcmutil stay built-in so brcmfmac.ko's symbols resolve.
    "CONFIG_BRCMUTIL=y",
    "CONFIG_BRCMFMAC=m",
    "CONFIG_BRCMFMAC_SDIO=y",
    "CONFIG_MODULES=y",
    "CONFIG_MODULE_UNLOAD=y",
    # Ship uncompressed .ko: kernel has no CONFIG_MODULE_DECOMPRESS and the
    # rootfs kmod is built without liblzma, so .ko.xz modules fail to load.
    "CONFIG_MODULE_COMPRESS_XZ=n",
    "CONFIG_MODULE_COMPRESS_NONE=y",
    # SIM800C USB GSM dongle — support CP2102, CH340 and CDC-ACM bridges
    "CONFIG_USB_SERIAL=y",
    "CONFIG_USB_SERIAL_CP210X=y",
    "CONFIG_USB_SERIAL_CH341=y",
    "CONFIG_USB_ACM=y",
    # PPP for GPRS data over the modem
    "CONFIG_PPP=y",
    "CONFIG_PPP_ASYNC=y",
    "CONFIG_PPP_DEFLATE=y",
    "CONFIG_PPP_BSDCOMP=y",
    # Bluetooth — BCM43436 on Pi Zero 2W (UART-based HCI)
    "CONFIG_BT=y",
    "CONFIG_BT_RFCOMM=y",
    "CONFIG_BT_RFCOMM_TTY=y",
    "CONFIG_BT_BNEP=y",
    "CONFIG_BT_HIDP=y",
    "CONFIG_BT_HCIUART=y",
    "CONFIG_BT_HCIUART_BCM=y",
    # HID input for BT keyboard
    "CONFIG_HID=y",
    "CONFIG_HID_GENERIC=y",
    "CONFIG_INPUT_EVDEV=y",
    "CONFIG_UHID=y",
    # ---- Slim kernel for headless WiFi AP router ----
    # No sound — saves ~7 MB of modules
    "CONFIG_SOUND=n",
    "CONFIG_SND=n",
    # No media/DVB/cameras/FM-radio — saves ~14 MB of modules
    "CONFIG_MEDIA_SUPPORT=n",
    "CONFIG_VIDEO_DEV=n",
    "CONFIG_RC_CORE=n",
    # Framebuffer console on HDMI so the kernel boot log / panic is visible
    # during hardware bring-up. No initramfs here, so the display driver must
    # be built-in (=y) to paint the console at boot — vc4 KMS + fbcon.
    "CONFIG_DRM=y",
    "CONFIG_DRM_VC4=y",
    "CONFIG_DRM_FBDEV_EMULATION=y",
    "CONFIG_FB=y",
    "CONFIG_FRAMEBUFFER_CONSOLE=y",
    # No RAID/LVM/multipath — single SD card
    "CONFIG_MD=n",
    "CONFIG_DM_MULTIPATH=n",
    # No industrial I/O or 1-wire sensors
    "CONFIG_IIO=n",
    "CONFIG_W1=n",
    # No joystick/gameport (keep INPUT_EVDEV + UHID for BT keyboard)
    "CONFIG_GAMEPORT=n",
    "CONFIG_INPUT_JOYSTICK=n",
    "CONFIG_INPUT_TOUCHSCREEN=n",
    "CONFIG_INPUT_TABLET=n",
    # Exotic filesystems not needed on SD-card router — saves ~13 MB
    "CONFIG_XFS_FS=n",
    "CONFIG_BTRFS_FS=n",
    "CONFIG_OCFS2_FS=n",
    "CONFIG_GFS2_FS=n",
    "CONFIG_CEPH_FS=n",
    "CONFIG_UBIFS_FS=n",
    "CONFIG_NFS_FS=n",
    "CONFIG_NFSD=n",
    "CONFIG_CIFS=n",
    "CONFIG_SMB_SERVER=n",
    # Network protocols not used in AP mode
    "CONFIG_ATM=n",
    "CONFIG_DECNET=n",
    "CONFIG_IPX=n",
    "CONFIG_APPLETALK=n",
    "CONFIG_CAN=n",
    "CONFIG_BATMAN_ADV=n",
    "CONFIG_SCTP=n",
    # OVS not needed on TinyWifi AP
    "CONFIG_OPENVSWITCH=n",
    # Staging drivers
    "CONFIG_STAGING=n",
    # Hardware monitoring — no sensors on this board
    "CONFIG_HWMON=n",
    # Non-brcmfmac wireless drivers — Pi Zero 2W only has BCM43436
    "CONFIG_ATH_COMMON=n",
    "CONFIG_ATH9K=n",
    "CONFIG_ATH9K_HTC=n",
    "CONFIG_RT2X00=n",
    "CONFIG_IWLWIFI=n",
    "CONFIG_MEDIATEK_MT76=n",
    "CONFIG_MT7601U=n",       # legacy MediaTek driver, separate from mt76
    "CONFIG_WL18XX=n",
    "CONFIG_MWIFIEX=n",
    "CONFIG_MWL8K=n",
    "CONFIG_B43=n",
    "CONFIG_B43LEGACY=n",
    "CONFIG_BRCMSMAC=n",
    # Filesystems seen still compiling — not needed on SD-card AP
    "CONFIG_NTFS_FS=n",       # legacy NTFS driver
    "CONFIG_NTFS3_FS=n",      # modern NTFS3 driver
    "CONFIG_UDF_FS=n",        # optical disc filesystem
    "CONFIG_REISERFS_FS=n",   # legacy ReiserFS
    "CONFIG_DLM=n",           # distributed lock manager (cluster FS)
    # Amateur radio — no ham radio on this device
    "CONFIG_HAMRADIO=n",
    # Pi Zero 2W has no built-in Ethernet (only WiFi + USB-OTG)
    "CONFIG_ETHERNET=n",
)


@dataclass(frozen=True)
class TargetConfig:
    name: str
    description: str
    kernel_defconfig: str
    kernel_filename: str
    image_name: str
    boot_config_lines: tuple[str, ...]
    boot_cmdline: str
    required_boot_files: tuple[str, ...]
    boot_firmware_files: tuple[str, ...]
    buildroot_package_lines: tuple[str, ...]
    install_boot_files: bool
    kernel_config_options: tuple[str, ...]
    build_kernel_modules: bool
    image_size_mb: int
    boot_size_mb: int
    kernel_source: str = "rpi"       # "rpi" | "mainline"
    kernel_arch: str = "arm64"       # kernel ARCH= value
    cross_compile: str = "aarch64-linux-gnu-"  # CROSS_COMPILE= value
    buildroot_arch: str = "aarch64"  # BR2_<arch>=y in Buildroot defconfig
    qemu_machine: Optional[str] = None
    qemu_cpu: Optional[str] = None
    qemu_root_device: Optional[str] = None
    qemu_requires_dtb: bool = False
    qemu_dtb_name: Optional[str] = None

    @property
    def qemu_supported(self) -> bool:
        return self.qemu_machine is not None


TARGETS = {
    "pi5": TargetConfig(
        name="pi5",
        description="Raspberry Pi 5 / BCM2712 hardware image",
        kernel_defconfig="bcm2712_defconfig",
        kernel_filename="kernel_2712.img",
        image_name="raspi.img",
        boot_config_lines=(
            "arm_64bit=1",
            "enable_uart=1",
            "os_check=0",
            "uart_2ndstage=1",
            "dtdebug=1",
            "dtoverlay=vc4-kms-v3d",
            "max_framebuffers=2",
        ),
        boot_cmdline=(
            "console=serial0,115200 console=tty1 "
            "root=/dev/mmcblk0p2 rootfstype=ext4 rw fsck.repair=yes rootwait "
            "loglevel=8 ignore_loglevel printk.time=1"
        ),
        required_boot_files=(
            "config.txt",
            "cmdline.txt",
            "kernel_2712.img",
            "bcm2712-rpi-5-b.dtb",
        ),
        boot_firmware_files=(),
        buildroot_package_lines=(),
        install_boot_files=True,
        kernel_config_options=COMMON_KERNEL_OPTIONS,
        build_kernel_modules=True,
        image_size_mb=1024,
        boot_size_mb=256,
    ),
    "zero2w": TargetConfig(
        name="zero2w",
        description="Raspberry Pi Zero 2 W / BCM2710 ARM64 hardware image",
        kernel_defconfig="bcm2711_defconfig",
        kernel_filename="kernel8.img",
        image_name="raspi-zero2w.img",
        boot_config_lines=(
            "arm_64bit=1",
            "enable_uart=1",
            "os_check=0",
            "uart_2ndstage=1",
            "dtdebug=1",
            "dtoverlay=vc4-kms-v3d",
            "max_framebuffers=2",
        ),
        boot_cmdline=(
            "console=serial0,115200 console=tty1 "
            "root=/dev/mmcblk0p2 rootfstype=ext4 rw fsck.repair=yes rootwait "
            "loglevel=8 ignore_loglevel printk.time=1"
        ),
        required_boot_files=(
            "config.txt",
            "cmdline.txt",
            "kernel8.img",
            "bcm2710-rpi-zero-2-w.dtb",
            "bootcode.bin",
            "start.elf",
            "fixup.dat",
        ),
        boot_firmware_files=(
            "bootcode.bin",
            "start.elf",
            "fixup.dat",
            "LICENCE.broadcom",
        ),
        buildroot_package_lines=(
            "BR2_PACKAGE_WPA_SUPPLICANT=y",
            "BR2_PACKAGE_WPA_SUPPLICANT_NL80211=y",
            "BR2_PACKAGE_WPA_SUPPLICANT_CLI=y",
            "BR2_PACKAGE_WPA_SUPPLICANT_PASSPHRASE=y",
            "BR2_PACKAGE_IW=y",
            "BR2_PACKAGE_WIRELESS_TOOLS=y",
            "BR2_PACKAGE_BRCMFMAC_SDIO_FIRMWARE_RPI=y",
            "BR2_PACKAGE_BRCMFMAC_SDIO_FIRMWARE_RPI_WIFI=y",
        ),
        install_boot_files=True,
        kernel_config_options=ZERO2W_KERNEL_OPTIONS,
        build_kernel_modules=True,
        image_size_mb=192,
        boot_size_mb=48,
    ),
    "pi4": TargetConfig(
        name="pi4",
        description="Raspberry Pi 4 / BCM2711 hardware image",
        kernel_defconfig="bcm2711_defconfig",
        kernel_filename="kernel8.img",
        image_name="raspi-pi4.img",
        boot_config_lines=(
            "arm_64bit=1",
            "enable_uart=1",
            "os_check=0",
            "uart_2ndstage=1",
            "dtdebug=1",
            "dtoverlay=vc4-kms-v3d",
            "max_framebuffers=2",
        ),
        boot_cmdline=(
            "console=serial0,115200 console=tty1 "
            "root=/dev/mmcblk0p2 rootfstype=ext4 rw fsck.repair=yes rootwait "
            "loglevel=8 ignore_loglevel printk.time=1"
        ),
        required_boot_files=(
            "config.txt",
            "cmdline.txt",
            "kernel8.img",
            "bcm2711-rpi-4-b.dtb",
        ),
        boot_firmware_files=(),
        buildroot_package_lines=(),
        install_boot_files=True,
        kernel_config_options=COMMON_KERNEL_OPTIONS,
        build_kernel_modules=True,
        image_size_mb=1024,
        boot_size_mb=256,
    ),
    "qemu-x86": TargetConfig(
        name="qemu-x86",
        description="x86_64 QEMU image — удобен для тестирования на x86-хостах без эмуляции ARM",
        kernel_defconfig="x86_64_defconfig",
        kernel_filename="bzImage",
        image_name="qemu-x86.img",
        boot_config_lines=(),
        boot_cmdline=(
            "console=ttyS0 root=/dev/vda2 rootfstype=ext4 rw rootwait"
        ),
        required_boot_files=(),
        boot_firmware_files=(),
        buildroot_package_lines=(),
        install_boot_files=False,
        kernel_config_options=QEMU_X86_KERNEL_OPTIONS,
        build_kernel_modules=False,
        image_size_mb=512,
        boot_size_mb=64,
        kernel_source="mainline",
        kernel_arch="x86",
        cross_compile="x86_64-linux-gnu-",
        buildroot_arch="x86_64",
        qemu_machine="q35",
        qemu_cpu="qemu64",
        qemu_root_device="/dev/vda2",
    ),
    "qemu-wifi": TargetConfig(
        name="qemu-wifi",
        description="ARM64 QEMU virt + mac80211_hwsim — TinyWifi AP тест в эмуляторе без реального железа",
        kernel_defconfig="defconfig",
        kernel_filename="Image",
        image_name="qemu-wifi.img",
        boot_config_lines=(),
        boot_cmdline=(
            "console=ttyAMA0 root=/dev/vda2 rootfstype=ext4 rw rootwait"
        ),
        required_boot_files=(),
        boot_firmware_files=(),
        buildroot_package_lines=(
            "BR2_PACKAGE_IW=y",
            "BR2_PACKAGE_WIRELESS_TOOLS=y",
            # Без RPi firmware — mac80211_hwsim не требует firmware-файлов
        ),
        install_boot_files=False,
        kernel_config_options=QEMU_WIFI_KERNEL_OPTIONS,
        build_kernel_modules=True,   # нужен mac80211_hwsim.ko
        image_size_mb=512,
        boot_size_mb=64,
        kernel_source="mainline",
        qemu_machine="virt",
        qemu_cpu="cortex-a72",
        qemu_root_device="/dev/vda2",
    ),
    "qemu-virt": TargetConfig(
        name="qemu-virt",
        description="Generic ARM64 QEMU virt image for local agent/OVSDB testing",
        kernel_defconfig="defconfig",
        kernel_filename="Image",
        image_name="qemu-virt.img",
        boot_config_lines=(),
        boot_cmdline=(
            "console=ttyAMA0 root=/dev/vda2 rootfstype=ext4 rw rootwait"
        ),
        required_boot_files=(),
        boot_firmware_files=(),
        buildroot_package_lines=(),
        install_boot_files=False,
        kernel_config_options=QEMU_VIRT_KERNEL_OPTIONS,
        build_kernel_modules=False,
        image_size_mb=512,
        boot_size_mb=64,
        kernel_source="mainline",
        qemu_machine="virt",
        qemu_cpu="cortex-a72",
        qemu_root_device="/dev/vda2",
    ),
}


def get_target(name: str) -> TargetConfig:
    try:
        return TARGETS[name]
    except KeyError as exc:
        available = ", ".join(sorted(TARGETS))
        raise ValueError(f"Unknown target '{name}'. Available targets: {available}") from exc
