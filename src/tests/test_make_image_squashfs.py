"""Unit tests for the squashfs (SPI-NOR/MTD) image path in make_image.

Covers:
  * rootfs_type dispatch — squashfs targets bypass the ext4/SD builder
  * _pad_file_to — erase-block padding math
  * create_squashfs_img — real mksquashfs build (skipped if tool absent)

Run:
    python -m pytest src/tests/test_make_image_squashfs.py -v
"""
from __future__ import annotations

import dataclasses
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_SRC = Path(__file__).parent.parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import make_image
from targets import TARGETS


def _squashfs_target(**overrides):
    """Derive a squashfs flash target from an existing one for testing."""
    base = TARGETS["zero2w"]
    fields = dict(
        name="mt7628-test",
        rootfs_type="squashfs",
        image_name="mt7628-test.img",
        squashfs_comp="gzip",  # gzip: always available in squashfs-tools
        squashfs_block_kb=64,
        flash_erase_kb=64,
    )
    fields.update(overrides)
    return dataclasses.replace(base, **fields)


class TestPadFileTo(unittest.TestCase):
    def _write(self, size: int) -> Path:
        tmp = Path(tempfile.mkdtemp()) / "blob"
        tmp.write_bytes(b"\xaa" * size)
        self.addCleanup(shutil.rmtree, tmp.parent)
        return tmp

    def test_pads_up_to_boundary(self):
        p = self._write(100)
        make_image._pad_file_to(p, 64 * 1024)
        self.assertEqual(p.stat().st_size, 64 * 1024)

    def test_no_pad_when_already_aligned(self):
        p = self._write(64 * 1024)
        make_image._pad_file_to(p, 64 * 1024)
        self.assertEqual(p.stat().st_size, 64 * 1024)

    def test_multi_block(self):
        p = self._write(64 * 1024 + 1)
        make_image._pad_file_to(p, 64 * 1024)
        self.assertEqual(p.stat().st_size, 128 * 1024)

    def test_zero_align_noop(self):
        p = self._write(123)
        make_image._pad_file_to(p, 0)
        self.assertEqual(p.stat().st_size, 123)


class TestDispatch(unittest.TestCase):
    def test_squashfs_target_dispatches_to_squashfs_builder(self):
        tgt = _squashfs_target()
        with mock.patch.object(make_image, "create_squashfs_img") as sq:
            make_image.create_img(tgt, image_path=Path("/tmp/x.img"))
            sq.assert_called_once()

    def test_ext4_target_does_not_call_squashfs_builder(self):
        # Guard the ext4 path early so no root/loop operations run.
        tgt = TARGETS["zero2w"]
        with mock.patch.object(make_image, "create_squashfs_img") as sq, \
             mock.patch.object(make_image, "_image_layout",
                               side_effect=RuntimeError("stop-before-loop")):
            with self.assertRaises(RuntimeError):
                make_image.create_img(tgt)
            sq.assert_not_called()


@unittest.skipIf(shutil.which("mksquashfs") is None, "squashfs-tools not installed")
class TestRealSquashfs(unittest.TestCase):
    def test_builds_and_pads(self):
        work = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, work)
        src = work / "rootfs"
        (src / "etc").mkdir(parents=True)
        (src / "etc" / "hostname").write_text("mt7628\n")
        (src / "bin").mkdir()
        (src / "bin" / "data").write_bytes(b"x" * 5000)

        out = work / "out.img"
        tgt = _squashfs_target()
        make_image.create_squashfs_img(tgt, image_path=out, source_dir=src)

        self.assertTrue(out.exists())
        # Padded to erase-block boundary
        self.assertEqual(out.stat().st_size % (tgt.flash_erase_kb * 1024), 0)
        # squashfs magic ("hsqs" little-endian)
        self.assertEqual(out.read_bytes()[:4], b"hsqs")


if __name__ == "__main__":
    unittest.main()
