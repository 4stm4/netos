"""Unit tests for run_qemu helpers — M4 (x86 full support).

Tests cover QEMU command generation for both arm64 (qemu-virt) and
x86_64 (qemu-x86) targets without actually launching QEMU.

Run:
    python src/tests/test_run_qemu.py
    python -m pytest src/tests/test_run_qemu.py -v
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

_SRC = Path(__file__).parent.parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from targets import TARGETS, get_target
from run_qemu import (
    build_qemu_cmd,
    get_kernel_image,
    get_qemu_bin,
    require_artifacts,
    qemu_machine_supported,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_machine_output(machines: list[str]) -> str:
    """Simulate `qemu-system-* -machine help` output."""
    header = "Supported machines are:\n"
    lines = [f"{m}                 Description of {m}" for m in machines]
    return header + "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# get_qemu_bin
# ---------------------------------------------------------------------------

class TestGetQemuBin(unittest.TestCase):

    def test_arm64_returns_aarch64(self):
        target = get_target("qemu-virt")
        self.assertEqual(get_qemu_bin(target), "qemu-system-aarch64")

    def test_x86_returns_x86_64(self):
        target = get_target("qemu-x86")
        self.assertEqual(get_qemu_bin(target), "qemu-system-x86_64")

    def test_unknown_arch_defaults_to_aarch64(self):
        """Fallback for unrecognised kernel_arch is qemu-system-aarch64."""
        target = get_target("qemu-virt")
        # Patch the arch_to_bin dict via a dummy target with unknown arch
        from targets import TargetConfig
        fake = TargetConfig(
            name="fake", description="fake", kernel_defconfig="defconfig",
            kernel_filename="Image", image_name="fake.img",
            boot_config_lines=(), boot_cmdline="", required_boot_files=(),
            boot_firmware_files=(), buildroot_package_lines=(),
            install_boot_files=False, kernel_config_options=(),
            build_kernel_modules=False, image_size_mb=512, boot_size_mb=64,
            kernel_arch="riscv",
        )
        result = get_qemu_bin(fake)
        self.assertEqual(result, "qemu-system-aarch64")


# ---------------------------------------------------------------------------
# get_kernel_image
# ---------------------------------------------------------------------------

class TestGetKernelImage(unittest.TestCase):

    def test_arm64_path(self):
        target = get_target("qemu-virt")
        path = get_kernel_image(target)
        self.assertIn("mainline_linux", str(path))
        self.assertIn("arm64", str(path))
        self.assertTrue(str(path).endswith("Image"))

    def test_x86_path(self):
        target = get_target("qemu-x86")
        path = get_kernel_image(target)
        self.assertIn("mainline_linux", str(path))
        self.assertIn("x86", str(path))
        self.assertTrue(str(path).endswith("bzImage"))

    def test_rpi_target_uses_rpi_linux_dir(self):
        target = get_target("pi5")
        path = get_kernel_image(target)
        self.assertIn("rpi_linux", str(path))
        self.assertIn("arm64", str(path))


# ---------------------------------------------------------------------------
# qemu_machine_supported
# ---------------------------------------------------------------------------

class TestQemuMachineSupported(unittest.TestCase):

    def _run_checked_returning(self, stdout: str):
        result = MagicMock()
        result.returncode = 0
        result.stdout = stdout
        result.stderr = ""
        return result

    def test_supported_machine_returns_true(self):
        output = _fake_machine_output(["virt", "q35", "microvm"])
        with patch("run_qemu.run_checked",
                   return_value=self._run_checked_returning(output)):
            self.assertTrue(qemu_machine_supported("qemu-system-aarch64", "virt"))

    def test_unsupported_machine_returns_false(self):
        output = _fake_machine_output(["virt", "microvm"])
        with patch("run_qemu.run_checked",
                   return_value=self._run_checked_returning(output)):
            self.assertFalse(qemu_machine_supported("qemu-system-aarch64", "q35"))

    def test_nonzero_returncode_raises(self):
        result = MagicMock()
        result.returncode = 1
        result.stdout = ""
        result.stderr = "command not found"
        with patch("run_qemu.run_checked", return_value=result):
            with self.assertRaises(RuntimeError):
                qemu_machine_supported("qemu-missing", "virt")

    def test_x86_q35_machine(self):
        output = _fake_machine_output(["q35", "pc", "microvm"])
        with patch("run_qemu.run_checked",
                   return_value=self._run_checked_returning(output)):
            self.assertTrue(qemu_machine_supported("qemu-system-x86_64", "q35"))


# ---------------------------------------------------------------------------
# build_qemu_cmd — arm64
# ---------------------------------------------------------------------------

class TestBuildQemuCmdArm64(unittest.TestCase):

    def setUp(self):
        self.target = get_target("qemu-virt")
        self.image_path = Path("/tmp/qemu-virt.img")
        # Stub out qemu_machine_supported so we don't need QEMU installed
        self.patcher = patch("run_qemu.qemu_machine_supported", return_value=True)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()

    def _build(self, host_port=6640, webui_host_port=8080, webui_guest_port=8080):
        return build_qemu_cmd(
            self.target,
            "qemu-system-aarch64",
            self.image_path,
            host_port,
            webui_host_port,
            webui_guest_port,
        )

    def test_binary_is_first_element(self):
        cmd = self._build()
        self.assertEqual(cmd[0], "qemu-system-aarch64")

    def test_machine_flag(self):
        cmd = self._build()
        idx = cmd.index("-M")
        self.assertEqual(cmd[idx + 1], "virt")

    def test_cpu_flag(self):
        cmd = self._build()
        idx = cmd.index("-cpu")
        self.assertEqual(cmd[idx + 1], "cortex-a72")

    def test_kernel_flag_contains_Image(self):
        cmd = self._build()
        idx = cmd.index("-kernel")
        self.assertIn("Image", cmd[idx + 1])

    def test_drive_contains_image_path(self):
        cmd = self._build()
        idx = cmd.index("-drive")
        self.assertIn(str(self.image_path), cmd[idx + 1])

    def test_drive_virtio(self):
        cmd = self._build()
        idx = cmd.index("-drive")
        self.assertIn("if=virtio", cmd[idx + 1])

    def test_append_has_console_ttyAMA0(self):
        cmd = self._build()
        idx = cmd.index("-append")
        self.assertIn("ttyAMA0", cmd[idx + 1])

    def test_serial_stdio(self):
        cmd = self._build()
        idx = cmd.index("-serial")
        self.assertEqual(cmd[idx + 1], "stdio")

    def test_no_display(self):
        cmd = self._build()
        self.assertIn("-display", cmd)
        idx = cmd.index("-display")
        self.assertEqual(cmd[idx + 1], "none")

    def test_hostfwd_ovsdb_port(self):
        cmd = self._build(host_port=6640)
        netdev_val = cmd[cmd.index("-netdev") + 1]
        self.assertIn("hostfwd=tcp:127.0.0.1:6640-127.0.0.1:6640", netdev_val)

    def test_hostfwd_webui_port(self):
        cmd = self._build(webui_host_port=9090, webui_guest_port=8080)
        netdev_val = cmd[cmd.index("-netdev") + 1]
        self.assertIn("hostfwd=tcp:127.0.0.1:9090-127.0.0.1:8080", netdev_val)

    def test_no_reboot(self):
        cmd = self._build()
        self.assertIn("-no-reboot", cmd)


# ---------------------------------------------------------------------------
# build_qemu_cmd — x86_64
# ---------------------------------------------------------------------------

class TestBuildQemuCmdX86(unittest.TestCase):

    def setUp(self):
        self.target = get_target("qemu-x86")
        self.image_path = Path("/tmp/qemu-x86.img")
        self.patcher = patch("run_qemu.qemu_machine_supported", return_value=True)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()

    def _build(self, host_port=6640, webui_host_port=8080, webui_guest_port=8080):
        return build_qemu_cmd(
            self.target,
            "qemu-system-x86_64",
            self.image_path,
            host_port,
            webui_host_port,
            webui_guest_port,
        )

    def test_binary_is_x86_64(self):
        cmd = self._build()
        self.assertEqual(cmd[0], "qemu-system-x86_64")

    def test_machine_is_q35(self):
        cmd = self._build()
        idx = cmd.index("-M")
        self.assertEqual(cmd[idx + 1], "q35")

    def test_cpu_is_qemu64(self):
        cmd = self._build()
        idx = cmd.index("-cpu")
        self.assertEqual(cmd[idx + 1], "qemu64")

    def test_kernel_is_bzImage(self):
        cmd = self._build()
        idx = cmd.index("-kernel")
        self.assertIn("bzImage", cmd[idx + 1])

    def test_kernel_path_contains_x86(self):
        cmd = self._build()
        idx = cmd.index("-kernel")
        self.assertIn("x86", cmd[idx + 1])

    def test_append_has_console_ttyS0(self):
        cmd = self._build()
        idx = cmd.index("-append")
        self.assertIn("ttyS0", cmd[idx + 1])

    def test_append_has_root_vda2(self):
        cmd = self._build()
        idx = cmd.index("-append")
        self.assertIn("/dev/vda2", cmd[idx + 1])

    def test_drive_virtio(self):
        cmd = self._build()
        idx = cmd.index("-drive")
        self.assertIn("if=virtio", cmd[idx + 1])

    def test_virtio_net_device(self):
        cmd = self._build()
        idx = cmd.index("-device")
        self.assertIn("virtio-net-pci", cmd[idx + 1])


# ---------------------------------------------------------------------------
# build_qemu_cmd — unsupported target
# ---------------------------------------------------------------------------

class TestBuildQemuCmdUnsupported(unittest.TestCase):

    def test_pi5_raises(self):
        target = get_target("pi5")
        with self.assertRaises(RuntimeError) as ctx:
            build_qemu_cmd(target, "qemu-system-aarch64",
                           Path("/tmp/fake.img"), 6640, 8080, 8080)
        self.assertIn("pi5", str(ctx.exception))

    def test_pi4_raises(self):
        target = get_target("pi4")
        with self.assertRaises(RuntimeError):
            build_qemu_cmd(target, "qemu-system-aarch64",
                           Path("/tmp/fake.img"), 6640, 8080, 8080)


# ---------------------------------------------------------------------------
# require_artifacts
# ---------------------------------------------------------------------------

class TestRequireArtifacts(unittest.TestCase):

    def test_raises_when_image_missing(self):
        target = get_target("qemu-x86")
        with self.assertRaises(FileNotFoundError) as ctx:
            require_artifacts(target)
        self.assertIn(target.image_name, str(ctx.exception))

    def test_raises_when_kernel_missing(self):
        target = get_target("qemu-virt")
        with self.assertRaises(FileNotFoundError):
            require_artifacts(target)

    def test_ok_when_both_exist(self):
        target = get_target("qemu-x86")
        with tempfile.TemporaryDirectory() as tmp:
            # Patch PROJECT_ROOT so the image is found in tmp
            img = Path(tmp) / target.image_name
            img.write_bytes(b"fake-image")

            kernel = (Path(tmp) / "temp" / "mainline_linux" /
                      "arch" / target.kernel_arch / "boot" / target.kernel_filename)
            kernel.parent.mkdir(parents=True)
            kernel.write_bytes(b"fake-kernel")

            import run_qemu as rq
            orig_root = rq.PROJECT_ROOT
            try:
                rq.PROJECT_ROOT = Path(tmp)
                result = rq.require_artifacts(target)
                self.assertEqual(result, img)
            finally:
                rq.PROJECT_ROOT = orig_root


# ---------------------------------------------------------------------------
# Target x86 config sanity
# ---------------------------------------------------------------------------

class TestQemuX86TargetConfig(unittest.TestCase):
    """Ensure qemu-x86 TargetConfig is correctly wired up."""

    def test_qemu_supported(self):
        self.assertTrue(get_target("qemu-x86").qemu_supported)

    def test_qemu_machine_is_q35(self):
        self.assertEqual(get_target("qemu-x86").qemu_machine, "q35")

    def test_kernel_arch_is_x86(self):
        self.assertEqual(get_target("qemu-x86").kernel_arch, "x86")

    def test_kernel_filename_is_bzImage(self):
        self.assertEqual(get_target("qemu-x86").kernel_filename, "bzImage")

    def test_kernel_source_is_mainline(self):
        self.assertEqual(get_target("qemu-x86").kernel_source, "mainline")

    def test_buildroot_arch_is_x86_64(self):
        self.assertEqual(get_target("qemu-x86").buildroot_arch, "x86_64")

    def test_cross_compile_is_x86_64(self):
        self.assertEqual(get_target("qemu-x86").cross_compile, "x86_64-linux-gnu-")

    def test_boot_cmdline_has_ttyS0(self):
        self.assertIn("ttyS0", get_target("qemu-x86").boot_cmdline)

    def test_boot_cmdline_has_vda2(self):
        self.assertIn("/dev/vda2", get_target("qemu-x86").boot_cmdline)

    def test_no_boot_files_installed(self):
        self.assertFalse(get_target("qemu-x86").install_boot_files)


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
