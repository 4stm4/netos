#!/usr/bin/env python3
import argparse
import http.client
import os
import select
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

from targets import TARGETS, TargetConfig, get_target


PROJECT_ROOT = Path(__file__).parent.parent
DEFAULT_READY_MARKERS = {"OVSDB_STARTED", "OVS_VSWITCHD_STARTED", "NET_AGENT_STARTED", "TESTUM_WEBUI_STARTED"}
DEFAULT_WEBUI_HEALTH_PATH = "/health"


def run_checked(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def get_kernel_image(target: TargetConfig) -> Path:
    """Return path to kernel image based on target's kernel_source and kernel_arch."""
    src_dir = "rpi_linux" if target.kernel_source == "rpi" else "mainline_linux"
    return PROJECT_ROOT / "temp" / src_dir / "arch" / target.kernel_arch / "boot" / target.kernel_filename


def get_qemu_bin(target: TargetConfig) -> str:
    """Return default QEMU binary name for the target architecture."""
    arch_to_bin = {
        "arm64": "qemu-system-aarch64",
        "x86": "qemu-system-x86_64",
    }
    return arch_to_bin.get(target.kernel_arch, "qemu-system-aarch64")


def require_artifacts(target: TargetConfig):
    image_path = PROJECT_ROOT / target.image_name
    kernel_image = get_kernel_image(target)
    missing = []
    if not image_path.exists():
        missing.append(str(image_path))
    if not kernel_image.exists():
        missing.append(str(kernel_image))
    if missing:
        raise FileNotFoundError(
            "Не найдены артефакты для запуска QEMU:\n"
            + "\n".join(f"  - {path}" for path in missing)
            + f"\nСоберите их на Linux: python3 src/main.py --target {target.name}"
        )
    return image_path


def qemu_machine_supported(qemu_bin: str, machine: str) -> bool:
    result = run_checked([qemu_bin, "-machine", "help"])
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Не удалось получить список QEMU machine")
    return any(line.split(maxsplit=1)[0] == machine for line in result.stdout.splitlines() if line.strip())


def build_qemu_cmd(
    target: TargetConfig,
    qemu_bin: str,
    image_path: Path,
    host_port: int,
    webui_host_port: int,
    webui_guest_port: int,
):
    if not target.qemu_supported:
        raise RuntimeError(
            f"Target {target.name} не имеет QEMU-конфигурации. "
            "Pi 5/BCM2712 в текущем QEMU не эмулируется."
        )

    if not qemu_machine_supported(qemu_bin, target.qemu_machine):
        raise RuntimeError(f"QEMU binary {qemu_bin} не поддерживает machine={target.qemu_machine}")

    hostfwds = [
        f"hostfwd=tcp:127.0.0.1:{host_port}-127.0.0.1:6640",
        f"hostfwd=tcp:127.0.0.1:{webui_host_port}-127.0.0.1:{webui_guest_port}",
    ]
    cmd = [
        qemu_bin,
        "-M", target.qemu_machine,
        "-cpu", target.qemu_cpu or "max",
        "-m", "1024",
        "-kernel", str(get_kernel_image(target)),
        "-drive", f"file={image_path},format=raw,if=virtio",
        "-append", target.boot_cmdline,
        "-netdev", "user,id=net0," + ",".join(hostfwds),
        "-device", "virtio-net-pci,netdev=net0",
        "-serial", "stdio",
        "-display", "none",
        "-no-reboot",
    ]
    return cmd


def check_webui_health(host: str, port: int, path: str, timeout: int):
    deadline = time.time() + timeout
    last_error = None
    while time.time() < deadline:
        try:
            conn = http.client.HTTPConnection(host, port, timeout=5)
            conn.request("GET", path)
            response = conn.getresponse()
            body = response.read().decode(errors="replace")
            conn.close()
            if 200 <= response.status < 300:
                print(f"QEMU: Testum Web UI health OK http://{host}:{port}{path}: {body}")
                return
            last_error = RuntimeError(f"HTTP {response.status}: {body}")
        except OSError as exc:
            last_error = exc
        time.sleep(1)
    raise TimeoutError(f"Web UI health-check failed at http://{host}:{port}{path}: {last_error}")


def wait_for_qemu(
    cmd: list[str],
    host_port: int,
    timeout: int,
    markers: set[str],
    skip_tcp_check: bool,
    check_webui: bool,
    webui_host_port: int,
    webui_health_path: str,
):
    print("Запускаем QEMU:")
    print("$ " + " ".join(cmd))
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    seen = set()
    start = time.time()

    try:
        assert proc.stdout is not None
        while True:
            if time.time() - start > timeout:
                raise TimeoutError(f"Таймаут {timeout}s ожидания маркеров: {sorted(markers)}")
            if proc.poll() is not None:
                return proc.returncode

            ready, _, _ = select.select([proc.stdout], [], [], 1)
            if not ready:
                continue

            line = proc.stdout.readline()
            if not line:
                continue
            print(line, end="")
            for marker in markers:
                if marker in line:
                    seen.add(marker)

            if "Kernel panic" in line:
                raise RuntimeError("Kernel panic в гостевой системе")

            if seen == markers:
                if skip_tcp_check:
                    return 0
                with socket.create_connection(("127.0.0.1", host_port), timeout=5):
                    print(f"QEMU: ovsdb-server доступен на 127.0.0.1:{host_port}")
                if check_webui:
                    check_webui_health("127.0.0.1", webui_host_port, webui_health_path, timeout=120)
                return 0
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()


def build_parser():
    parser = argparse.ArgumentParser(description="Run a 4stm4 netOS image in QEMU")
    parser.add_argument("--target", choices=sorted(TARGETS), default="qemu-virt")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--host-port", type=int, default=6640)
    parser.add_argument("--webui-host-port", type=int, default=8080)
    parser.add_argument("--webui-guest-port", type=int, default=8080)
    parser.add_argument("--webui-health-path", default=os.environ.get("NETOS_WEBUI_HEALTH_PATH", DEFAULT_WEBUI_HEALTH_PATH))
    parser.add_argument("--check-webui", action="store_true")
    parser.add_argument("--skip-tcp-check", action="store_true")
    parser.add_argument("--qemu-bin", default=os.environ.get("QEMU_BIN", ""))
    return parser


def main():
    args = build_parser().parse_args()
    target = get_target(args.target)
    qemu_bin_name = args.qemu_bin or get_qemu_bin(target)
    qemu_bin = shutil.which(qemu_bin_name) or qemu_bin_name

    if not target.qemu_supported:
        raise RuntimeError(
            f"Target {target.name} не имеет QEMU-конфигурации. "
            "Pi 5/BCM2712 в текущем QEMU не эмулируется; используйте --target qemu-virt."
        )

    image_path = require_artifacts(target)
    cmd = build_qemu_cmd(
        target,
        qemu_bin,
        image_path,
        args.host_port,
        args.webui_host_port,
        args.webui_guest_port,
    )
    return wait_for_qemu(
        cmd,
        args.host_port,
        args.timeout,
        DEFAULT_READY_MARKERS,
        args.skip_tcp_check,
        args.check_webui,
        args.webui_host_port,
        args.webui_health_path,
    )


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"ОШИБКА: {exc}", file=sys.stderr)
        sys.exit(1)
