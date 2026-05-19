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
    parser = argparse.ArgumentParser(description="Build 4stm4 netOS rootfs/kernel/image")
    parser.add_argument(
        "--target",
        choices=sorted(TARGETS),
        default="pi5",
        help="Build target. Use qemu-virt for local generic ARM64 QEMU testing.",
    )
    parser.add_argument(
        "--profile",
        default=None,
        help="Path to profile YAML (overrides defaults; env vars have higher priority).",
    )
    parser.add_argument(
        "--packages-file",
        default=None,
        dest="packages_file",
        help="Path to a text file with extra BR2_PACKAGE_*=y lines.",
    )
    return parser


def _apply_profile(profile_path: str) -> None:
    """Load a YAML profile and set env vars (existing env takes priority)."""
    try:
        import yaml  # type: ignore[import]
    except ImportError:
        sys.exit("PyYAML is required to use --profile. Run: pip install pyyaml")

    from pathlib import Path as _Path
    path = _Path(profile_path)
    if not path.exists():
        sys.exit(f"Profile not found: {profile_path}")

    with path.open() as f:
        data = yaml.safe_load(f)

    # branding
    branding = data.get("branding", {})
    _setenv_if_unset("NETOS_VERSION", branding.get("version", ""))
    _setenv_if_unset("NETOS_HOSTNAME", branding.get("hostname", ""))

    # image
    image = data.get("image", {})
    _setenv_if_unset("NETOS_IMAGE_SIZE_MB", str(image.get("size_mb", "")))
    _setenv_if_unset("NETOS_BOOT_SIZE_MB", str(image.get("boot_mb", "")))

    # network eth0
    eth0 = data.get("network", {}).get("eth0", {})
    if eth0.get("mode") == "static":
        _setenv_if_unset("NETOS_ETH0_ADDRESS", eth0.get("address", ""))
        _setenv_if_unset("NETOS_ETH0_GATEWAY", eth0.get("gateway", ""))
        _setenv_if_unset("NETOS_ETH0_DNS", eth0.get("dns", ""))

    # wifi
    wifi = data.get("network", {}).get("wifi", {})
    if wifi.get("ssid"):
        _setenv_if_unset("NETOS_WIFI_SSID", wifi.get("ssid", ""))
        _setenv_if_unset("NETOS_WIFI_PSK", wifi.get("psk", ""))
        _setenv_if_unset("NETOS_WIFI_COUNTRY", wifi.get("country", "US"))
    _setenv_if_unset(
        "NETOS_WIFI_BOOTSTRAP", "1" if wifi.get("bootstrap", True) else "0"
    )

    # webui
    webui = data.get("webui", {})
    source = webui.get("source", "git")
    if source == "local":
        _setenv_if_unset("NETOS_WEBUI_SOURCE_DIR", webui.get("source_dir", ""))
    elif source == "runtime":
        _setenv_if_unset("NETOS_WEBUI_EMBED", "0")
    _setenv_if_unset("NETOS_WEBUI_GIT_URL", webui.get("git_url", ""))
    _setenv_if_unset("NETOS_WEBUI_GIT_REF", webui.get("git_ref", "main"))
    _setenv_if_unset("NETOS_WEBUI_PORT", str(webui.get("port", 8080)))
    _setenv_if_unset("NETOS_WEBUI_DATA_DIR", webui.get("data_dir", ""))
    _setenv_if_unset("NETOS_WEBUI_DATABASE_URL", webui.get("database_url", ""))
    _setenv_if_unset("NETOS_WEBUI_PIP_MODE", webui.get("pip_mode", "never"))
    _setenv_if_unset("NETOS_WEBUI_ADMIN_USERNAME", webui.get("admin_username", "admin"))
    if webui.get("admin_password"):
        _setenv_if_unset("NETOS_WEBUI_ADMIN_PASSWORD", webui.get("admin_password", ""))
    _setenv_if_unset("NETOS_WEBUI_HEALTH_PATH", webui.get("health_path", "/health"))
    _setenv_if_unset("NETOS_WEBUI_APP_MODULE", webui.get("app_module", "app.main:app"))


def _setenv_if_unset(key: str, value: str) -> None:
    """Set an env var only if it is not already set."""
    if value and key not in os.environ:
        os.environ[key] = value


def _load_extra_packages(packages_file: str) -> list[str]:
    from pathlib import Path as _Path
    path = _Path(packages_file)
    if not path.exists():
        sys.exit(f"Packages file not found: {packages_file}")
    lines = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            lines.append(line)
    return lines


if __name__ == "__main__":
    args = build_parser().parse_args()

    # Apply profile before resolving target so env vars set by profile
    # can affect any env-dependent logic later.
    if args.profile:
        _apply_profile(args.profile)

    # If profile specifies a target, allow --target to override, otherwise
    # read target from profile if not explicitly given via CLI.
    profile_target = None
    if args.profile:
        try:
            import yaml  # type: ignore[import]
            from pathlib import Path as _Path
            _pdata = yaml.safe_load(_Path(args.profile).read_text())
            profile_target = _pdata.get("target")
        except Exception:
            pass

    # Determine final target: CLI flag wins, then profile, then default
    import sys as _sys
    _raw_args = _sys.argv[1:]
    _target_explicit = "--target" in _raw_args
    if not _target_explicit and profile_target:
        try:
            target = get_target(profile_target)
        except ValueError as _e:
            sys.exit(str(_e))
    else:
        target = get_target(args.target)

    extra_packages: list[str] = []
    if args.packages_file:
        extra_packages = _load_extra_packages(args.packages_file)

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

    NetOSBuildrootBuilder(ROOTFS_PATH, TEMP_PATH, target, extra_packages=extra_packages).bootstrap()

    # Настройка контейнера
    setup.setup_directories(ROOTFS_PATH)
    setup.write_base_configs(ROOTFS_PATH, hostname=NETOS_HOSTNAME)
    setup.setup_network(ROOTFS_PATH)
    setup.install_boot_diagnostics(ROOTFS_PATH)
    setup.create_dev_nodes(ROOTFS_PATH)
    linux_kernel.install_kernel()
    setup.install_webui_assets(ROOTFS_PATH)
    setup.install_nervum_assets(ROOTFS_PATH)
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
