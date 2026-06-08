import logging
import os
import subprocess
import sys


_CROSS_TOOLCHAIN: dict[str, list[str]] = {
    # kernel_arch → apt packages for cross-compilation
    "arm64": [
        "gcc-aarch64-linux-gnu",
        "g++-aarch64-linux-gnu",
        "binutils-aarch64-linux-gnu",
    ],
    "x86": [
        "gcc-x86-64-linux-gnu",
        "g++-x86-64-linux-gnu",
        "binutils-x86-64-linux-gnu",
    ],
    "x86_64": [
        "gcc-x86-64-linux-gnu",
        "g++-x86-64-linux-gnu",
        "binutils-x86-64-linux-gnu",
    ],
}


def install_dependencies(kernel_arch: str = "arm64") -> None:
    """Install host-side build dependencies for kernel, Buildroot and image creation.

    *kernel_arch* selects the cross-compiler toolchain (``"arm64"`` | ``"x86"`` | ``"x86_64"``).
    Defaults to ``"arm64"`` for backward compatibility.
    """
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
        "qemu-utils",
        "qemu-system-x86",
        "qemu-system-aarch64",
    ]
    prebuilt_kernel = os.environ.get("NETOS_PREBUILT_KERNEL_IMAGE") or os.environ.get("LITAINER_PREBUILT_KERNEL_IMAGE")
    if not prebuilt_kernel:
        cross_pkgs = _CROSS_TOOLCHAIN.get(kernel_arch, _CROSS_TOOLCHAIN["arm64"])
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
                *cross_pkgs,
            ]
        )

    try:
        subprocess.run(prefix + ["apt-get", "update"], check=True)
        # --fix-broken resolves held/broken packages before installing
        # (common on Ubuntu when security patches bump library versions
        #  but -dev packages still require the old exact version)
        subprocess.run(prefix + ["apt-get", "install", "-f", "-y"], check=False)
        subprocess.run(
            prefix + ["apt-get", "install", "-y", "--fix-missing"] + dependencies,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        logging.error(f"Ошибка при установке зависимостей сборочной VM: {e}")
        sys.exit(1)
