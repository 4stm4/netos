import logging
import os
import subprocess
import sys


def install_dependencies():
    """Install host-side build dependencies for kernel, Buildroot and image creation."""
    logging.info("Устанавливаем зависимости сборочной VM...")
    prefix = [] if os.geteuid() == 0 else ["sudo"]

    dependencies = [
        # common build tools
        "build-essential",
        "gcc",
        "g++",
        "make",
        "git",
        "wget",
        "curl",
        "ca-certificates",
        "patch",
        "perl",
        "python3",
        "python3-pip",
        "rsync",
        "file",
        "cpio",
        "unzip",
        "tar",
        "gzip",
        "bzip2",
        "xz-utils",
        "zstd",
        # disk image creation and local QEMU checks
        "fdisk",
        "dosfstools",
        "e2fsprogs",
        "util-linux",
        "qemu-system-aarch64",
    ]
    if not os.environ.get("LITAINER_PREBUILT_KERNEL_IMAGE"):
        dependencies.extend(
            [
                # Linux kernel build
                "libncurses-dev",
                "libssl-dev",
                "libelf-dev",
                "bc",
                "bison",
                "flex",
                "kmod",
                "gcc-aarch64-linux-gnu",
                "g++-aarch64-linux-gnu",
                "binutils-aarch64-linux-gnu",
            ]
        )

    try:
        subprocess.run(prefix + ["apt-get", "update"], check=True)
        subprocess.run(prefix + ["apt-get", "install", "-y"] + dependencies, check=True)
    except subprocess.CalledProcessError as e:
        logging.error(f"Ошибка при установке зависимостей сборочной VM: {e}")
        sys.exit(1)
