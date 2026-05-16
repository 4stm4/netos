import argparse
import os
import subprocess
from pathlib import Path
from typing import Union

from targets import TARGETS, TargetConfig, get_target

MIN_ROOTFS_SIZE_MB = 128

PROJECT_ROOT = Path(__file__).parent.parent
CONTAINER_PATH = PROJECT_ROOT / "container"
BOOT_SRC_PATH = CONTAINER_PATH / "boot"
TEMP_PATH = PROJECT_ROOT / "temp"

BOOT_MNT = TEMP_PATH / "mnt_boot"
ROOTFS_MNT = TEMP_PATH / "mnt_rootfs"

CONFIG_TXT = TEMP_PATH / "config.txt"
CMDLINE_TXT = TEMP_PATH / "cmdline.txt"


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer number of megabytes") from exc
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return value


def _image_layout(target: TargetConfig) -> tuple[int, int]:
    image_size_mb = _env_int("NETOS_IMAGE_SIZE_MB", target.image_size_mb)
    boot_size_mb = _env_int("NETOS_BOOT_SIZE_MB", target.boot_size_mb)
    if image_size_mb <= boot_size_mb + MIN_ROOTFS_SIZE_MB:
        raise ValueError(
            "NETOS_IMAGE_SIZE_MB must leave at least "
            f"{MIN_ROOTFS_SIZE_MB}MB for rootfs after boot partition"
        )
    return image_size_mb, boot_size_mb

def _command(cmd, use_sudo=False):
    resolved = [str(arg) for arg in cmd]
    if use_sudo and os.geteuid() != 0:
        return ["sudo", *resolved]
    return resolved


def run(cmd, input_data=None, use_sudo=False):
    resolved = _command(cmd, use_sudo)
    print(f"$ {' '.join(resolved)}")
    subprocess.run(resolved, check=True, input=input_data, text=isinstance(input_data, str))


def check_output(cmd, use_sudo=False):
    resolved = _command(cmd, use_sudo)
    return subprocess.check_output(resolved, text=True)


def _resolve_target(target: Union[str, TargetConfig]) -> TargetConfig:
    if isinstance(target, TargetConfig):
        return target
    return get_target(target)


def create_img(target: Union[str, TargetConfig] = "pi5"):
    target = _resolve_target(target)
    image_size_mb, boot_size_mb = _image_layout(target)
    img_path = PROJECT_ROOT / target.image_name
    boot_loop = None
    root_loop = None
    mounted = []

    TEMP_PATH.mkdir(parents=True, exist_ok=True)
    print(
        f"Создаём пустой образ {img_path} размером {image_size_mb}MB "
        f"для target={target.name}..."
    )
    if img_path.exists():
        img_path.unlink()
    run(["truncate", "-s", f"{image_size_mb}M", img_path])

    print("Размечаем образ (boot + rootfs)...")
    sfdisk_input = f"""
label: dos
label-id: 0x0
unit: sectors

/dev/sda1 : start=2048, size={boot_size_mb*2048}, type=c
/dev/sda2 : start={boot_size_mb*2048+2048}, type=83
""".strip()
    (TEMP_PATH / "partition.sfdisk").write_text(sfdisk_input)
    # Передаём разметку через stdin, без shell-редиректа
    run(["sfdisk", img_path], input_data=sfdisk_input, use_sudo=True)

    print("Подключаем loop-устройство...")
    # Освобождаем старые привязки этого образа, если они остались
    existing = check_output(["losetup", "-j", str(img_path)], use_sudo=True).strip().splitlines()
    for line in existing:
        dev = line.split(":")[0]
        if dev:
            subprocess.run(_command(["losetup", "-d", dev], use_sudo=True), check=False)
    sector_size = 512
    boot_start = 2048
    boot_size_sectors = boot_size_mb * 2048
    root_start = boot_start + boot_size_sectors
    try:
        boot_loop = check_output(
            [
                "losetup",
                "--find",
                "--show",
                "--offset",
                str(boot_start * sector_size),
                "--sizelimit",
                str(boot_size_sectors * sector_size),
                str(img_path),
            ],
            use_sudo=True,
        ).strip()
        root_loop = check_output(
            [
                "losetup",
                "--find",
                "--show",
                "--offset",
                str(root_start * sector_size),
                str(img_path),
            ],
            use_sudo=True,
        ).strip()
        print(f"Используем loop-устройства: boot={boot_loop}, root={root_loop}")

        print("Создаём файловые системы...")
        run(["mkfs.vfat", boot_loop], use_sudo=True)
        run(["mkfs.ext4", root_loop], use_sudo=True)

        BOOT_MNT.mkdir(parents=True, exist_ok=True)
        ROOTFS_MNT.mkdir(parents=True, exist_ok=True)
        run(["mount", boot_loop, BOOT_MNT], use_sudo=True)
        mounted.append(BOOT_MNT)
        run(["mount", root_loop, ROOTFS_MNT], use_sudo=True)
        mounted.append(ROOTFS_MNT)

        print("Копируем rootfs...")
        run(["cp", "-a", str(CONTAINER_PATH) + "/.", str(ROOTFS_MNT)], use_sudo=True)

        print("Копируем boot-файлы...")
        if target.install_boot_files:
            CONFIG_TXT.write_text(f"kernel={target.kernel_filename}\narm_64bit=1\nenable_uart=1\n")
            print(f"Создан {CONFIG_TXT}")
            CMDLINE_TXT.write_text(target.boot_cmdline + "\n")
            print(f"Создан {CMDLINE_TXT}")
        if target.install_boot_files and BOOT_SRC_PATH.exists():
            run(["cp", "-rL", str(BOOT_SRC_PATH) + "/.", str(BOOT_MNT)], use_sudo=True)
        if target.install_boot_files and CONFIG_TXT.exists():
            run(["cp", str(CONFIG_TXT), str(BOOT_MNT / "config.txt")], use_sudo=True)
        if target.install_boot_files and CMDLINE_TXT.exists():
            run(["cp", str(CMDLINE_TXT), str(BOOT_MNT / "cmdline.txt")], use_sudo=True)
    finally:
        print("Размонтируем...")
        for mountpoint in reversed(mounted):
            subprocess.run(_command(["umount", str(mountpoint)], use_sudo=True), check=False)
        for loopdev in (boot_loop, root_loop):
            if loopdev:
                subprocess.run(_command(["losetup", "-d", loopdev], use_sudo=True), check=False)

    print(f"Готово! Образ: {img_path}")


def build_parser():
    parser = argparse.ArgumentParser(description="Create Litainer disk image from container/")
    parser.add_argument("--target", choices=sorted(TARGETS), default="pi5")
    return parser

if __name__ == "__main__":
    args = build_parser().parse_args()
    create_img(args.target)
