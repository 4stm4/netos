"""Unit tests for ResolvedBuildPlan and LockFile.

Run:
    python src/tests/test_plan.py
    python -m pytest src/tests/test_plan.py -v
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

_SRC = Path(__file__).parent.parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from netos_build.plan import ResolvedBuildPlan
from netos_build.lockfile import LockFile
from targets import TARGETS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_plan(**overrides) -> ResolvedBuildPlan:
    defaults = dict(
        target            = "qemu-virt",
        arch              = "arm64",
        kernel_arch       = "arm64",
        kernel_source     = "mainline",
        kernel_defconfig  = "defconfig",
        kernel_filename   = "Image",
        cross_compile     = "aarch64-linux-gnu-",
        buildroot_arch    = "aarch64",
        packages          = ("BR2_PACKAGE_BUSYBOX=y",),
        image_name        = "qemu-virt.img",
        image_format      = "raw",
        image_size_mb     = 512,
        boot_size_mb      = 64,
        install_boot_files = False,
        boot_cmdline      = "console=ttyAMA0 root=/dev/vda2",
    )
    defaults.update(overrides)
    return ResolvedBuildPlan(**defaults)


# ---------------------------------------------------------------------------
# ResolvedBuildPlan
# ---------------------------------------------------------------------------

class TestResolvedBuildPlan(unittest.TestCase):

    def test_basic_construction(self):
        plan = _make_plan()
        self.assertEqual(plan.target, "qemu-virt")
        self.assertEqual(plan.arch,   "arm64")
        self.assertEqual(plan.cache_policy, "use")

    def test_invalid_cache_policy_raises(self):
        with self.assertRaises(ValueError):
            _make_plan(cache_policy="fast-please")

    def test_invalid_image_format_raises(self):
        with self.assertRaises(ValueError):
            _make_plan(image_format="vmdk")

    def test_all_packages_combines_extra(self):
        plan = _make_plan(
            packages=("BR2_PACKAGE_BUSYBOX=y",),
            extra_packages=("BR2_PACKAGE_GIT=y",),
        )
        self.assertIn("BR2_PACKAGE_BUSYBOX=y", plan.all_packages)
        self.assertIn("BR2_PACKAGE_GIT=y",     plan.all_packages)

    def test_packages_hash_stable(self):
        plan = _make_plan(packages=("BR2_PACKAGE_BUSYBOX=y", "BR2_PACKAGE_GIT=y"))
        h1 = plan.packages_hash()
        h2 = _make_plan(packages=("BR2_PACKAGE_GIT=y", "BR2_PACKAGE_BUSYBOX=y")).packages_hash()
        # Sorted before hashing → order-independent
        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), 16)

    def test_packages_hash_differs_on_different_packages(self):
        p1 = _make_plan(packages=("BR2_PACKAGE_BUSYBOX=y",)).packages_hash()
        p2 = _make_plan(packages=("BR2_PACKAGE_GIT=y",)).packages_hash()
        self.assertNotEqual(p1, p2)

    def test_toolchain_cache_key_format(self):
        key = _make_plan().toolchain_cache_key()
        self.assertTrue(key.startswith("arm64-"))
        self.assertEqual(len(key), len("arm64-") + 8)

    def test_toolchain_cache_key_differs_by_arch(self):
        arm = _make_plan(arch="arm64",  buildroot_arch="aarch64",
                         cross_compile="aarch64-linux-gnu-").toolchain_cache_key()
        x86 = _make_plan(arch="x86_64", buildroot_arch="x86_64",
                         cross_compile="x86_64-linux-gnu-").toolchain_cache_key()
        self.assertNotEqual(arm, x86)


class TestFromTarget(unittest.TestCase):
    """ResolvedBuildPlan.from_target() for every registered target."""

    def _check_target(self, name: str):
        t    = TARGETS[name]
        plan = ResolvedBuildPlan.from_target(t)
        self.assertEqual(plan.target, name)
        self.assertIn(plan.arch,          ("arm64", "x86_64", "arm"))
        self.assertIn(plan.image_format,  ("raw",))
        self.assertIn(plan.cache_policy,  ("use", "rebuild", "refresh"))
        self.assertIsInstance(plan.packages, tuple)

    def test_qemu_virt(self):  self._check_target("qemu-virt")
    def test_qemu_x86(self):   self._check_target("qemu-x86")
    def test_pi5(self):        self._check_target("pi5")
    def test_pi4(self):        self._check_target("pi4")
    def test_zero2w(self):     self._check_target("zero2w")

    def test_x86_arch_resolved(self):
        plan = ResolvedBuildPlan.from_target(TARGETS["qemu-x86"])
        self.assertEqual(plan.arch,          "x86_64")
        self.assertEqual(plan.kernel_arch,   "x86")
        self.assertEqual(plan.cross_compile, "x86_64-linux-gnu-")
        self.assertEqual(plan.buildroot_arch, "x86_64")

    def test_extra_packages_forwarded(self):
        plan = ResolvedBuildPlan.from_target(
            TARGETS["qemu-virt"],
            extra_packages=["BR2_PACKAGE_NGINX=y"],
        )
        self.assertIn("BR2_PACKAGE_NGINX=y", plan.extra_packages)

    def test_cache_policy_forwarded(self):
        plan = ResolvedBuildPlan.from_target(TARGETS["qemu-virt"], cache_policy="rebuild")
        self.assertEqual(plan.cache_policy, "rebuild")


# ---------------------------------------------------------------------------
# LockFile
# ---------------------------------------------------------------------------

class TestLockFile(unittest.TestCase):

    def test_load_missing_returns_false(self):
        lock = LockFile(Path("/nonexistent/netos.lock.json"))
        self.assertFalse(lock.load())

    def test_save_and_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "netos.lock.json"
            lock = LockFile(path)
            lock.record("buildroot",
                        version="2026.02.1",
                        url="https://buildroot.org/downloads/buildroot-2026.02.1.tar.xz",
                        sha256="abc123")
            lock.save()

            lock2 = LockFile(path)
            self.assertTrue(lock2.load())
            self.assertEqual(lock2.sha256_for("buildroot"), "abc123")
            self.assertEqual(lock2.version_for("buildroot"), "2026.02.1")

    def test_sha256_for_missing_returns_none(self):
        lock = LockFile(Path("/tmp/does-not-matter.json"))
        self.assertIsNone(lock.sha256_for("nonexistent"))

    def test_sha256_for_empty_string_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lock.json"
            lock = LockFile(path)
            lock.record("linux-mainline", version="6.12.27",
                        url="https://cdn.kernel.org/...", sha256="")
            lock.save()
            lock2 = LockFile(path)
            lock2.load()
            self.assertIsNone(lock2.sha256_for("linux-mainline"))

    def test_validate_sha256_passes_on_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lock.json"
            lock = LockFile(path)
            lock.record("buildroot", version="2026.02.1",
                        url="https://buildroot.org/...", sha256="deadbeef")
            lock.save()
            lock2 = LockFile(path); lock2.load()
            lock2.validate_sha256("buildroot", "deadbeef")   # must not raise

    def test_validate_sha256_raises_on_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lock.json"
            lock = LockFile(path)
            lock.record("buildroot", version="2026.02.1",
                        url="https://buildroot.org/...", sha256="correcthash")
            lock.save()
            lock2 = LockFile(path); lock2.load()
            with self.assertRaises(RuntimeError):
                lock2.validate_sha256("buildroot", "wronghash")

    def test_validate_sha256_noop_when_not_in_lock(self):
        lock = LockFile(Path("/tmp/x.json"))
        lock.validate_sha256("unknown-artifact", "anyhash")  # must not raise

    def test_record_updates_existing_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lock.json"
            lock = LockFile(path)
            lock.record("buildroot", version="old", url="https://old", sha256="oldhash")
            lock.record("buildroot", version="new", url="https://new", sha256="newhash")
            lock.save()
            lock2 = LockFile(path); lock2.load()
            self.assertEqual(lock2.version_for("buildroot"), "new")
            self.assertEqual(lock2.sha256_for("buildroot"),  "newhash")

    def test_multiple_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lock.json"
            lock = LockFile(path)
            lock.record("buildroot",   version="2026.02.1", url="https://a", sha256="hash1")
            lock.record("openvswitch", version="3.4.1",     url="https://b", sha256="hash2")
            lock.save()
            lock2 = LockFile(path); lock2.load()
            self.assertEqual(lock2.sha256_for("buildroot"),   "hash1")
            self.assertEqual(lock2.sha256_for("openvswitch"), "hash2")

    def test_lock_file_json_structure(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lock.json"
            lock = LockFile(path)
            lock.record("buildroot", version="1.0", url="https://x", sha256="abc")
            lock.save()
            data = json.loads(path.read_text())
            self.assertEqual(data["version"], 1)
            self.assertIn("generated_at", data)
            self.assertIn("buildroot", data["artifacts"])

    def test_load_ignores_wrong_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lock.json"
            path.write_text(json.dumps({
                "version": 99,
                "artifacts": {"buildroot": {"version": "x", "url": "", "sha256": "abc"}}
            }))
            lock = LockFile(path)
            self.assertFalse(lock.load())


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
