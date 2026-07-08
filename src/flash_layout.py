"""Parametrized SPI-NOR flash layout for MTD/flash-image targets.

All offsets/sizes live HERE as data — the DTS and the image assembler both
read from this single source of truth, so when real numbers arrive only this
file (or a target's ``flash_layout`` field) changes.

Convention: NOR flash erased state is 0xFF; regions not populated by the
assembler are left as 0xFF (matching a freshly-erased chip).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# NOR erase-block granularity — offsets/sizes are validated against this.
ERASE_BLOCK = 0x10000            # 64 KB

# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FlashPartition:
    """One SPI-NOR partition.

    offset / size  — bytes; ``size == 0`` means "grow to the end of the flash".
    source         — artifact key the assembler writes here ("uboot" | "kernel"
                     | "rootfs" | ...). ``None`` => region left blank (0xFF).
    preserve       — never populated by the assembler (per-device data such as
                     the factory/ART partition: MAC + RF calibration, written to
                     the individual board at flash time). Implies source=None.
    read_only      — advisory; mirrors the DTS ``read-only`` flag.
    """

    name: str
    offset: int
    size: int
    source: Optional[str] = None
    preserve: bool = False
    read_only: bool = False

    def resolved_size(self, flash_size: int) -> int:
        """Size in bytes, resolving a grow-to-end (size == 0) partition."""
        return self.size if self.size else flash_size - self.offset

    def end(self, flash_size: int) -> int:
        return self.offset + self.resolved_size(flash_size)


@dataclass(frozen=True)
class FlashLayout:
    """A complete flash layout: total size + ordered partitions."""

    flash_size: int
    erase_block: int
    partitions: tuple[FlashPartition, ...]

    def validate(self) -> None:
        """Raise ValueError on any structural problem (overlap, misalignment,
        out-of-bounds, grow-to-end not last)."""
        prev_end = 0
        for i, p in enumerate(self.partitions):
            if p.offset % self.erase_block:
                raise ValueError(
                    f"partition {p.name!r} offset {p.offset:#x} is not "
                    f"aligned to erase block {self.erase_block:#x}"
                )
            if p.size and p.size % self.erase_block:
                raise ValueError(
                    f"partition {p.name!r} size {p.size:#x} is not aligned "
                    f"to erase block {self.erase_block:#x}"
                )
            if p.offset < prev_end:
                raise ValueError(
                    f"partition {p.name!r} at {p.offset:#x} overlaps previous "
                    f"partition ending at {prev_end:#x}"
                )
            if p.size == 0 and i != len(self.partitions) - 1:
                raise ValueError(
                    f"grow-to-end partition {p.name!r} must be last"
                )
            end = p.end(self.flash_size)
            if end > self.flash_size:
                raise ValueError(
                    f"partition {p.name!r} ends at {end:#x}, past flash size "
                    f"{self.flash_size:#x}"
                )
            prev_end = end

    def by_source(self, source: str) -> "FlashPartition | None":
        for p in self.partitions:
            if p.source == source:
                return p
        return None


# ---------------------------------------------------------------------------
# MT7628AN — 16 MB SPI-NOR (ramips convention, STEP 1)
# ---------------------------------------------------------------------------
#
# Edit offsets HERE only. Mirror any change into
# board/4stm4/mt7628/custom-mt7628-board.dts.
#
# NOTE (path B / Buildroot + mainline): mainline has no OpenWrt mtdsplit, so the
# single "firmware" region (0x050000..end) is split into EXPLICIT kernel+rootfs.
# MT7628_FIRMWARE_KERNEL_SIZE is the kernel-partition cap (a parameter — size it
# to the real uImage once known).

MT7628_FLASH_SIZE = 0x1000000            # 16 MB
MT7628_FIRMWARE_START = 0x050000         # firmware region start (after factory)
MT7628_FIRMWARE_KERNEL_SIZE = 0x200000   # 2 MB kernel cap — TODO: size to uImage

MT7628_16M_LAYOUT = FlashLayout(
    flash_size=MT7628_FLASH_SIZE,
    erase_block=ERASE_BLOCK,
    partitions=(
        FlashPartition("u-boot",     0x000000, 0x030000, source="uboot", read_only=True),
        FlashPartition("u-boot-env", 0x030000, 0x010000, source=None,    read_only=True),
        # ART/EEPROM — per-device, never written by the assembler (STEP 2).
        FlashPartition("factory",    0x040000, 0x010000, preserve=True,  read_only=True),
        FlashPartition("kernel",     MT7628_FIRMWARE_START, MT7628_FIRMWARE_KERNEL_SIZE,
                       source="kernel"),
        # rootfs grows to end of flash (size == 0).
        FlashPartition("rootfs",     MT7628_FIRMWARE_START + MT7628_FIRMWARE_KERNEL_SIZE, 0,
                       source="rootfs"),
    ),
)
