"""Tests for the parametrized flash layout + 16 MB image assembler.

Run:
    python -m pytest src/tests/test_flash_image.py -v
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

_SRC = Path(__file__).parent.parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from flash_layout import (
    ERASE_BLOCK,
    FlashLayout,
    FlashPartition,
    MT7628_16M_LAYOUT,
    MT7628_FLASH_SIZE,
)
from make_flash_image import NOR_ERASED_BYTE, assemble_flash_image


# --------------------------------------------------------------------------
# Layout validation
# --------------------------------------------------------------------------

def test_mt7628_layout_is_valid():
    MT7628_16M_LAYOUT.validate()  # must not raise


def test_mt7628_layout_covers_full_flash_without_overlap():
    parts = MT7628_16M_LAYOUT.partitions
    # contiguous, no gaps, rootfs reaches end
    assert parts[0].offset == 0
    for a, b in zip(parts, parts[1:]):
        assert a.end(MT7628_FLASH_SIZE) == b.offset, (a.name, b.name)
    assert parts[-1].end(MT7628_FLASH_SIZE) == MT7628_FLASH_SIZE


def test_factory_is_preserve_and_blank_source():
    factory = next(p for p in MT7628_16M_LAYOUT.partitions if p.name == "factory")
    assert factory.preserve is True
    assert factory.source is None
    assert factory.offset == 0x040000 and factory.size == 0x010000


def test_overlap_detected():
    bad = FlashLayout(0x100000, ERASE_BLOCK, (
        FlashPartition("a", 0x0, 0x20000),
        FlashPartition("b", 0x10000, 0x10000),  # overlaps a
    ))
    with pytest.raises(ValueError, match="overlap"):
        bad.validate()


def test_misaligned_offset_detected():
    bad = FlashLayout(0x100000, ERASE_BLOCK, (
        FlashPartition("a", 0x8000, 0x10000),  # not 64k aligned
    ))
    with pytest.raises(ValueError, match="aligned"):
        bad.validate()


def test_grow_to_end_must_be_last():
    bad = FlashLayout(0x100000, ERASE_BLOCK, (
        FlashPartition("a", 0x0, 0x0),          # grow-to-end but not last
        FlashPartition("b", 0x10000, 0x10000),
    ))
    with pytest.raises(ValueError, match="must be last"):
        bad.validate()


def test_out_of_bounds_detected():
    bad = FlashLayout(0x100000, ERASE_BLOCK, (
        FlashPartition("a", 0x0, 0x200000),  # bigger than flash
    ))
    with pytest.raises(ValueError, match="past flash size"):
        bad.validate()


# --------------------------------------------------------------------------
# Assembler
# --------------------------------------------------------------------------

def _tmp(content: bytes, name: str) -> Path:
    d = Path(tempfile.mkdtemp())
    p = d / name
    p.write_bytes(content)
    return p


def test_assemble_places_artifacts_and_preserves_factory():
    work = Path(tempfile.mkdtemp())
    kernel = _tmp(b"K" * 1000, "uImage")
    rootfs = _tmp(b"R" * 5000, "root.squashfs")
    uboot = _tmp(b"U" * 200, "u-boot.bin")
    out = work / "flash.bin"

    reports = assemble_flash_image(
        MT7628_16M_LAYOUT,
        {"uboot": uboot, "kernel": kernel, "rootfs": rootfs},
        out,
    )

    img = out.read_bytes()
    # Full 16 MB
    assert len(img) == MT7628_FLASH_SIZE
    # Artifacts at their partition offsets
    assert img[0x000000:0x000000 + 200] == b"U" * 200
    assert img[0x050000:0x050000 + 1000] == b"K" * 1000
    assert img[0x250000:0x250000 + 5000] == b"R" * 5000
    # factory (0x40000..0x50000) left fully erased (0xFF) — never written
    assert set(img[0x040000:0x050000]) == {NOR_ERASED_BYTE}
    # u-boot-env (blank source) also erased
    assert set(img[0x030000:0x040000]) == {NOR_ERASED_BYTE}
    # gap right after kernel artifact is erased
    assert img[0x050000 + 1000] == NOR_ERASED_BYTE

    rep = {r.name: r for r in reports}
    assert rep["kernel"].used == 1000
    assert rep["rootfs"].used == 5000
    assert rep["factory"].used == 0


def test_missing_artifact_leaves_partition_blank():
    work = Path(tempfile.mkdtemp())
    rootfs = _tmp(b"R" * 4096, "root.squashfs")
    out = work / "flash.bin"
    # No uboot / kernel provided → those regions stay 0xFF
    assemble_flash_image(MT7628_16M_LAYOUT, {"rootfs": rootfs}, out)
    img = out.read_bytes()
    assert set(img[0x000000:0x030000]) == {NOR_ERASED_BYTE}   # u-boot blank
    assert set(img[0x050000:0x250000]) == {NOR_ERASED_BYTE}   # kernel blank
    assert img[0x250000:0x250000 + 4096] == b"R" * 4096


def test_oversize_artifact_raises():
    work = Path(tempfile.mkdtemp())
    # kernel partition is 0x200000; give it more
    big = _tmp(b"K" * (0x200000 + 1), "uImage")
    out = work / "flash.bin"
    with pytest.raises(ValueError, match="does not fit"):
        assemble_flash_image(MT7628_16M_LAYOUT, {"kernel": big}, out)


def test_rootfs_grows_to_end():
    rootfs = next(p for p in MT7628_16M_LAYOUT.partitions if p.name == "rootfs")
    assert rootfs.size == 0
    assert rootfs.resolved_size(MT7628_FLASH_SIZE) == MT7628_FLASH_SIZE - rootfs.offset
