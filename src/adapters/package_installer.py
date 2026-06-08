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
        "xz-utils",
        # bzip2 and zstd omitted: Ubuntu Noble security patches break exact-version
        # deps for these packages; they are already present on any modern Ubuntu
        # system and Buildroot supplies its own copies anyway.
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
                # libelf-dev pulls in zlib1g-dev which conflicts on Ubuntu Noble
                # security patches; Buildroot cross-compiler doesn't need it on host
                "bc",
                "bison",
                "flex",
                "kmod",
                *cross_pkgs,
            ]
        )

    try:
        subprocess.run(prefix + ["apt-get", "update"], check=True)
        subprocess.run(
            prefix + ["apt-get", "install", "-y", "--allow-change-held-packages"]
            + dependencies,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        logging.warning("apt-get install завершился с ошибкой: %s", e)
        # On Ubuntu Noble, security patches can create exact-version conflicts
        # (libbz2, libzstd, zlib1g). Check that the essential tools are present
        # before aborting — the server may already have everything needed.
        missing = _check_essential_tools(kernel_arch)
        if missing:
            logging.error(
                "Ошибка установки зависимостей, отсутствуют критичные инструменты: %s",
                ", ".join(missing),
            )
            sys.exit(1)
        logging.info(
            "apt-get install завершился с предупреждениями, но все критичные "
            "инструменты присутствуют — продолжаем сборку."
        )


def _check_essential_tools(kernel_arch: str) -> list[str]:
    """Return list of essential build tools that are missing from PATH / dpkg."""
    import shutil

    required = ["gcc", "make", "git", "curl", "cpio", "python3"]
    cross_prefix = {
        "arm64":  "aarch64-linux-gnu-gcc",
        "x86":    "x86_64-linux-gnu-gcc",
        "x86_64": "x86_64-linux-gnu-gcc",
    }.get(kernel_arch, "aarch64-linux-gnu-gcc")
    required.append(cross_prefix)

    return [t for t in required if not shutil.which(t)]
