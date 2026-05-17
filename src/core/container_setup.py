import os
import platform
import re
import stat
import sys
from pathlib import Path
from typing import Optional
from core.interfaces import FileSystemPort, LoggerPort, NetworkConfiguratorPort
from netos_branding import NETOS_ID, NETOS_NAME, NETOS_VERSION
import shutil
import subprocess

class ContainerSetup:

    def __init__(self, fs: FileSystemPort, logger: LoggerPort, network_configurator: NetworkConfiguratorPort):
        self.fs = fs
        self.logger = logger
        self.network_configurator = network_configurator

    def setup_directories(self, rootfs_path: Path):
        directories = [
            "bin", "boot", "dev", "etc", "home",
            "lib", "media", "mnt", "opt", "proc",
            "root", "run", "sbin", "srv", "sys",
            "tmp", "usr", "var"
        ]
        for directory in directories:
            dir_path = rootfs_path / directory
            self.fs.create_directory(dir_path)
            self.logger.info(f"Создана директория: {dir_path}")

    def setup_network(self, rootfs_path: Path):
        self.network_configurator.setup_network(rootfs_path)

    def _copy_to_rootfs(self, source: Path, rootfs_path: Path, dest: Optional[Path] = None):
        """Копирует файл в rootfs, сохраняя исходную структуру каталогов."""
        if dest is not None:
            rel_path = dest
        else:
            try:
                rel_path = source.relative_to("/")
            except ValueError:
                rel_path = source

        destination = rootfs_path / rel_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        self.logger.info(f"Скопирован файл: {source} -> {destination}")

    def _ldd_dependencies(self, path: Path) -> set[Path]:
        """Возвращает список зависимостей, найденных через ldd."""
        deps = set()
        try:
            result = subprocess.run(["ldd", str(path)], capture_output=True, text=True, check=True)
        except subprocess.CalledProcessError as e:
            self.logger.error(f"ldd вернул ошибку для {path}: {e}")
            return deps

        for line in result.stdout.splitlines():
            line = line.strip()
            # Форматы строк ldd: "libc.so.6 => /lib/... (0x..)" или "/lib/... (0x..)"
            if "=>" in line:
                candidate = line.split("=>", 1)[1].strip().split()[0]
            else:
                candidate = line.split()[0] if line.startswith("/") else None

            if candidate:
                candidate_path = Path(candidate)
                if candidate_path.exists():
                    deps.add(candidate_path)
                else:
                    self.logger.error(f"Зависимость {candidate} не найдена для {path}")
        return deps

    def _collect_recursive_dependencies(self, initial: Path) -> set[Path]:
        """Ищет зависимости бинарника и их зависимости рекурсивно через ldd."""
        to_process = [initial]
        seen = set()
        all_deps = set()

        while to_process:
            current = to_process.pop()
            if current in seen:
                continue
            seen.add(current)
            deps = self._ldd_dependencies(current)
            for dep in deps:
                if dep not in seen:
                    to_process.append(dep)
                all_deps.add(dep)

        return all_deps

    def write_base_configs(self, rootfs_path: Path, hostname: str = "litainer"):
        """Создаёт базовые системные конфиги в rootfs."""
        fstab = """proc /proc proc defaults 0 0
sysfs /sys sysfs defaults 0 0
devpts /dev/pts devpts gid=5,mode=620 0 0
tmpfs /run tmpfs defaults 0 0
tmpfs /tmp tmpfs defaults 0 0
"""
        self.fs.write_text(Path("etc/fstab"), fstab)
        self.fs.write_text(Path("etc/hostname"), hostname + "\n")
        os_release = f"""NAME="{NETOS_NAME}"
PRETTY_NAME="{NETOS_NAME} {NETOS_VERSION}"
ID={NETOS_ID}
VERSION="{NETOS_VERSION}"
VERSION_ID="{NETOS_VERSION}"
ANSI_COLOR="1;36"
"""
        etc_os_release = rootfs_path / "etc" / "os-release"
        usr_lib = rootfs_path / "usr" / "lib"
        usr_os_release = usr_lib / "os-release"
        usr_lib.mkdir(parents=True, exist_ok=True)
        for path in (etc_os_release, usr_os_release):
            if path.exists() or path.is_symlink():
                path.unlink()
        usr_os_release.write_text(os_release)
        etc_os_release.symlink_to(Path("../usr/lib/os-release"))
        self.fs.write_text(Path("etc/issue"), f"{NETOS_NAME} {NETOS_VERSION} \\n \\l\n\n")
        if not (rootfs_path / "etc" / "passwd").exists():
            self.fs.write_text(Path("etc/passwd"), "root:x:0:0:root:/root:/bin/bash\n")
        if not (rootfs_path / "etc" / "group").exists():
            self.fs.write_text(Path("etc/group"), "root:x:0:\n")
        self.logger.info("Обновлены базовые конфиги rootfs")

    def install_boot_diagnostics(self, rootfs_path: Path):
        """Installs first-boot diagnostics that are copied to the FAT boot partition."""
        sbin_dir = rootfs_path / "usr" / "local" / "sbin"
        sbin_dir.mkdir(parents=True, exist_ok=True)
        diag_path = sbin_dir / "netos-boot-diagnostics"
        diag_path.write_text("""#!/bin/sh

STAGE="${1:-manual}"
BOOT_MNT="${NETOS_BOOT_MNT:-/boot}"
BOOT_DEV="${NETOS_BOOT_DEV:-/dev/mmcblk0p1}"
TMP_LOG="/tmp/netos-${STAGE}.log"

write_section() {
    echo
    echo "## $1"
}

collect_log() {
    {
        echo "4stm4 NetOS boot diagnostics"
        echo "stage=$STAGE"
        echo "time=$(date 2>/dev/null || true)"
        write_section "os-release"
        cat /etc/os-release 2>&1 || true
        write_section "cmdline"
        cat /proc/cmdline 2>&1 || true
        write_section "uname"
        uname -a 2>&1 || true
        write_section "mounts"
        mount 2>&1 || true
        write_section "partitions"
        cat /proc/partitions 2>&1 || true
        write_section "block devices"
        ls -l /dev/mmc* /dev/sd* /dev/disk/by-* 2>&1 || true
        write_section "network"
        ip addr 2>&1 || ifconfig -a 2>&1 || true
        ip route 2>&1 || route -n 2>&1 || true
        write_section "processes"
        ps 2>&1 || true
        write_section "dmesg"
        dmesg 2>&1 || true
    } > "$TMP_LOG"
}

mount_boot() {
    mkdir -p "$BOOT_MNT"
    if mountpoint -q "$BOOT_MNT"; then
        return 0
    fi
    mount -t vfat -o rw,umask=022 "$BOOT_DEV" "$BOOT_MNT" 2>/dev/null && return 0
    mount "$BOOT_DEV" "$BOOT_MNT" 2>/dev/null && return 0
    return 1
}

collect_log
if mount_boot; then
    cp "$TMP_LOG" "$BOOT_MNT/netos-${STAGE}.log" 2>/dev/null || true
    sync
fi
exit 0
""")
        diag_path.chmod(0o755)

        init_dir = rootfs_path / "etc" / "init.d"
        init_dir.mkdir(parents=True, exist_ok=True)
        for name, stage in (("S02netos-bootdiag", "early"), ("S95netos-bootdiag", "late")):
            init_path = init_dir / name
            init_path.write_text(f"#!/bin/sh\n/usr/local/sbin/netos-boot-diagnostics {stage}\n")
            init_path.chmod(0o755)
        self.logger.info("Установлены boot diagnostics для записи логов на FAT-раздел")

    def create_dev_nodes(self, rootfs_path: Path):
        """Создаёт статические устройства /dev/null, /dev/console, /dev/tty, если их нет."""
        dev_dir = rootfs_path / "dev"
        dev_dir.mkdir(parents=True, exist_ok=True)
        nodes = [
            (dev_dir / "null", stat.S_IFCHR | 0o666, os.makedev(1, 3)),
            (dev_dir / "zero", stat.S_IFCHR | 0o666, os.makedev(1, 5)),
            (dev_dir / "console", stat.S_IFCHR | 0o600, os.makedev(5, 1)),
            (dev_dir / "tty", stat.S_IFCHR | 0o666, os.makedev(5, 0)),
        ]
        for path, mode, dev in nodes:
            if path.exists():
                continue
            try:
                os.mknod(path, mode, dev)
                self.logger.info(f"Создан узел устройства: {path}")
            except PermissionError:
                try:
                    subprocess.run(
                        [
                            "sudo",
                            "mknod",
                            "-m",
                            oct(mode & 0o777)[2:],
                            str(path),
                            "c",
                            str(os.major(dev)),
                            str(os.minor(dev)),
                        ],
                        check=True,
                    )
                    self.logger.info(f"Создан узел устройства через sudo: {path}")
                except (FileNotFoundError, subprocess.CalledProcessError) as e:
                    self.logger.error(f"Не удалось создать {path} через sudo: {e}")
            except FileExistsError:
                pass
            except OSError as e:
                self.logger.error(f"Не удалось создать {path}: {e}")

    def get_library_paths(self):
        """
        Возвращает пути системных библиотек на основе архитектуры.
        """
        arch = platform.machine()
        if arch == "x86_64":
            return [
                Path("/lib/x86_64-linux-gnu/libc.so.6"),
                Path("/lib/x86_64-linux-gnu/libpthread.so.0"),
                Path("/lib64/ld-linux-x86-64.so.2"),
                Path("/lib/x86_64-linux-gnu/libnss_dns.so.2"),
                Path("/lib/x86_64-linux-gnu/libnss_files.so.2"),
                Path("/lib/x86_64-linux-gnu/libresolv.so.2"),
            ]
        elif arch == "aarch64":  # Архитектура arm64
            return [
                Path("/lib/aarch64-linux-gnu/libc.so.6"),
                Path("/lib/aarch64-linux-gnu/libpthread.so.0"),
                Path("/lib/ld-linux-aarch64.so.1"),
                Path("/lib/aarch64-linux-gnu/libnss_dns.so.2"),
                Path("/lib/aarch64-linux-gnu/libnss_files.so.2"),
                Path("/lib/aarch64-linux-gnu/libresolv.so.2"),
            ]
        else:
            raise ValueError(f"Неизвестная архитектура: {arch}")

    def copy_system_libraries(self, rootfs_path: Path):
        libraries = self.get_library_paths()
        for lib in libraries:
            if not lib.exists():
                self.logger.error(f"Библиотека не найдена: {lib}")
                continue
            self._copy_to_rootfs(lib, rootfs_path)
            deps = self._collect_recursive_dependencies(lib)
            for dep in deps:
                if dep.exists():
                    self._copy_to_rootfs(dep, rootfs_path)
                else:
                    self.logger.error(f"Зависимость {dep} не найдена для {lib}")

    def copy_binaries_and_dependencies(self, rootfs_path: Path, binaries: list[str]):
        for binary in binaries:
            # Найти путь к бинарнику
            result = subprocess.run(["which", binary], capture_output=True, text=True)
            binary_path = result.stdout.strip()
            if not binary_path or not Path(binary_path).exists():
                self.logger.error(f"Бинарник {binary} не найден!")
                continue
            # Копировать бинарник
            binary_path = Path(binary_path)
            self._copy_to_rootfs(binary_path, rootfs_path)
            deps = self._collect_recursive_dependencies(binary_path)
            for dep in deps:
                if dep.exists():
                    self._copy_to_rootfs(dep, rootfs_path)
                else:
                    self.logger.error(f"Зависимость {dep} не найдена!")

    def install_webui_assets(self, rootfs_path: Path):
        """Installs Testum web UI bootstrap config and SysV init integration."""
        enabled = os.environ.get("NETOS_WEBUI_ENABLED", "1")
        port = os.environ.get("NETOS_WEBUI_PORT", "8080")
        data_dir = os.environ.get("NETOS_WEBUI_DATA_DIR", "/opt/testum")
        embed = os.environ.get("NETOS_WEBUI_EMBED", "1")
        install_url = os.environ.get(
            "NETOS_WEBUI_INSTALL_URL",
            "https://raw.githubusercontent.com/4stm4/testum/main/install.sh",
        )
        git_url = os.environ.get("NETOS_WEBUI_GIT_URL", "https://github.com/4stm4/testum.git")
        git_ref = os.environ.get("NETOS_WEBUI_GIT_REF", "main")
        admin_password = os.environ.get("NETOS_WEBUI_ADMIN_PASSWORD", "")
        start_cmd = os.environ.get(
            "NETOS_WEBUI_START_CMD",
            "python3 -m uvicorn app.main:app --host 0.0.0.0 --port ${TESTUM_PORT:-8080}",
        )
        migrate_cmd = os.environ.get("NETOS_WEBUI_MIGRATE_CMD", "python3 -m alembic upgrade head")
        app_module = os.environ.get("NETOS_WEBUI_APP_MODULE", "app.main:app")
        pythonpath = os.environ.get("NETOS_WEBUI_PYTHONPATH", "src")
        health_path = os.environ.get("NETOS_WEBUI_HEALTH_PATH", "/health")
        source_dir = os.environ.get("NETOS_WEBUI_SOURCE_DIR", "")
        app_env = os.environ.get("NETOS_WEBUI_APP_ENV", "production")
        admin_username = os.environ.get("NETOS_WEBUI_ADMIN_USERNAME", "admin")
        database_url = os.environ.get("NETOS_WEBUI_DATABASE_URL", f"sqlite:///{data_dir}/testum.db")
        ssh_host_key_policy = os.environ.get("NETOS_WEBUI_SSH_HOST_KEY_POLICY", "auto_add")
        pip_mode = os.environ.get("NETOS_WEBUI_PIP_MODE", "never")
        vendor_packages = os.environ.get(
            "NETOS_WEBUI_EMBED_VENDOR_PACKAGES",
            "pyjobkit==1.0.0 croniter==6.2.2",
        )

        preloaded = self._embed_webui_source(
            rootfs_path=rootfs_path,
            data_dir=data_dir,
            embed=embed,
            source_dir=source_dir,
            git_url=git_url,
            git_ref=git_ref,
            vendor_packages=vendor_packages,
        )

        runtime_install_url = "" if preloaded else install_url
        runtime_git_url = "" if preloaded else git_url

        def sh_quote(value: str) -> str:
            return "'" + value.replace("'", "'\"'\"'") + "'"

        etc_netos = rootfs_path / "etc" / "netos"
        etc_netos.mkdir(parents=True, exist_ok=True)
        env_path = etc_netos / "webui.env"
        env_path.write_text(
            "\n".join(
                [
                    f"TESTUM_ENABLED={sh_quote(enabled)}",
                    f"TESTUM_PRELOADED={sh_quote('1' if preloaded else '0')}",
                    f"TESTUM_PORT={sh_quote(port)}",
                    f"TESTUM_DATA_DIR={sh_quote(data_dir)}",
                    f"TESTUM_INSTALL_URL={sh_quote(runtime_install_url)}",
                    f"TESTUM_GIT_URL={sh_quote(runtime_git_url)}",
                    f"TESTUM_GIT_REF={sh_quote(git_ref)}",
                    f"TESTUM_APP_ENV={sh_quote(app_env)}",
                    f"TESTUM_ADMIN_USERNAME={sh_quote(admin_username)}",
                    f"TESTUM_ADMIN_PASSWORD={sh_quote(admin_password)}",
                    f"TESTUM_DATABASE_URL={sh_quote(database_url)}",
                    f"TESTUM_SSH_HOST_KEY_POLICY={sh_quote(ssh_host_key_policy)}",
                    f"TESTUM_PIP_MODE={sh_quote(pip_mode)}",
                    f"TESTUM_START_CMD={sh_quote(start_cmd)}",
                    f"TESTUM_MIGRATE_CMD={sh_quote(migrate_cmd)}",
                    f"TESTUM_APP_MODULE={sh_quote(app_module)}",
                    f"TESTUM_PYTHONPATH={sh_quote(pythonpath)}",
                    f"TESTUM_HEALTH_PATH={sh_quote(health_path)}",
                    "",
                ]
            )
        )
        env_path.chmod(0o600)

        sbin_dir = rootfs_path / "usr" / "local" / "sbin"
        sbin_dir.mkdir(parents=True, exist_ok=True)
        installer_path = sbin_dir / "netos-webui-service"
        installer_path.write_text(self._webui_service_script())
        installer_path.chmod(0o755)

        init_dir = rootfs_path / "etc" / "init.d"
        init_dir.mkdir(parents=True, exist_ok=True)
        init_path = init_dir / "S98testum"
        init_path.write_text(self._webui_init_script())
        init_path.chmod(0o755)
        self.logger.info("Установлены bootstrap и init-скрипт Testum Web UI")

    def _embed_webui_source(
        self,
        rootfs_path: Path,
        data_dir: str,
        embed: str,
        source_dir: str,
        git_url: str,
        git_ref: str,
        vendor_packages: str,
    ) -> bool:
        enabled = embed.lower() not in {"0", "false", "no", "off"}
        target_path = rootfs_path / data_dir.lstrip("/")
        source_path = Path(source_dir).expanduser() if source_dir else None

        if source_path:
            if not source_path.exists():
                raise FileNotFoundError(f"NETOS_WEBUI_SOURCE_DIR не найден: {source_path}")
            self._copy_webui_source(source_path, target_path)
            self._vendor_webui_python_packages(target_path, vendor_packages, source_path)
            return True

        if not enabled:
            return False

        if not git_url:
            self.logger.error("NETOS_WEBUI_EMBED включен, но NETOS_WEBUI_GIT_URL пустой")
            return False

        if target_path.exists():
            shutil.rmtree(target_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "clone", "--depth=1", "--branch", git_ref, git_url, str(target_path)],
            check=True,
        )
        self._cleanup_webui_source(target_path)
        self._vendor_webui_python_packages(target_path, vendor_packages)
        self.logger.info(f"Testum Web UI embedded from {git_url}@{git_ref} -> {target_path}")
        return True

    def _copy_webui_source(self, source_path: Path, target_path: Path):
        if target_path.exists():
            shutil.rmtree(target_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(
            source_path,
            target_path,
            ignore=shutil.ignore_patterns(
                ".git",
                ".github",
                "__pycache__",
                ".pytest_cache",
                ".mypy_cache",
                ".ruff_cache",
                ".venv",
                "venv",
                "node_modules",
                ".DS_Store",
                "*.pyc",
                "dev.db",
                "test.db",
            ),
        )
        self._cleanup_webui_source(target_path)
        self.logger.info(f"Web UI source copied: {source_path} -> {target_path}")

    def _cleanup_webui_source(self, target_path: Path):
        removable_paths = (
            ".git",
            ".github",
            ".pytest_cache",
            ".mypy_cache",
            ".ruff_cache",
            ".venv",
            "venv",
            "node_modules",
        )
        for rel_path in removable_paths:
            path = target_path / rel_path
            if path.is_dir():
                shutil.rmtree(path)
            elif path.exists():
                path.unlink()
        for pattern in ("*.pyc", ".DS_Store", "dev.db", "test.db"):
            for path in target_path.rglob(pattern):
                if path.is_file():
                    path.unlink()
        (target_path / ".netos-embedded").write_text("embedded=1\n")

    def _vendor_webui_python_packages(
        self,
        target_path: Path,
        vendor_packages: str,
        source_path: Optional[Path] = None,
    ):
        packages = [package for package in vendor_packages.split() if package]
        if not packages:
            return
        vendor_dir = target_path / ".python"
        if vendor_dir.exists():
            shutil.rmtree(vendor_dir)
        vendor_dir.mkdir(parents=True, exist_ok=True)
        copied_names: set[str] = set()
        if source_path:
            copied_names = self._copy_vendor_packages_from_source_venv(
                source_path, vendor_dir, packages
            )
        remaining = [
            package
            for package in packages
            if self._vendor_package_name(package) not in copied_names
        ]
        if remaining:
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    "--target",
                    str(vendor_dir),
                    "--no-deps",
                    "--no-compile",
                    "--ignore-requires-python",
                    *remaining,
                ],
                check=True,
            )
        bin_dir = vendor_dir / "bin"
        if bin_dir.exists():
            shutil.rmtree(bin_dir)
        self._cleanup_vendor_tree(vendor_dir)
        self.logger.info(f"Vendored Web UI Python packages into {vendor_dir}: {', '.join(packages)}")

    def _copy_vendor_packages_from_source_venv(
        self, source_path: Path, vendor_dir: Path, packages: list[str]
    ) -> set[str]:
        copied: set[str] = set()
        for site_packages in self._source_venv_site_packages(source_path):
            for package_spec in packages:
                package_name = self._vendor_package_name(package_spec)
                if package_name in copied:
                    continue
                if self._copy_vendor_package(site_packages, vendor_dir, package_name):
                    copied.add(package_name)
            if len(copied) == len(packages):
                break
        if copied:
            self.logger.info(
                "Copied Web UI vendor packages from source venv: "
                + ", ".join(sorted(copied))
            )
        return copied

    def _source_venv_site_packages(self, source_path: Path) -> list[Path]:
        site_packages: list[Path] = []
        for venv_name in (".venv", "venv"):
            lib_path = source_path / venv_name / "lib"
            if not lib_path.exists():
                continue
            site_packages.extend(sorted(lib_path.glob("python*/site-packages")))
        return [path for path in site_packages if path.is_dir()]

    def _copy_vendor_package(
        self, site_packages: Path, vendor_dir: Path, package_name: str
    ) -> bool:
        copied_module = False
        for item in site_packages.iterdir():
            item_name = item.name
            item_norm = item_name.lower().replace("-", "_")
            is_module = item_name == package_name or item_name == f"{package_name}.py"
            is_metadata = item_norm.startswith(f"{package_name}_") and (
                item_norm.endswith(".dist_info") or item_norm.endswith(".egg_info")
            )
            if not is_module and not is_metadata:
                continue
            target = vendor_dir / item_name
            if target.exists():
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()
            if item.is_dir():
                shutil.copytree(
                    item,
                    target,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "tests"),
                )
            else:
                shutil.copy2(item, target)
            copied_module = copied_module or is_module
        return copied_module

    def _vendor_package_name(self, package_spec: str) -> str:
        name = re.split(r"[<>=!~\[]", package_spec, maxsplit=1)[0].strip()
        return name.lower().replace("-", "_")

    def _cleanup_vendor_tree(self, vendor_dir: Path):
        for path in vendor_dir.rglob("__pycache__"):
            if path.is_dir():
                shutil.rmtree(path)
        for path in vendor_dir.rglob("*.pyc"):
            if path.is_file():
                path.unlink()

    def _webui_service_script(self) -> str:
        return """#!/bin/sh
set -u

ENV_FILE=/etc/netos/webui.env
LOG_DIR=/var/log/testum
STATE_DIR=/var/lib/testum
RUN_DIR=/run/testum

mkdir -p "$LOG_DIR" "$STATE_DIR" "$RUN_DIR"

log() {
    echo "[$(date '+%Y-%m-%dT%H:%M:%S%z')] $*"
}

if [ -f "$ENV_FILE" ]; then
    . "$ENV_FILE"
fi

TESTUM_ENABLED=${TESTUM_ENABLED:-1}
case "$TESTUM_ENABLED" in
    0|false|False|no|No|off|Off)
        log "Testum Web UI disabled"
        exit 0
        ;;
esac

TESTUM_PORT=${TESTUM_PORT:-8080}
TESTUM_DATA_DIR=${TESTUM_DATA_DIR:-/opt/testum}
TESTUM_PRELOADED=${TESTUM_PRELOADED:-0}
TESTUM_GIT_REF=${TESTUM_GIT_REF:-main}
TESTUM_INSTALL_URL=${TESTUM_INSTALL_URL:-}
TESTUM_GIT_URL=${TESTUM_GIT_URL:-}
TESTUM_APP_ENV=${TESTUM_APP_ENV:-production}
TESTUM_ADMIN_USERNAME=${TESTUM_ADMIN_USERNAME:-admin}
TESTUM_DATABASE_URL=${TESTUM_DATABASE_URL:-sqlite:///$TESTUM_DATA_DIR/testum.db}
TESTUM_SSH_HOST_KEY_POLICY=${TESTUM_SSH_HOST_KEY_POLICY:-auto_add}
TESTUM_PIP_MODE=${TESTUM_PIP_MODE:-never}
TESTUM_START_CMD=${TESTUM_START_CMD:-}
TESTUM_MIGRATE_CMD=${TESTUM_MIGRATE_CMD:-}
TESTUM_APP_MODULE=${TESTUM_APP_MODULE:-}
TESTUM_PYTHONPATH=${TESTUM_PYTHONPATH:-}
RUNTIME_ENV="$STATE_DIR/runtime.env"

apply_testum_pythonpath() {
    if [ -z "$TESTUM_PYTHONPATH" ]; then
        return 0
    fi
    OLD_IFS=$IFS
    IFS=:
    EXTRA=
    for item in $TESTUM_PYTHONPATH; do
        case "$item" in
            /*) path="$item" ;;
            *) path="$TESTUM_DATA_DIR/$item" ;;
        esac
        if [ -z "$EXTRA" ]; then
            EXTRA="$path"
        else
            EXTRA="$EXTRA:$path"
        fi
    done
    IFS=$OLD_IFS
    export PYTHONPATH="$EXTRA${PYTHONPATH:+:$PYTHONPATH}"
}

generate_runtime_env() {
    if [ ! -f "$RUNTIME_ENV" ]; then
        touch "$RUNTIME_ENV"
        chmod 600 "$RUNTIME_ENV"
    fi
    . "$RUNTIME_ENV" 2>/dev/null || true
    if [ -z "${SECRET_KEY:-}" ]; then
        SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')
        echo "SECRET_KEY='$SECRET_KEY'" >> "$RUNTIME_ENV"
    fi
    if [ -z "${FERNET_KEY:-}" ]; then
        FERNET_KEY=$(python3 -c 'import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())')
        echo "FERNET_KEY='$FERNET_KEY'" >> "$RUNTIME_ENV"
    fi
    if [ -z "${TESTUM_ADMIN_PASSWORD:-}" ]; then
        TESTUM_ADMIN_PASSWORD=$(python3 -c 'import secrets; print(secrets.token_urlsafe(18))')
        echo "TESTUM_ADMIN_PASSWORD='$TESTUM_ADMIN_PASSWORD'" >> "$RUNTIME_ENV"
    fi
    if [ -z "${ADMIN_USERNAME:-}" ]; then
        ADMIN_USERNAME="$TESTUM_ADMIN_USERNAME"
        echo "ADMIN_USERNAME='$ADMIN_USERNAME'" >> "$RUNTIME_ENV"
    fi
    if [ -z "${ADMIN_PASSWORD:-}" ]; then
        ADMIN_PASSWORD="$TESTUM_ADMIN_PASSWORD"
        echo "ADMIN_PASSWORD='$ADMIN_PASSWORD'" >> "$RUNTIME_ENV"
    fi
    if [ -z "${DATABASE_URL:-}" ]; then
        DATABASE_URL="$TESTUM_DATABASE_URL"
        echo "DATABASE_URL='$DATABASE_URL'" >> "$RUNTIME_ENV"
    fi
    if [ -z "${APP_ENV:-}" ]; then
        APP_ENV="$TESTUM_APP_ENV"
        echo "APP_ENV='$APP_ENV'" >> "$RUNTIME_ENV"
    fi
    if [ -z "${SSH_HOST_KEY_POLICY:-}" ]; then
        SSH_HOST_KEY_POLICY="$TESTUM_SSH_HOST_KEY_POLICY"
        echo "SSH_HOST_KEY_POLICY='$SSH_HOST_KEY_POLICY'" >> "$RUNTIME_ENV"
    fi
    export SECRET_KEY FERNET_KEY TESTUM_ADMIN_PASSWORD ADMIN_USERNAME ADMIN_PASSWORD DATABASE_URL APP_ENV SSH_HOST_KEY_POLICY
}

run_install_sh() {
    if [ -z "$TESTUM_INSTALL_URL" ]; then
        return 1
    fi
    log "Downloading Testum installer from $TESTUM_INSTALL_URL"
    curl -fsSL "$TESTUM_INSTALL_URL" -o /tmp/testum-install.sh || return 1
    chmod +x /tmp/testum-install.sh
    set -- --bare-metal --port "$TESTUM_PORT" --data-dir "$TESTUM_DATA_DIR"
    if [ -n "${TESTUM_ADMIN_PASSWORD:-}" ]; then
        set -- "$@" --admin-password "$TESTUM_ADMIN_PASSWORD"
    fi
    sh /tmp/testum-install.sh "$@"
}

sync_git_source() {
    if [ -z "$TESTUM_GIT_URL" ]; then
        return 1
    fi
    if [ ! -d "$TESTUM_DATA_DIR/.git" ]; then
        rm -rf "$TESTUM_DATA_DIR"
        git clone --depth=1 --branch "$TESTUM_GIT_REF" "$TESTUM_GIT_URL" "$TESTUM_DATA_DIR"
    else
        git -C "$TESTUM_DATA_DIR" fetch --depth=1 origin "$TESTUM_GIT_REF" || return 1
        git -C "$TESTUM_DATA_DIR" reset --hard "origin/$TESTUM_GIT_REF" || return 1
    fi
}

prepare_python_deps() {
    cd "$TESTUM_DATA_DIR" || return 1
    PYTHON_BIN=python3
    PYTHONPATH_EXTRA=
    if [ -d "$TESTUM_DATA_DIR/.python" ]; then
        PYTHONPATH_EXTRA="$TESTUM_DATA_DIR/.python"
    fi
    case "$TESTUM_PIP_MODE" in
        never|Never|off|Off|0|false|False|no|No)
            log "pip install disabled; using embedded/Buildroot Python packages"
            echo "$PYTHON_BIN" > "$RUN_DIR/python-bin"
            echo "$PYTHONPATH_EXTRA" > "$RUN_DIR/pythonpath-extra"
            return 0
            ;;
    esac
    if [ -f requirements.txt ]; then
        if python3 -m venv "$TESTUM_DATA_DIR/venv" >/dev/null 2>&1; then
            PYTHON_BIN="$TESTUM_DATA_DIR/venv/bin/python"
            "$PYTHON_BIN" -m pip install --no-cache-dir --upgrade pip
            "$PYTHON_BIN" -m pip install --no-cache-dir -r requirements.txt
        elif python3 -m pip --version >/dev/null 2>&1; then
            mkdir -p "$TESTUM_DATA_DIR/.python"
            python3 -m pip install --no-cache-dir --target "$TESTUM_DATA_DIR/.python" -r requirements.txt
            PYTHONPATH_EXTRA="$TESTUM_DATA_DIR/.python"
        else
            log "pip/venv unavailable; using Buildroot-provided Python packages"
        fi
    fi
    echo "$PYTHON_BIN" > "$RUN_DIR/python-bin"
    echo "$PYTHONPATH_EXTRA" > "$RUN_DIR/pythonpath-extra"
}

run_migrations() {
    cd "$TESTUM_DATA_DIR" || return 0
    apply_testum_pythonpath
    PYTHON_BIN=$(cat "$RUN_DIR/python-bin" 2>/dev/null || echo python3)
    PYTHONPATH_EXTRA=$(cat "$RUN_DIR/pythonpath-extra" 2>/dev/null || true)
    if [ -n "$PYTHONPATH_EXTRA" ]; then
        export PYTHONPATH="$PYTHONPATH_EXTRA${PYTHONPATH:+:$PYTHONPATH}"
    fi
    if [ -n "$TESTUM_MIGRATE_CMD" ]; then
        sh -c "$TESTUM_MIGRATE_CMD" || log "migration command failed"
    elif [ -f manage.py ]; then
        "$PYTHON_BIN" manage.py migrate --noinput || log "django migrations failed"
    elif [ -f alembic.ini ]; then
        "$PYTHON_BIN" -m alembic upgrade head || alembic upgrade head || log "alembic migrations failed"
    fi
}

bootstrap_if_needed() {
    generate_runtime_env
    if [ -f "$STATE_DIR/installed" ]; then
        return 0
    fi
    if [ "$TESTUM_PRELOADED" = "1" ] && [ -d "$TESTUM_DATA_DIR" ]; then
        prepare_python_deps || true
        run_migrations || true
        touch "$STATE_DIR/installed"
        return 0
    fi
    if [ -n "$TESTUM_INSTALL_URL" ]; then
        if run_install_sh; then
            touch "$STATE_DIR/installed"
            return 0
        fi
        log "install.sh failed; trying git/preloaded source fallback"
    fi
    if [ -n "$TESTUM_GIT_URL" ]; then
        sync_git_source || return 1
    elif [ ! -d "$TESTUM_DATA_DIR" ]; then
        log "No Testum source configured. Set TESTUM_INSTALL_URL, TESTUM_GIT_URL or preload $TESTUM_DATA_DIR."
        return 1
    fi
    prepare_python_deps || true
    run_migrations || true
    touch "$STATE_DIR/installed"
}

start_webui() {
    cd "$TESTUM_DATA_DIR" || return 1
    . "$RUNTIME_ENV" 2>/dev/null || true
    export SECRET_KEY FERNET_KEY TESTUM_ADMIN_PASSWORD ADMIN_USERNAME ADMIN_PASSWORD DATABASE_URL APP_ENV SSH_HOST_KEY_POLICY TESTUM_PORT
    apply_testum_pythonpath
    PYTHON_BIN=$(cat "$RUN_DIR/python-bin" 2>/dev/null || echo python3)
    PYTHONPATH_EXTRA=$(cat "$RUN_DIR/pythonpath-extra" 2>/dev/null || true)
    if [ -n "$PYTHONPATH_EXTRA" ]; then
        export PYTHONPATH="$PYTHONPATH_EXTRA${PYTHONPATH:+:$PYTHONPATH}"
    fi
    if [ -n "$TESTUM_START_CMD" ]; then
        exec sh -c "$TESTUM_START_CMD"
    fi
    if [ -x ./start.sh ]; then
        exec ./start.sh
    fi
    if [ -f manage.py ]; then
        exec "$PYTHON_BIN" manage.py runserver "0.0.0.0:$TESTUM_PORT"
    fi
    if [ -n "$TESTUM_APP_MODULE" ]; then
        exec "$PYTHON_BIN" -m uvicorn "$TESTUM_APP_MODULE" --host 0.0.0.0 --port "$TESTUM_PORT"
    fi
    if [ -f app/main.py ]; then
        exec "$PYTHON_BIN" -m uvicorn app.main:app --host 0.0.0.0 --port "$TESTUM_PORT"
    fi
    if [ -f main.py ]; then
        exec "$PYTHON_BIN" -m uvicorn main:app --host 0.0.0.0 --port "$TESTUM_PORT"
    fi
    log "No Testum startup command found. Set TESTUM_START_CMD or TESTUM_APP_MODULE."
    return 1
}

bootstrap_if_needed || exit 0
log "Starting Testum Web UI on port $TESTUM_PORT"
start_webui
"""

    def _webui_init_script(self) -> str:
        return """#!/bin/sh

PIDFILE=/run/testum/testum.pid
LOGFILE=/var/log/testum/service.log
SERVICE=/usr/local/sbin/netos-webui-service
ENV_FILE=/etc/netos/webui.env

is_enabled() {
    TESTUM_ENABLED=1
    [ -f "$ENV_FILE" ] && . "$ENV_FILE"
    case "${TESTUM_ENABLED:-1}" in
        0|false|False|no|No|off|Off) return 1 ;;
    esac
    return 0
}

start() {
    is_enabled || return 0
    mkdir -p /run/testum /var/log/testum
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
        echo "Testum Web UI already running"
        return 0
    fi
    "$SERVICE" >> "$LOGFILE" 2>&1 &
    echo $! > "$PIDFILE"
    echo "TESTUM_WEBUI_STARTED"
}

stop() {
    if [ -f "$PIDFILE" ]; then
        kill "$(cat "$PIDFILE")" 2>/dev/null || true
        rm -f "$PIDFILE"
    fi
}

case "${1:-start}" in
    start) start ;;
    stop) stop ;;
    restart) stop; start ;;
    *) echo "Usage: $0 {start|stop|restart}"; exit 1 ;;
esac
"""

    def install_ovsdb_assets(
        self,
        rootfs_path: Path,
        schema_src: Path,
        agent_src: Path,
        storage_agent: Optional[Path] = None,
        vm_agent: Optional[Path] = None,
        stat_agent: Optional[Path] = None,
        cli_tool: Optional[Path] = None,
    ):
        """Копирует схему OVSDB и агентов, создаёт init-скрипт для запуска."""
        if not schema_src.exists():
            self.logger.error(f"Файл схемы не найден: {schema_src}")
            return
        if not agent_src.exists():
            self.logger.error(f"Агент не найден: {agent_src}")
            return
        extra_agents = []
        for name, path in [("storage_agent", storage_agent), ("vm_agent", vm_agent), ("stat_agent", stat_agent)]:
            if path and path.exists():
                extra_agents.append((name, path))
            elif path:
                self.logger.error(f"{name} не найден: {path}")

        etc_ovs = rootfs_path / "etc" / "openvswitch"
        etc_ovs.mkdir(parents=True, exist_ok=True)
        self._copy_to_rootfs(schema_src, rootfs_path, Path("etc/openvswitch/system.ovsschema"))
        self._copy_to_rootfs(agent_src, rootfs_path, Path("usr/local/sbin/net_agent.py"))
        agent_dst = rootfs_path / "usr/local/sbin/net_agent.py"
        agent_dst.chmod(0o755)

        for _, path in extra_agents:
            target = rootfs_path / "usr/local/sbin" / path.name
            self._copy_to_rootfs(path, rootfs_path, Path("usr/local/sbin") / path.name)
            target.chmod(0o755)

        if cli_tool and cli_tool.exists():
            self._copy_to_rootfs(cli_tool, rootfs_path, Path("usr/local/bin/cli.py"))
            (rootfs_path / "usr/local/bin/cli.py").chmod(0o755)

        rcS_content = """#!/bin/sh
set -e

mountpoint -q /proc || mount -t proc proc /proc
mountpoint -q /sys || mount -t sysfs sysfs /sys
mountpoint -q /dev || mount -t devtmpfs devtmpfs /dev 2>/dev/null || true
mkdir -p /dev/pts
mountpoint -q /dev/pts || mount -t devpts devpts /dev/pts 2>/dev/null || true

CGROOT=/sys/fs/cgroup
if [ ! -d "$CGROOT" ]; then
    mkdir -p "$CGROOT"
fi
if ! mountpoint -q "$CGROOT"; then
    mount -t cgroup2 none "$CGROOT" 2>/dev/null || mount -t cgroup -o none,name=systemd cgroup "$CGROOT" 2>/dev/null || true
fi
mkdir -p "$CGROOT/vm.slice"
if [ -e "$CGROOT/vm.slice/cpu.max" ] && [ -w "$CGROOT/vm.slice/cpu.max" ]; then
    echo "100000 50000" > "$CGROOT/vm.slice/cpu.max"
fi
if [ -e "$CGROOT/vm.slice/memory.max" ] && [ -w "$CGROOT/vm.slice/memory.max" ]; then
    echo "1073741824" > "$CGROOT/vm.slice/memory.max"
fi

OVS_RUNDIR=/var/run/openvswitch
OVS_DBDIR=/var/lib/openvswitch
OVS_LOGDIR=/var/log/openvswitch
SYS_SCHEMA=/etc/openvswitch/system.ovsschema
SYS_DB=$OVS_DBDIR/sysdb.db
OVS_SCHEMA=/usr/share/openvswitch/vswitch.ovsschema
OVS_DB=$OVS_DBDIR/conf.db

mkdir -p "$OVS_RUNDIR" "$OVS_DBDIR" "$OVS_LOGDIR"

if ! command -v ovsdb-tool >/dev/null 2>&1; then
    echo "OVSDB_TOOL_MISSING"
    exit 0
fi

if [ ! -f "$SYS_DB" ]; then
    ovsdb-tool create "$SYS_DB" "$SYS_SCHEMA"
fi

DB_ARGS="$SYS_DB"
if [ -f "$OVS_SCHEMA" ]; then
    if [ ! -f "$OVS_DB" ]; then
        ovsdb-tool create "$OVS_DB" "$OVS_SCHEMA"
    fi
    DB_ARGS="$DB_ARGS $OVS_DB"
else
    echo "OVS_SCHEMA_MISSING:$OVS_SCHEMA"
fi

ovsdb-server \
    --remote=punix:$OVS_RUNDIR/db.sock \
    --remote=ptcp:6640:127.0.0.1 \
    --unixctl=$OVS_RUNDIR/ovsdb-server.ctl \
    --pidfile=$OVS_RUNDIR/ovsdb-server.pid \
    --detach --no-chdir \
    --log-file=$OVS_LOGDIR/ovsdb-server.log \
    $DB_ARGS
echo "OVSDB_STARTED"

if [ -f "$OVS_DB" ] && command -v ovs-vswitchd >/dev/null 2>&1; then
    ovs-vswitchd unix:$OVS_RUNDIR/db.sock \
        --pidfile=$OVS_RUNDIR/ovs-vswitchd.pid \
        --detach --no-chdir \
        --log-file=$OVS_LOGDIR/ovs-vswitchd.log
    ovs-vsctl --no-wait init || true
    echo "OVS_VSWITCHD_STARTED"
fi

PYTHON_BIN=""
if [ -x /usr/bin/python3 ]; then
    PYTHON_BIN=/usr/bin/python3
elif [ -x /bin/python3 ]; then
    PYTHON_BIN=/bin/python3
fi

if [ -d /usr/share/openvswitch/python ]; then
    export PYTHONPATH=/usr/share/openvswitch/python${PYTHONPATH:+:$PYTHONPATH}
fi

if [ -n "$PYTHON_BIN" ] && [ -x /usr/local/sbin/net_agent.py ]; then
    "$PYTHON_BIN" /usr/local/sbin/net_agent.py &
    echo "NET_AGENT_STARTED"
fi
if [ -n "$PYTHON_BIN" ] && [ -x /usr/local/sbin/storage_agent.py ]; then
    "$PYTHON_BIN" /usr/local/sbin/storage_agent.py &
    echo "STORAGE_AGENT_STARTED"
fi
if [ -n "$PYTHON_BIN" ] && [ -x /usr/local/sbin/vm_agent.py ]; then
    "$PYTHON_BIN" /usr/local/sbin/vm_agent.py &
    echo "VM_AGENT_STARTED"
fi
if [ -n "$PYTHON_BIN" ] && [ -x /usr/local/sbin/stat_agent.py ]; then
    "$PYTHON_BIN" /usr/local/sbin/stat_agent.py &
    echo "STAT_AGENT_STARTED"
fi

if [ -c /dev/watchdog ]; then
    ( while true; do echo 1 > /dev/watchdog; sleep 10; done ) &
    echo "WATCHDOG_STARTED"
fi

exit 0
"""
        init_path = rootfs_path / "sbin" / "init"
        if init_path.exists():
            service_path = rootfs_path / "etc" / "init.d" / "S99netos"
            service_path.parent.mkdir(parents=True, exist_ok=True)
            service_path.write_text(rcS_content)
            service_path.chmod(0o755)
            self.logger.info("Установлены схема OVSDB, агенты и init-скрипт S99netos")
            return

        rcS_path = rootfs_path / "etc/init.d/rcS"
        rcS_path.parent.mkdir(parents=True, exist_ok=True)
        rcS_path.write_text(rcS_content)
        rcS_path.chmod(0o755)

        init_path.parent.mkdir(parents=True, exist_ok=True)
        init_content = """#!/bin/sh
/etc/init.d/rcS
status=$?
if [ "$status" -ne 0 ]; then
    echo "RCS_FAILED:$status"
else
    echo "INIT_READY"
fi

while true; do
    sleep 3600
done
"""
        init_path.write_text(init_content)
        init_path.chmod(0o755)
        self.logger.info("Установлены схема OVSDB, агенты, rcS и минимальный /sbin/init")

    def detach_image(self, device: str):
        subprocess.run(["hdiutil", "detach", device], check=True)
