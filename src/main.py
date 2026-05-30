from core.container_setup import ContainerSetup
from adapters.file_adapter import FileAdapter
from adapters.logging_adapter import LoggingAdapter
from adapters.network_adapter import NetworkAdapter
from adapters.package_installer import install_dependencies
from adapters.linux_kernel import LinuxKernel
from adapters.netos_buildroot import NetOSBuildrootBuilder, BUILDROOT_VERSION, BUILDROOT_URL, BUILDROOT_SHA256, OPENVSWITCH_VERSION
from adapters.tinywifi_setup import TinyWifiSetup
from make_image import create_img
from netos_branding import NETOS_HOSTNAME
from targets import TARGETS, get_target
from netos_build import ResolvedBuildPlan, LockFile
import argparse
import os
from pathlib import Path
import platform
import subprocess
import sys


# Определение абсолютных путей
SCRIPT_DIR = Path(__file__).parent.absolute()
PROJECT_ROOT = SCRIPT_DIR.parent
TEMP_PATH = Path(os.environ.get("NETOS_TEMP_DIR", "") or PROJECT_ROOT / "temp")
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
    parser.add_argument(
        "--groups",
        default=None,
        dest="groups",
        help=(
            "Comma-separated extra catalog group names to include "
            "(e.g. --groups wireless,monitoring). "
            "See src/packages/catalog.yaml for available groups."
        ),
    )
    return parser


def _is_tinywifi() -> bool:
    return os.environ.get("NETOS_APPLIANCE", "").lower() == "tinywifi"


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

    # appliance flavor
    appliance = data.get("appliance", {})
    _setenv_if_unset("NETOS_APPLIANCE", appliance.get("type", ""))

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

    extra_groups: list[str] = []
    if args.groups:
        extra_groups = [g.strip() for g in args.groups.split(",") if g.strip()]

    # Build plan — central model for this build
    cache_policy = os.environ.get("NETOS_CACHE_POLICY", "use")
    plan = ResolvedBuildPlan.from_target(target, extra_packages=extra_packages, cache_policy=cache_policy)

    # Lock file — load if present; consulted by ArtifactManager in later milestones
    lock = LockFile(PROJECT_ROOT / "netos.lock.json")
    lock.load()

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
        kernel_source=target.kernel_source,
        kernel_arch=target.kernel_arch,
        cross_compile=target.cross_compile,
    )

    logging_adapter.info(
        "Собираем target: %s (%s) | arch=%s | cache_policy=%s",
        plan.target, target.description, plan.arch, plan.cache_policy,
    )
    file_adapter.clear_container()
    ROOTFS_PATH.mkdir(parents=True, exist_ok=True)
    # Инициализация контейнера
    setup = ContainerSetup(file_adapter, logging_adapter, network_adapter)
    install_dependencies(kernel_arch=target.kernel_arch)
    linux_kernel.download_kernel()
    linux_kernel.unpack_kernel()
    linux_kernel.configure_kernel()
    linux_kernel.compile_kernel()

    _cache_dir = os.environ.get("NETOS_CACHE_DIR", "") or None

    # Для TinyWifi используем только группу tinywifi вместо DEFAULT_GROUPS
    _groups_override = ["tinywifi"] if _is_tinywifi() else None

    try:
        NetOSBuildrootBuilder(
            ROOTFS_PATH, TEMP_PATH, target,
            extra_packages=extra_packages,
            cache_policy=plan.cache_policy,
            extra_groups=extra_groups,
            cache_dir=Path(_cache_dir) if _cache_dir else None,
            groups_override=_groups_override,
        ).bootstrap()
    except RuntimeError as exc:
        logging_adapter.error("=== СБОРКА УПАЛА ===\n%s", exc)
        sys.exit(1)
    except subprocess.CalledProcessError as exc:
        logging_adapter.error("=== СБОРКА УПАЛА === команда завершилась с кодом %d:\n  %s",
                              exc.returncode, " ".join(str(a) for a in exc.cmd))
        sys.exit(1)

    # Общая настройка rootfs
    setup.setup_directories(ROOTFS_PATH)
    setup.write_base_configs(ROOTFS_PATH, hostname=NETOS_HOSTNAME)
    setup.create_dev_nodes(ROOTFS_PATH)
    linux_kernel.install_kernel()

    if _is_tinywifi():
        # TinyWifi AP appliance — минимальный образ без OVS/Testum/nervum
        logging_adapter.info("Appliance: TinyWifi — устанавливаем AP конфигурацию")
        TinyWifiSetup().install(ROOTFS_PATH)
    else:
        # Стандартный netOS — полный стек OVS + Testum + nervum
        setup.setup_network(ROOTFS_PATH)
        setup.install_boot_diagnostics(ROOTFS_PATH)
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
    _img_output_dir  = os.environ.get("NETOS_IMAGE_OUTPUT_DIR", "") or None
    _img_filename    = os.environ.get("NETOS_IMAGE_FILENAME", "") or None
    _base = Path(_img_output_dir) if _img_output_dir else PROJECT_ROOT
    if not _img_filename:
        from datetime import datetime
        _appliance = os.environ.get("NETOS_APPLIANCE", "").lower() or "netos"
        _img_filename = f"{_appliance}-{target.name}-{datetime.now().strftime('%d%m%y-%H%M')}.img"
    _img_path = _base / _img_filename
    _produce_qcow2 = (plan.image_format == "qcow2")
    try:
        create_img(target, image_path=_img_path, qcow2=_produce_qcow2)
    except Exception as e:
        logging_adapter.error(f"Не удалось создать образ: {e}")
        sys.exit(1)

    # Update lock file with the artifact versions actually used in this build
    lock.record("buildroot",   version=BUILDROOT_VERSION,   url=BUILDROOT_URL,   sha256=BUILDROOT_SHA256)
    lock.record("openvswitch", version=OPENVSWITCH_VERSION, url=f"https://www.openvswitch.org/releases/openvswitch-{OPENVSWITCH_VERSION}.tar.gz", sha256="")
    lock.save()
    logging_adapter.info("Build complete. Lock file: %s", PROJECT_ROOT / "netos.lock.json")
