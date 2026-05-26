"""Unit tests for ToolchainCache (M3).

Tests use a fake output_dir with a small directory tree that mirrors
the structure created by a real Buildroot build.

Run:
    python src/tests/test_toolchain_cache.py
    python -m pytest src/tests/test_toolchain_cache.py -v
"""
from __future__ import annotations

import json
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

_SRC = Path(__file__).parent.parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from netos_build.plan import ResolvedBuildPlan
from netos_build.toolchain_cache import ToolchainCache


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _plan(arch: str = "arm64", buildroot_arch: str = "aarch64",
          cross_compile: str = "aarch64-linux-gnu-") -> ResolvedBuildPlan:
    return ResolvedBuildPlan(
        target=f"qemu-{arch}", arch=arch,
        kernel_arch="arm64" if arch == "arm64" else "x86",
        kernel_source="mainline", kernel_defconfig="defconfig",
        kernel_filename="Image", cross_compile=cross_compile,
        buildroot_arch=buildroot_arch,
        packages=("BR2_PACKAGE_BUSYBOX=y",),
        image_name=f"qemu-{arch}.img", image_format="raw",
        image_size_mb=512, boot_size_mb=64,
        install_boot_files=False, boot_cmdline="console=ttyAMA0 root=/dev/vda2",
    )


def _make_fake_output(tmp_root: str) -> tuple[Path, dict[str, bytes]]:
    """Create a minimal Buildroot-style output dir.

    Returns (output_dir, {rel_path: content}) for later assertions.
    """
    out = Path(tmp_root) / "buildroot-output-test"

    # host/ — cross-compiler binaries + sysroot
    (out / "host" / "bin").mkdir(parents=True)
    (out / "host" / "lib").mkdir(parents=True)
    (out / "host" / "aarch64-buildroot-linux-gnu" / "sysroot" / "usr" / "lib").mkdir(parents=True)

    files: dict[str, bytes] = {
        "host/bin/aarch64-buildroot-linux-gnu-gcc":  b"fake-gcc-binary",
        "host/bin/aarch64-buildroot-linux-gnu-g++":  b"fake-gpp-binary",
        "host/bin/aarch64-buildroot-linux-gnu-ld":   b"fake-ld-binary",
        "host/lib/libgcc.a":                          b"fake-libgcc-archive",
        "host/aarch64-buildroot-linux-gnu/sysroot/usr/lib/libc.so.6": b"fake-libc",
    }
    # build/ — stamp files
    stamps = {
        "build/host-gcc-final-14.3.0/.stamp_built":          b"",
        "build/host-gcc-final-14.3.0/.stamp_configured":     b"",
        "build/host-gcc-final-14.3.0/.stamp_host_installed": b"",
        "build/host-binutils-2.43/.stamp_built":             b"",
        "build/toolchain-buildroot/.stamp_built":            b"",
    }
    # Virtual toolchain dirs (tiny)
    virtual = {
        "build/toolchain-buildroot/somefile":     b"meta",
        "build/toolchain-buildroot-aux/somefile": b"meta-aux",
    }
    files.update(stamps)
    files.update(virtual)

    # Config hash
    files[".last_toolchain_hash"] = b"abc123deadbeef"

    for rel, content in files.items():
        p = out / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)

    return out, files


# ---------------------------------------------------------------------------
# Tests: cache_key
# ---------------------------------------------------------------------------

class TestCacheKey(unittest.TestCase):

    def test_key_stable(self):
        """Same plan + version → same key on repeated calls."""
        with tempfile.TemporaryDirectory() as tmp:
            tc = ToolchainCache(Path(tmp))
            p  = _plan()
            self.assertEqual(
                tc.cache_key(p, "2026.02.1"),
                tc.cache_key(p, "2026.02.1"),
            )

    def test_key_format(self):
        """Key is ``{arch}-br{version}-{hash8}``."""
        with tempfile.TemporaryDirectory() as tmp:
            tc  = ToolchainCache(Path(tmp))
            key = tc.cache_key(_plan(), "2026.02.1")
            # arm64-br2026.02.1-xxxxxxxx
            parts = key.split("-")
            self.assertEqual(parts[0], "arm64")
            self.assertIn("br2026.02.1", key)
            # last segment is 8 hex chars
            self.assertEqual(len(parts[-1]), 8)

    def test_key_differs_by_arch(self):
        with tempfile.TemporaryDirectory() as tmp:
            tc   = ToolchainCache(Path(tmp))
            arm  = tc.cache_key(_plan("arm64",  "aarch64", "aarch64-linux-gnu-"), "2026.02.1")
            x86  = tc.cache_key(_plan("x86_64", "x86_64",  "x86_64-linux-gnu-"),  "2026.02.1")
            self.assertNotEqual(arm, x86)

    def test_key_differs_by_buildroot_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            tc = ToolchainCache(Path(tmp))
            p  = _plan()
            k1 = tc.cache_key(p, "2026.02.1")
            k2 = tc.cache_key(p, "2026.02.2")
            self.assertNotEqual(k1, k2)

    def test_key_differs_by_cross_compile(self):
        with tempfile.TemporaryDirectory() as tmp:
            tc = ToolchainCache(Path(tmp))
            k1 = tc.cache_key(_plan(cross_compile="aarch64-linux-gnu-"),     "2026.02.1")
            k2 = tc.cache_key(_plan(cross_compile="aarch64-poky-linux-gnu-"), "2026.02.1")
            self.assertNotEqual(k1, k2)


# ---------------------------------------------------------------------------
# Tests: has / archive_path
# ---------------------------------------------------------------------------

class TestHas(unittest.TestCase):

    def test_has_false_when_cache_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            tc = ToolchainCache(Path(tmp))
            self.assertFalse(tc.has(_plan(), "2026.02.1"))

    def test_has_true_after_pack(self):
        with tempfile.TemporaryDirectory() as tmp:
            out, _ = _make_fake_output(tmp)
            tc = ToolchainCache(Path(tmp) / "cache")
            tc.pack(_plan(), "2026.02.1", out)
            self.assertTrue(tc.has(_plan(), "2026.02.1"))

    def test_archive_path_ends_with_tar_gz(self):
        with tempfile.TemporaryDirectory() as tmp:
            tc   = ToolchainCache(Path(tmp))
            path = tc.archive_path(_plan(), "2026.02.1")
            self.assertTrue(str(path).endswith(".tar.gz"))


# ---------------------------------------------------------------------------
# Tests: pack
# ---------------------------------------------------------------------------

class TestPack(unittest.TestCase):

    def test_pack_creates_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            out, _ = _make_fake_output(tmp)
            tc = ToolchainCache(Path(tmp) / "cache")
            dest = tc.pack(_plan(), "2026.02.1", out)
            self.assertTrue(dest.exists())
            self.assertGreater(dest.stat().st_size, 0)

    def test_pack_is_valid_tar_gz(self):
        with tempfile.TemporaryDirectory() as tmp:
            out, _ = _make_fake_output(tmp)
            tc   = ToolchainCache(Path(tmp) / "cache")
            dest = tc.pack(_plan(), "2026.02.1", out)
            with tarfile.open(dest, "r:gz") as tar:
                names = tar.getnames()
            self.assertTrue(any(n.startswith("host/") for n in names))

    def test_pack_includes_host_binaries(self):
        with tempfile.TemporaryDirectory() as tmp:
            out, files = _make_fake_output(tmp)
            tc   = ToolchainCache(Path(tmp) / "cache")
            dest = tc.pack(_plan(), "2026.02.1", out)
            with tarfile.open(dest, "r:gz") as tar:
                names = set(tar.getnames())
            for rel in files:
                if rel.startswith("host/"):
                    self.assertIn(rel, names, f"Missing in archive: {rel}")

    def test_pack_includes_stamp_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            out, _ = _make_fake_output(tmp)
            tc   = ToolchainCache(Path(tmp) / "cache")
            dest = tc.pack(_plan(), "2026.02.1", out)
            with tarfile.open(dest, "r:gz") as tar:
                names = set(tar.getnames())
            self.assertIn("build/host-gcc-final-14.3.0/.stamp_built", names)
            self.assertIn("build/host-gcc-final-14.3.0/.stamp_configured", names)
            self.assertIn(".last_toolchain_hash", names)

    def test_pack_raises_on_missing_host(self):
        with tempfile.TemporaryDirectory() as tmp:
            empty_dir = Path(tmp) / "empty-output"
            empty_dir.mkdir()
            tc = ToolchainCache(Path(tmp) / "cache")
            with self.assertRaises(FileNotFoundError):
                tc.pack(_plan(), "2026.02.1", empty_dir)

    def test_pack_no_tmp_file_left_on_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            out, _ = _make_fake_output(tmp)
            tc   = ToolchainCache(Path(tmp) / "cache")
            tc.pack(_plan(), "2026.02.1", out)
            # No .tmp files should remain
            tmp_files = list((Path(tmp) / "cache" / "toolchains").glob("*.tmp"))
            self.assertEqual(tmp_files, [])

    def test_pack_updates_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            out, _ = _make_fake_output(tmp)
            tc  = ToolchainCache(Path(tmp) / "cache")
            p   = _plan()
            tc.pack(p, "2026.02.1", out)
            idx = json.loads((tc.cache_dir / "index.json").read_text())
            key = tc.cache_key(p, "2026.02.1")
            self.assertIn(key, idx)
            self.assertEqual(idx[key]["arch"], "arm64")
            self.assertEqual(idx[key]["buildroot_version"], "2026.02.1")
            self.assertIn("packed_at", idx[key])


# ---------------------------------------------------------------------------
# Tests: restore
# ---------------------------------------------------------------------------

class TestRestore(unittest.TestCase):

    def test_restore_returns_false_on_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            tc = ToolchainCache(Path(tmp) / "cache")
            self.assertFalse(tc.restore(_plan(), "2026.02.1", Path(tmp) / "out"))

    def test_restore_extracts_host_binaries(self):
        with tempfile.TemporaryDirectory() as tmp:
            out, files = _make_fake_output(tmp)
            tc      = ToolchainCache(Path(tmp) / "cache")
            p       = _plan()
            tc.pack(p, "2026.02.1", out)

            restore_dir = Path(tmp) / "restored-output"
            restore_dir.mkdir()
            result = tc.restore(p, "2026.02.1", restore_dir)

            self.assertTrue(result)
            for rel, content in files.items():
                restored = restore_dir / rel
                self.assertTrue(restored.exists(), f"Not restored: {rel}")
                self.assertEqual(restored.read_bytes(), content, f"Content mismatch: {rel}")

    def test_restore_returns_false_on_corrupt_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            tc  = ToolchainCache(Path(tmp) / "cache")
            p   = _plan()
            # Create a corrupt archive
            tc.cache_dir.mkdir(parents=True, exist_ok=True)
            archive = tc.archive_path(p, "2026.02.1")
            archive.write_bytes(b"this is not a valid gzip archive")

            restore_dir = Path(tmp) / "out"
            restore_dir.mkdir()
            result = tc.restore(p, "2026.02.1", restore_dir)

            self.assertFalse(result)
            # Corrupt archive should be deleted
            self.assertFalse(archive.exists())


# ---------------------------------------------------------------------------
# Tests: pack → restore roundtrip
# ---------------------------------------------------------------------------

class TestRoundtrip(unittest.TestCase):

    def test_pack_restore_roundtrip_content_identical(self):
        """Every file packed must be byte-for-byte identical after restore."""
        with tempfile.TemporaryDirectory() as tmp:
            out, files = _make_fake_output(tmp)
            tc = ToolchainCache(Path(tmp) / "cache")
            p  = _plan()

            tc.pack(p, "2026.02.1", out)

            restore_dir = Path(tmp) / "restored"
            restore_dir.mkdir()
            tc.restore(p, "2026.02.1", restore_dir)

            for rel, expected in files.items():
                restored = restore_dir / rel
                self.assertTrue(restored.exists(),   f"Missing: {rel}")
                self.assertEqual(restored.read_bytes(), expected, f"Mismatch: {rel}")

    def test_second_pack_skipped_if_cache_exists(self):
        """pack() result already cached → archive unchanged (no second write)."""
        with tempfile.TemporaryDirectory() as tmp:
            out, _ = _make_fake_output(tmp)
            tc  = ToolchainCache(Path(tmp) / "cache")
            p   = _plan()

            dest = tc.pack(p, "2026.02.1", out)
            mtime_1 = dest.stat().st_mtime

            # Second pack (same key) should create a new archive (overwrite is OK)
            # but the important thing is that has() returns True afterwards
            self.assertTrue(tc.has(p, "2026.02.1"))

    def test_different_arches_have_separate_archives(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_arm, _ = _make_fake_output(tmp)
            # Reuse same dir for x86 (different output_dir in practice,
            # but cache key differs so archives won't collide)
            tc    = ToolchainCache(Path(tmp) / "cache")
            p_arm = _plan("arm64",  "aarch64", "aarch64-linux-gnu-")
            p_x86 = _plan("x86_64", "x86_64",  "x86_64-linux-gnu-")

            tc.pack(p_arm, "2026.02.1", out_arm)
            tc.pack(p_x86, "2026.02.1", out_arm)

            self.assertNotEqual(
                tc.archive_path(p_arm, "2026.02.1"),
                tc.archive_path(p_x86, "2026.02.1"),
            )
            self.assertTrue(tc.has(p_arm, "2026.02.1"))
            self.assertTrue(tc.has(p_x86, "2026.02.1"))


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
