import subprocess
import sys
from pathlib import Path
import time
import os
import plistlib

IMG_SIZE_MB = int(os.environ.get("NETOS_IMAGE_SIZE_MB", "1024"))
IMG_SIZE = f"{IMG_SIZE_MB}m"
IMG_NAME = "raspi.img"
BOOT_SIZE_MB = int(os.environ.get("NETOS_BOOT_SIZE_MB", "256"))
PROJECT_ROOT = Path(__file__).parent.parent
CONTAINER_PATH = PROJECT_ROOT / "container"
TEMP_PATH = PROJECT_ROOT / "temp"
IMG_PATH = PROJECT_ROOT / IMG_NAME

KERNEL_IMAGE = TEMP_PATH / "rpi_linux" / "arch/arm64/boot/Image"
DTB_DIR = TEMP_PATH / "rpi_linux" / "arch/arm64/boot/dts"
CONFIG_TXT = TEMP_PATH / "config.txt"
CMDLINE_TXT = TEMP_PATH / "cmdline.txt"


def run(cmd, **kwargs):
    print(f"$ {' '.join(str(x) for x in cmd)}")
    res = subprocess.run(cmd, **kwargs)
    if res.returncode != 0:
        print(f"[!] Ошибка: {cmd}")
        sys.exit(1)
    return res

def detach_if_attached(img_path):
    info = subprocess.check_output(["hdiutil", "info"]).decode()
    device = None
    for block in info.split("================================================"):
        if img_path in block:
            for line in block.splitlines():
                if line.strip().startswith("/dev/disk"):
                    device = line.strip().split()[0]
                    break
    if device:
        print(f"[i] Образ уже подключён как {device}, отключаю...")
        subprocess.run(["hdiutil", "detach", "-force", device])

def get_mountpoint(dev):
    info = subprocess.check_output(["diskutil", "info", "-plist", dev])
    plist = plistlib.loads(info)
    for key in ("MountPoint", b"MountPoint"):
        if key in plist:
            return plist[key].decode() if isinstance(plist[key], bytes) else plist[key]
    raise RuntimeError(f"Не удалось найти точку монтирования для {dev}")

def create_img():
    if not CONTAINER_PATH.exists() or not any(CONTAINER_PATH.iterdir()):
        print(f"[!] Папка {CONTAINER_PATH} не найдена или пуста. Сначала соберите rootfs через main.py!")
        sys.exit(1)
    print(f"Создаём пустой образ {IMG_PATH} размером {IMG_SIZE}...")
    run(["dd", "if=/dev/zero", f"of={IMG_PATH}", "bs=1m", f"count={IMG_SIZE_MB}"])
    detach_if_attached(str(IMG_PATH))

    print("Подключаем образ...")
    attach = subprocess.run(["hdiutil", "attach", "-nomount", "-readwrite", str(IMG_PATH)], capture_output=True, text=True)
    if attach.returncode != 0:
        print(attach.stdout)
        print(attach.stderr)
        sys.exit(1)
    device = None
    for line in attach.stdout.splitlines():
        if "/dev/disk" in line:
            device = line.strip()
            break
    if not device:
        print("[!] Не удалось получить device для образа!")
        sys.exit(1)
    print(f"Device: {device}")

    print("Размечаем через fdisk...")
    # fdisk expects commands from stdin
    # Создаём MBR: 1-й раздел FAT32 (boot), 2-й раздел Linux (rootfs)
    fdisk_script = f"""
edit 1
edit 2
edit 3
edit 4
reinit
partition 1
H
{BOOT_SIZE_MB}M
partition 2
L
*
write
quit
"""
    # Альтернативно: используйте diskutil partitionDisk для автоматизации
    # diskutil partitionDisk <device> MBR FAT32 BOOT 256M FAT32 ROOT R
    run(["diskutil", "partitionDisk", device, "MBR", "FAT32", "BOOT", f"{BOOT_SIZE_MB}M", "FAT32", "ROOT", "R"])

    # Получаем имена разделов
    time.sleep(2)
    diskutil_list = subprocess.check_output(["diskutil", "list", device]).decode()
    boot_part = None
    rootfs_part = None
    for line in diskutil_list.splitlines():
        if "BOOT" in line:
            boot_part = "/dev/" + line.strip().split()[-1]
        if "ROOT" in line:
            rootfs_part = "/dev/" + line.strip().split()[-1]
    if not boot_part or not rootfs_part:
        print("[!] Не удалось найти разделы BOOT и ROOT!")
        sys.exit(1)
    print(f"BOOT: {boot_part}, ROOT: {rootfs_part}")

    print("Монтируем разделы...")
    run(["diskutil", "mount", boot_part])
    run(["diskutil", "mount", rootfs_part])
    boot_mnt = get_mountpoint(boot_part)
    rootfs_mnt = get_mountpoint(rootfs_part)

    print("Копируем rootfs...")
    run(["cp", "-a", str(CONTAINER_PATH) + "/.", boot_mnt])

    print("Копируем boot-файлы...")
    if not CONFIG_TXT.exists():
        CONFIG_TXT.write_text("kernel=kernel8.img\nenable_uart=1\n")
        print(f"Создан {CONFIG_TXT}")
    if not CMDLINE_TXT.exists():
        CMDLINE_TXT.write_text("console=serial0,115200 console=tty1 root=/dev/diskXs2 rootfstype=ext2 fsck.repair=yes rootwait\n")
        print(f"Создан {CMDLINE_TXT}")
    if KERNEL_IMAGE.exists():
        run(["cp", str(KERNEL_IMAGE), str(boot_mnt) + "/kernel8.img"])
    if CONFIG_TXT.exists():
        run(["cp", str(CONFIG_TXT), str(boot_mnt) + "/config.txt"])
    if CMDLINE_TXT.exists():
        run(["cp", str(CMDLINE_TXT), str(boot_mnt) + "/cmdline.txt"])
    if DTB_DIR.exists():
        run(["cp", "-a", str(DTB_DIR), str(boot_mnt)])

    print("Размонтируем...")
    run(["diskutil", "unmount", boot_part])
    run(["diskutil", "unmount", rootfs_part])
    run(["hdiutil", "detach", device])
    print(f"Готово! Образ: {IMG_PATH}")

if __name__ == "__main__":
    create_img()
