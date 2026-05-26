"""Unit tests for RootfsCache (M5).

Tests use a temporary directory with a fake rootfs.tar that mirrors the
structure created by a real Buildroot build.

Run:
    python src/tests/test_rootfs_cache.py
    python -m pytest src/tests/test_rootfs_cache.py -v
"""
from __future__ import annotations

import gzip
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
from netos_build.rootfs_cache import RootfsCache


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _plan(arch: str = "arm64", buildroot_arch: str = "aarch64",
          packages: tuple = ("BR2_PACKAGE_BUSYBOX=y",)) -> ResolvedBuildPlan:
    return ResolvedBuildPlan(
        target=f"qemu-{arch}", arch=arch,
        kernel_arch="arm64" if arch == "arm64" else "x86",
        kernel_source="mainline", kernel_defconfig="defconfig",
        kernel_filename="Image", cross_compile="aarch64-linux-gnu-",
        buildroot_arch=buildroot_arch,
        packages=packages,
        image_name=f"qemu-{arch}.img", image_format="raw",
        image_size_mb=512, boot_size_mb=64,
        install_boot_files=False, boot_cmdline="console=ttyAMA0 root=/dev/vda2",
    )


def _make_fake_output(tmp_root: str, content: bytes = b"") -> tuple[Path, bytes]:
    """Create a minimal output_dir with images/rootfs.tar.

    Returns (output_dir, rootfs_tar_bytes).
    """
    out = Path(tmp_root) / "buildroot-output-test"
    images_dir = out / "images"
    images_dir.mkdir(parents=True)

    # Build a tiny valid tar archive as fake rootfs.tar
    tar_buf = bytearray()
    import io
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        data = content or b"fake-rootfs-content"
        info = tarfile.TarInfo(name="etc/hostname")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))

        data2 = b"busybox-binary"
        info2 = tarfile.TarInfo(name="bin/busybox")
        info2.size = len(data2)
        tar.addfile(info2, io.BytesIO(data2))

    rootfs_bytes = buf.getvalue()
    (images_dir / "rootfs.tar").write_bytes(rootfs_bytes)
    return out, rootfs_bytes


# ---------------------------------------------------------------------------
# Tests: cache_key
# ---------------------------------------------------------------------------

class TestCacheKey(unittest.TestCase):

    def test_key_stable(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc = RootfsCache(Path(tmp))
            p  = _plan()
            self.assertEqual(
                rc.cache_key(p, "2026.02.1"),
                rc.cache_key(p, "2026.02.1"),
            )

    def test_key_format(self):
        """Key is ``{arch}-br{version}-{packages_hash16}``."""
        with tempfile.TemporaryDirectory() as tmp:
            rc  = RootfsCache(Path(tmp))
            key = rc.cache_key(_plan(), "2026.02.1")
            # arm64-br2026.02.1-<16 hex chars>
            self.assertTrue(key.startswith("arm64-br2026.02.1-"))
            # 16-char packages_hash at the end
            suffix = key.split("-")[-1]
            self.assertEqual(len(suffix), 16)

    def test_key_differs_by_arch(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc  = RootfsCache(Path(tmp))
            arm = rc.cache_key(_plan("arm64", "aarch64"), "2026.02.1")
            x86 = rc.cache_key(_plan("x86_64", "x86_64"), "2026.02.1")
            self.assertNotEqual(arm, x86)

    def test_key_differs_by_buildroot_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc = RootfsCache(Path(tmp))
            p  = _plan()
            self.assertNotEqual(
                rc.cache_key(p, "2026.02.1"),
                rc.cache_key(p, "2026.02.2"),
            )

    def test_key_differs_by_packages(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc = RootfsCache(Path(tmp))
            p1 = _plan(packages=("BR2_PACKAGE_BUSYBOX=y",))
            p2 = _plan(packages=("BR2_PACKAGE_BUSYBOX=y", "BR2_PACKAGE_GIT=y"))
            self.assertNotEqual(
                rc.cache_key(p1, "2026.02.1"),
                rc.cache_key(p2, "2026.02.1"),
            )

    def test_key_stable_across_package_order(self):
        """packages_hash is order-independent → key must be equal."""
        with tempfile.TemporaryDirectory() as tmp:
            rc = RootfsCache(Path(tmp))
            p1 = _plan(packages=("BR2_PACKAGE_BUSYBOX=y", "BR2_PACKAGE_GIT=y"))
            p2 = _plan(packages=("BR2_PACKAGE_GIT=y", "BR2_PACKAGE_BUSYBOX=y"))
            self.assertEqual(
                rc.cache_key(p1, "2026.02.1"),
                rc.cache_key(p2, "2026.02.1"),
            )


# ---------------------------------------------------------------------------
# Tests: archive_path / has
# ---------------------------------------------------------------------------

class TestHas(unittest.TestCase):

    def test_has_false_when_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc = RootfsCache(Path(tmp))
            self.assertFalse(rc.has(_plan(), "2026.02.1"))

    def test_has_true_after_pack(self):
        with tempfile.TemporaryDirectory() as tmp:
            out, _ = _make_fake_output(tmp)
            rc = RootfsCache(Path(tmp) / "cache")
            rc.pack(_plan(), "2026.02.1", out)
            self.assertTrue(rc.has(_plan(), "2026.02.1"))

    def test_archive_path_ends_with_rootfs_tar_gz(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc   = RootfsCache(Path(tmp))
            path = rc.archive_path(_plan(), "2026.02.1")
            self.assertTrue(str(path).endswith(".rootfs.tar.gz"))


# ---------------------------------------------------------------------------
# Tests: pack
# ---------------------------------------------------------------------------

class TestPack(unittest.TestCase):

    def test_pack_creates_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            out, _ = _make_fake_output(tmp)
            rc   = RootfsCache(Path(tmp) / "cache")
            dest = rc.pack(_plan(), "2026.02.1", out)
            self.assertTrue(dest.exists())
            self.assertGreater(dest.stat().st_size, 0)

    def test_pack_is_valid_gzip(self):
        with tempfile.TemporaryDirectory() as tmp:
            out, _ = _make_fake_output(tmp)
            rc   = RootfsCache(Path(tmp) / "cache")
            dest = rc.pack(_plan(), "2026.02.1", out)
            with gzip.open(dest, "rb") as gz:
                data = gz.read()
            self.assertGreater(len(data), 0)

    def test_pack_decompresses_to_valid_tar(self):
        with tempfile.TemporaryDirectory() as tmp:
            out, _ = _make_fake_output(tmp)
            rc   = RootfsCache(Path(tmp) / "cache")
            dest = rc.pack(_plan(), "2026.02.1", out)
            import io
            with gzip.open(dest, "rb") as gz:
                raw = gz.read()
            with tarfile.open(fileobj=io.BytesIO(raw)) as tar:
                names = tar.getnames()
            self.assertIn("etc/hostname", names)
            self.assertIn("bin/busybox", names)

    def test_pack_raises_on_missing_rootfs_tar(self):
        with tempfile.TemporaryDirectory() as tmp:
            empty = Path(tmp) / "empty-output"
            empty.mkdir()
            rc = RootfsCache(Path(tmp) / "cache")
            with self.assertRaises(FileNotFoundError):
                rc.pack(_plan(), "2026.02.1", empty)

    def test_pack_no_tmp_file_left_on_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            out, _ = _make_fake_output(tmp)
            rc = RootfsCache(Path(tmp) / "cache")
            rc.pack(_plan(), "2026.02.1", out)
            tmp_files = list((Path(tmp) / "cache" / "rootfs").glob("*.tmp"))
            self.assertEqual(tmp_files, [])

    def test_pack_updates_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            out, _ = _make_fake_output(tmp)
            rc  = RootfsCache(Path(tmp) / "cache")
            p   = _plan()
            rc.pack(p, "2026.02.1", out)
            idx = json.loads((rc.cache_dir / "index.json").read_text())
            key = rc.cache_key(p, "2026.02.1")
            self.assertIn(key, idx)
            self.assertEqual(idx[key]["arch"], "arm64")
            self.assertEqual(idx[key]["buildroot_version"], "2026.02.1")
            self.assertIn("packed_at", idx[key])
            self.assertIn("packages_hash", idx[key])


# ---------------------------------------------------------------------------
# Tests: restore
# ---------------------------------------------------------------------------

class TestRestore(unittest.TestCase):

    def test_restore_returns_false_on_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc = RootfsCache(Path(tmp) / "cache")
            self.assertFalse(rc.restore(_plan(), "2026.02.1", Path(tmp) / "out"))

    def test_restore_writes_rootfs_tar(self):
        with tempfile.TemporaryDirectory() as tmp:
            out, original_bytes = _make_fake_output(tmp)
            rc = RootfsCache(Path(tmp) / "cache")
            p  = _plan()
            rc.pack(p, "2026.02.1", out)

            restore_dir = Path(tmp) / "restored-output"
            restore_dir.mkdir()
            result = rc.restore(p, "2026.02.1", restore_dir)

            self.assertTrue(result)
            restored_tar = restore_dir / "images" / "rootfs.tar"
            self.assertTrue(restored_tar.exists())
            self.assertEqual(restored_tar.read_bytes(), original_bytes)

    def test_restore_creates_images_dir_if_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            out, _ = _make_fake_output(tmp)
            rc = RootfsCache(Path(tmp) / "cache")
            p  = _plan()
            rc.pack(p, "2026.02.1", out)

            restore_dir = Path(tmp) / "new-output"
            # Do NOT create restore_dir/images/ — restore must create it
            restore_dir.mkdir()
            result = rc.restore(p, "2026.02.1", restore_dir)

            self.assertTrue(result)
            self.assertTrue((restore_dir / "images" / "rootfs.tar").exists())

    def test_restore_returns_false_on_corrupt_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc = RootfsCache(Path(tmp) / "cache")
            p  = _plan()
            rc.cache_dir.mkdir(parents=True, exist_ok=True)
            archive = rc.archive_path(p, "2026.02.1")
            archive.write_bytes(b"not-a-valid-gzip-file")

            restore_dir = Path(tmp) / "out"
            restore_dir.mkdir()
            result = rc.restore(p, "2026.02.1", restore_dir)

            self.assertFalse(result)
            # Corrupt archive must be deleted
            self.assertFalse(archive.exists())

    def test_restore_no_tmp_file_left_on_corrupt(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc = RootfsCache(Path(tmp) / "cache")
            p  = _plan()
            rc.cache_dir.mkdir(parents=True, exist_ok=True)
            rc.archive_path(p, "2026.02.1").write_bytes(b"garbage")

            restore_dir = Path(tmp) / "out"
            restore_dir.mkdir()
            rc.restore(p, "2026.02.1", restore_dir)

            tmp_files = list((restore_dir / "images").glob("*.tmp"))
            self.assertEqual(tmp_files, [])


# ---------------------------------------------------------------------------
# Tests: pack → restore roundtrip
# ---------------------------------------------------------------------------

class TestRoundtrip(unittest.TestCase):

    def test_roundtrip_content_identical(self):
        """rootfs.tar after restore must be byte-for-byte identical."""
        with tempfile.TemporaryDirectory() as tmp:
            out, original_bytes = _make_fake_output(tmp)
            rc = RootfsCache(Path(tmp) / "cache")
            p  = _plan()

            rc.pack(p, "2026.02.1", out)

            restore_dir = Path(tmp) / "restored"
            restore_dir.mkdir()
            result = rc.restore(p, "2026.02.1", restore_dir)

            self.assertTrue(result)
            restored = restore_dir / "images" / "rootfs.tar"
            self.assertEqual(restored.read_bytes(), original_bytes)

    def test_different_packages_have_separate_archives(self):
        with tempfile.TemporaryDirectory() as tmp:
            out, _ = _make_fake_output(tmp)
            rc = RootfsCache(Path(tmp) / "cache")
            p1 = _plan(packages=("BR2_PACKAGE_BUSYBOX=y",))
            p2 = _plan(packages=("BR2_PACKAGE_BUSYBOX=y", "BR2_PACKAGE_GIT=y"))

            rc.pack(p1, "2026.02.1", out)
            rc.pack(p2, "2026.02.1", out)

            self.assertNotEqual(
                rc.archive_path(p1, "2026.02.1"),
                rc.archive_path(p2, "2026.02.1"),
            )
            self.assertTrue(rc.has(p1, "2026.02.1"))
            self.assertTrue(rc.has(p2, "2026.02.1"))

    def test_second_pack_does_not_crash(self):
        """Packing the same key twice must succeed (idempotent)."""
        with tempfile.TemporaryDirectory() as tmp:
            out, _ = _make_fake_output(tmp)
            rc = RootfsCache(Path(tmp) / "cache")
            p  = _plan()
            rc.pack(p, "2026.02.1", out)
            rc.pack(p, "2026.02.1", out)  # second pack — should not raise
            self.assertTrue(rc.has(p, "2026.02.1"))

    def test_different_arches_have_separate_archives(self):
        with tempfile.TemporaryDirectory() as tmp:
            out, _ = _make_fake_output(tmp)
            rc    = RootfsCache(Path(tmp) / "cache")
            p_arm = _plan("arm64",  "aarch64")
            p_x86 = _plan("x86_64", "x86_64")

            rc.pack(p_arm, "2026.02.1", out)
            rc.pack(p_x86, "2026.02.1", out)

            self.assertNotEqual(
                rc.archive_path(p_arm, "2026.02.1"),
                rc.archive_path(p_x86, "2026.02.1"),
            )
            self.assertTrue(rc.has(p_arm, "2026.02.1"))
            self.assertTrue(rc.has(p_x86, "2026.02.1"))


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
