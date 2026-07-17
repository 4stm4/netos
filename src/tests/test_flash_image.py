"""Tests for the parametrized flash layout + 16 MB image assembler.

Run:
    python -m pytest src/tests/test_flash_image.py -v
"""
from __future__ import annotations

import re
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
    # contiguous, no gaps, overlay (last) reaches end
    assert parts[0].offset == 0
    for a, b in zip(parts, parts[1:]):
        assert a.end(MT7628_FLASH_SIZE) == b.offset, (a.name, b.name)
    assert parts[-1].name == "overlay"
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


def test_8m_layout_valid_and_rootfs_budget():
    from flash_layout import MT7628_8M_LAYOUT, MT7628_8M_OVERLAY_SIZE
    MT7628_8M_LAYOUT.validate()
    assert MT7628_8M_LAYOUT.flash_size == 0x800000
    rootfs = MT7628_8M_LAYOUT.by_source("rootfs")
    # head (u-boot 192k + env 64k + factory 64k + kernel 2M), then rootfs, then
    # overlay carved from the end.
    assert rootfs.offset == 0x250000
    assert rootfs.resolved_size(0x800000) == 0x800000 - MT7628_8M_OVERLAY_SIZE - 0x250000
    # sanity: rootfs still comfortably larger than a minimal AP squashfs (~4 MB)
    assert rootfs.resolved_size(0x800000) > 4 * 1024 * 1024


def test_8m_assembles_full_image():
    work = Path(tempfile.mkdtemp())
    from flash_layout import MT7628_8M_LAYOUT
    kernel = _tmp(b"K" * 1000, "uImage")
    rootfs = _tmp(b"R" * 5000, "root.squashfs")
    out = work / "flash8.bin"
    assemble_flash_image(MT7628_8M_LAYOUT, {"kernel": kernel, "rootfs": rootfs}, out)
    assert out.stat().st_size == 0x800000


@pytest.mark.parametrize("layout_name", ["MT7628_8M_LAYOUT", "MT7628_16M_LAYOUT"])
def test_overlay_present_writable_and_grows_to_end(layout_name):
    import flash_layout
    L = getattr(flash_layout, layout_name)
    overlay = next((p for p in L.partitions if p.name == "overlay"), None)
    assert overlay is not None, "writable overlay partition must exist"
    assert overlay.read_only is False
    assert overlay.preserve is False
    assert overlay.source is None            # blank at build → fresh jffs2 on boot
    assert overlay.size == 0                  # grow-to-end
    assert L.partitions[-1] is overlay        # must be last
    assert overlay.end(L.flash_size) == L.flash_size


_BOARD_DIR = _SRC.parent / "board" / "4stm4" / "mt7628"


def _parse_dts_partitions(dts: Path) -> list[tuple[str, int, int]]:
    """Extract (label, offset, size) triples from the partitions node of a .dts.

    Matches ``label = "x";`` immediately followed (within a few lines) by
    ``reg = <0xAAA 0xBBB>;`` — the partition entries. GPIO labels have no reg
    and are skipped.
    """
    text = dts.read_text()
    out: list[tuple[str, int, int]] = []
    pat = re.compile(
        r'label\s*=\s*"([^"]+)"\s*;\s*(?:reg\s*=\s*<\s*(0x[0-9a-fA-F]+)\s+(0x[0-9a-fA-F]+)\s*>\s*;)?'
    )
    for m in pat.finditer(text):
        name, off, size = m.group(1), m.group(2), m.group(3)
        if off is None:
            continue  # e.g. gpio-keys/leds labels have no reg
        out.append((name, int(off, 16), int(size, 16)))
    return out


@pytest.mark.parametrize("dts_name,layout_name", [
    ("custom-mt7628-board-16m.dts", "MT7628_16M_LAYOUT"),
    ("custom-mt7628-board-8m.dts",  "MT7628_8M_LAYOUT"),
])
def test_dts_partitions_match_code_layout(dts_name, layout_name):
    """Guard against DTS <-> flash_layout.py drift: the .dts partition table must
    equal the code layout (same names, offsets, and explicit sizes)."""
    import flash_layout
    L = getattr(flash_layout, layout_name)
    dts_parts = _parse_dts_partitions(_BOARD_DIR / dts_name)

    code_parts = [
        (p.name, p.offset, p.resolved_size(L.flash_size)) for p in L.partitions
    ]
    assert dts_parts == code_parts, (
        f"{dts_name} partitions differ from {layout_name}:\n"
        f"  dts : {dts_parts}\n  code: {code_parts}"
    )


def test_overlay_region_blank_in_assembled_image():
    work = Path(tempfile.mkdtemp())
    kernel = _tmp(b"K" * 1000, "uImage")
    rootfs = _tmp(b"R" * 5000, "root.squashfs")
    out = work / "flash.bin"
    assemble_flash_image(MT7628_16M_LAYOUT, {"kernel": kernel, "rootfs": rootfs}, out)
    img = out.read_bytes()
    overlay = next(p for p in MT7628_16M_LAYOUT.partitions if p.name == "overlay")
    region = img[overlay.offset:overlay.end(MT7628_FLASH_SIZE)]
    assert set(region) == {NOR_ERASED_BYTE}   # erased → jffs2 formats on first boot
