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


@dataclass(frozen=True)
class TargetConfig:
    name: str
    description: str
    kernel_defconfig: str
    kernel_filename: str
    image_name: str
    boot_cmdline: str
    install_boot_files: bool
    kernel_config_options: tuple[str, ...]
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
        boot_cmdline=(
            "console=serial0,115200 console=tty1 "
            "root=/dev/mmcblk0p2 rootfstype=ext4 fsck.repair=yes rootwait"
        ),
        install_boot_files=True,
        kernel_config_options=COMMON_KERNEL_OPTIONS,
    ),
    "qemu-virt": TargetConfig(
        name="qemu-virt",
        description="Generic ARM64 QEMU virt image for local agent/OVSDB testing",
        kernel_defconfig="defconfig",
        kernel_filename="Image",
        image_name="qemu-virt.img",
        boot_cmdline=(
            "console=ttyAMA0 root=/dev/vda2 rootfstype=ext4 rw rootwait"
        ),
        install_boot_files=False,
        kernel_config_options=QEMU_VIRT_KERNEL_OPTIONS,
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
