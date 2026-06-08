from __future__ import annotations

import sys
from pathlib import Path

from fastapi import APIRouter

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from src.targets import TARGETS

router = APIRouter()


_WIFI_CAPABLE_TARGETS = {"zero2w"}


@router.get("/targets")
def get_targets():
    result: dict = {}
    for name, t in TARGETS.items():
        result[name] = {
            "name": t.name,
            "description": t.description,
            "kernel_defconfig": t.kernel_defconfig,
            "kernel_filename": t.kernel_filename,
            "image_name": t.image_name,
            "image_size_mb": t.image_size_mb,
            "boot_size_mb": t.boot_size_mb,
            "boot_cmdline": t.boot_cmdline,
            "qemu_machine": t.qemu_machine,
            "qemu_cpu": t.qemu_cpu,
            "qemu_root_device": t.qemu_root_device,
            "qemu_supported": t.qemu_supported,
            "install_boot_files": t.install_boot_files,
            "build_kernel_modules": t.build_kernel_modules,
            "kernel_config_options": list(t.kernel_config_options),
            "buildroot_package_lines": list(t.buildroot_package_lines),
            "kernel_source": getattr(t, "kernel_source", "rpi"),
            "wifi_capable": name in _WIFI_CAPABLE_TARGETS,
            "status": "verified" if name == "qemu-virt" else "wip",
        }
    return result
