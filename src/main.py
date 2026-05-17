from core.container_setup import ContainerSetup
from adapters.file_adapter import FileAdapter
from adapters.logging_adapter import LoggingAdapter
from adapters.network_adapter import NetworkAdapter
from adapters.package_installer import install_dependencies
from adapters.linux_kernel import LinuxKernel
from adapters.netos_buildroot import NetOSBuildrootBuilder
from make_image import create_img
from netos_branding import NETOS_HOSTNAME
from targets import TARGETS, get_target
import argparse
import os
from pathlib import Path
import platform
import sys


# Определение абсолютных путей
SCRIPT_DIR = Path(__file__).parent.absolute()
PROJECT_ROOT = SCRIPT_DIR.parent
TEMP_PATH = PROJECT_ROOT / "temp"
ROOTFS_PATH = PROJECT_ROOT / "container"
SCHEMA_PATH = SCRIPT_DIR / "schema" / "system.ovsschema"
NET_AGENT_PATH = SCRIPT_DIR / "agents" / "net_agent.py"
STORAGE_AGENT_PATH = SCRIPT_DIR / "agents" / "storage_agent.py"
VM_AGENT_PATH = SCRIPT_DIR / "agents" / "vm_agent.py"
STAT_AGENT_PATH = SCRIPT_DIR / "agents" / "stat_agent.py"
CLI_PATH = SCRIPT_DIR / "cli.py"


def build_parser():
    parser = argparse.ArgumentParser(description="Build Litainer rootfs/kernel/image")
    parser.add_argument(
        "--target",
        choices=sorted(TARGETS),
        default="pi5",
        help="Build target. Use qemu-virt for local generic ARM64 QEMU testing.",
    )
    return parser


if __name__ == "__main__":
    args = build_parser().parse_args()
    target = get_target(args.target)

    if platform.system() != "Linux":
        sys.exit(
            "Полная сборка rootfs и образа поддерживается только на Linux. "
            "На macOS нужна Linux VM или уже готовый rootfs."
        )
    if os.geteuid() == 0:
        sys.exit(
            "Не запускайте src/main.py через sudo/root: Buildroot не должен "
            "собираться под root. Запустите обычным пользователем; скрипт сам "
            "вызовет sudo для apt и операций с loop/mount."
        )

    # Инициализация адаптеров
    file_adapter = FileAdapter(ROOTFS_PATH)
    logging_adapter = LoggingAdapter()
    network_adapter = NetworkAdapter()
    linux_kernel = LinuxKernel(
        TEMP_PATH,
        target.kernel_defconfig,
        ROOTFS_PATH,
        kernel_filename=target.kernel_filename,
        config_options=target.kernel_config_options,
        boot_firmware_files=target.boot_firmware_files,
        build_modules=target.build_kernel_modules,
    )

    logging_adapter.info(f"Собираем target: {target.name} ({target.description})")
    file_adapter.clear_container()
    ROOTFS_PATH.mkdir(parents=True, exist_ok=True)
    # Инициализация контейнера
    setup = ContainerSetup(file_adapter, logging_adapter, network_adapter)
    install_dependencies()
    linux_kernel.download_kernel()
    linux_kernel.unpack_kernel()
    linux_kernel.configure_kernel()
    linux_kernel.compile_kernel()

    NetOSBuildrootBuilder(ROOTFS_PATH, TEMP_PATH, target).bootstrap()

    # Настройка контейнера
    setup.setup_directories(ROOTFS_PATH)
    setup.write_base_configs(ROOTFS_PATH, hostname=NETOS_HOSTNAME)
    setup.setup_network(ROOTFS_PATH)
    setup.install_boot_diagnostics(ROOTFS_PATH)
    setup.create_dev_nodes(ROOTFS_PATH)
    linux_kernel.install_kernel()
    setup.install_webui_assets(ROOTFS_PATH)
    setup.install_ovsdb_assets(
        ROOTFS_PATH,
        SCHEMA_PATH,
        NET_AGENT_PATH,
        storage_agent=STORAGE_AGENT_PATH,
        vm_agent=VM_AGENT_PATH,
        stat_agent=STAT_AGENT_PATH,
        cli_tool=CLI_PATH,
    )
    try:
        create_img(target)
    except Exception as e:
        logging_adapter.error(f"Не удалось создать образ: {e}")
