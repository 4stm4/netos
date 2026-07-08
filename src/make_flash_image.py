"""Assemble a full raw SPI-NOR flash image from a parametrized FlashLayout.

Phase 5 (flash-image assembler). Fully parametrized: partition offsets/sizes
come from :mod:`flash_layout`, artifacts (u-boot / kernel uImage / rootfs
squashfs) are passed in by source key. Nothing is hardcoded here — when the
real numbers arrive, only ``flash_layout.py`` changes.

Design notes:
  * NOR erased state is 0xFF, so the whole image is initialised to 0xFF and any
    region we do not populate (gaps, u-boot-env, and the per-device ``factory``
    partition) stays 0xFF — matching a freshly-erased chip.
  * ``preserve`` partitions (factory/ART) are NEVER written: MAC + RF calibration
    are per-device and flashed to the individual board. With full-dump flashing
    there is no sysupgrade, so "don't clobber factory" == "assembler never
    touches it" (STEP 2).
  * An artifact larger than its (fixed-size) partition is a hard error.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

from flash_layout import FlashLayout, MT7628_16M_LAYOUT

NOR_ERASED_BYTE = 0xFF


@dataclass(frozen=True)
class PartitionReport:
    name: str
    offset: int
    size: int
    used: int          # bytes actually written (0 for blank/preserve)
    source: Optional[str]

    @property
    def free(self) -> int:
        return self.size - self.used


def assemble_flash_image(
    layout: FlashLayout,
    artifacts: Dict[str, Path],
    out_path: Path,
) -> list[PartitionReport]:
    """Build the full flash image at *out_path* from *layout* + *artifacts*.

    *artifacts* maps a partition ``source`` key ("uboot"|"kernel"|"rootfs"|…) to
    a file path. A source referenced by the layout but absent from *artifacts*
    leaves that partition blank (0xFF) — useful for producing a
    bootloader-less image (kernel+rootfs only) while U-Boot is flashed
    separately.

    Returns a per-partition report (used/free bytes).
    """
    layout.validate()

    image = bytearray([NOR_ERASED_BYTE]) * layout.flash_size
    reports: list[PartitionReport] = []

    for p in layout.partitions:
        size = p.resolved_size(layout.flash_size)
        used = 0

        if p.preserve:
            # Per-device region (factory/ART) — never populated.
            reports.append(PartitionReport(p.name, p.offset, size, 0, p.source))
            continue

        art = artifacts.get(p.source) if p.source else None
        if art is not None:
            data = Path(art).read_bytes()
            if len(data) > size:
                raise ValueError(
                    f"artifact {art} ({len(data):#x} bytes) does not fit "
                    f"partition {p.name!r} ({size:#x} bytes)"
                )
            image[p.offset:p.offset + len(data)] = data
            used = len(data)

        reports.append(PartitionReport(p.name, p.offset, size, used, p.source))

    if len(image) != layout.flash_size:
        raise AssertionError("internal: image size drifted from flash size")

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(image)
    return reports


def format_report(reports: list[PartitionReport], flash_size: int) -> str:
    lines = [f"Flash image layout ({flash_size / 1024 / 1024:.0f} MB):"]
    for r in reports:
        tag = ""
        if r.source is None and r.used == 0:
            tag = "  (blank/preserve)"
        pct = (100.0 * r.used / r.size) if r.size else 0.0
        lines.append(
            f"  {r.name:<12} @ {r.offset:#08x}  size={r.size:#08x}  "
            f"used={r.used:#08x} ({pct:4.1f}%)  free={r.free:#08x}{tag}"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Assemble a full SPI-NOR flash image")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--uboot", type=Path, help="u-boot binary (optional)")
    ap.add_argument("--kernel", type=Path, help="kernel uImage (optional)")
    ap.add_argument("--rootfs", type=Path, help="rootfs squashfs (optional)")
    args = ap.parse_args()

    arts: Dict[str, Path] = {}
    if args.uboot:
        arts["uboot"] = args.uboot
    if args.kernel:
        arts["kernel"] = args.kernel
    if args.rootfs:
        arts["rootfs"] = args.rootfs

    rep = assemble_flash_image(MT7628_16M_LAYOUT, arts, args.out)
    print(format_report(rep, MT7628_16M_LAYOUT.flash_size))
    print(f"Wrote {args.out}")
