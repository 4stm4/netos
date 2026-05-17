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


QEMU_VIRT_KERNEL_OPTIONS = COMMON_KERNEL_OPTIONS + (
    "CONFIG_PCI=y",
    "CONFIG_VIRTIO=y",
    "CONFIG_VIRTIO_PCI=y",
    "CONFIG_VIRTIO_BLK=y",
    "CONFIG_VIRTIO_NET=y",
    "CONFIG_SERIAL_AMBA_PL011=y",
    "CONFIG_SERIAL_AMBA_PL011_CONSOLE=y",
    "CONFIG_RTC_DRV_PL031=y",
)


ZERO2W_KERNEL_OPTIONS = COMMON_KERNEL_OPTIONS + (
    "CONFIG_KVM=n",
    "CONFIG_VFIO=n",
    "CONFIG_VFIO_PCI=n",
    "CONFIG_RFKILL=y",
    "CONFIG_WIRELESS=y",
    "CONFIG_CFG80211=y",
    "CONFIG_MAC80211=y",
    "CONFIG_BRCMUTIL=y",
    "CONFIG_BRCMFMAC=y",
    "CONFIG_BRCMFMAC_SDIO=y",
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
        build_kernel_modules=False,
        image_size_mb=1024,
        boot_size_mb=256,
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
        build_kernel_modules=True,
        image_size_mb=512,
        boot_size_mb=64,
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
