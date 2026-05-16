import os
import platform
import stat
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
