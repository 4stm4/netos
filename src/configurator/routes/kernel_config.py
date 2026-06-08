"""Fetch and parse kernel defconfig for a given target/version."""
from __future__ import annotations

import time
import urllib.request
from typing import Optional

from fastapi import APIRouter, HTTPException

router = APIRouter()

# ── cache ──────────────────────────────────────────────────────────────────
_CACHE: dict[str, tuple[float, dict]] = {}
_TTL = 3600


def _cached(key: str, fetch_fn) -> dict:
    now = time.monotonic()
    if key in _CACHE:
        ts, val = _CACHE[key]
        if now - ts < _TTL:
            return val
    val = fetch_fn()
    _CACHE[key] = (now, val)
    return val


# ── defconfig URL builders ─────────────────────────────────────────────────

def _defconfig_url(
    kernel_source: str,
    kernel_arch: str,
    defconfig: str,
    branch: Optional[str] = None,
    version: Optional[str] = None,
) -> str:
    if kernel_source == "rpi":
        br = branch or "rpi-6.12.y"
        arch_dir = "arm64" if kernel_arch == "arm64" else kernel_arch
        return (
            f"https://raw.githubusercontent.com/raspberrypi/linux/"
            f"{br}/arch/{arch_dir}/configs/{defconfig}"
        )
    # mainline
    ver = version or "6.12.27"
    # strip patch part for tag lookup: 6.12.27 -> v6.12.27
    tag = f"v{ver}"
    if kernel_arch in ("x86", "x86_64"):
        arch_dir = "x86"
    else:
        arch_dir = kernel_arch
    return (
        f"https://raw.githubusercontent.com/torvalds/linux/"
        f"{tag}/arch/{arch_dir}/configs/{defconfig}"
    )


# ── parser ─────────────────────────────────────────────────────────────────

def _parse_defconfig(text: str) -> dict[str, str]:
    """Return {CONFIG_KEY: 'y'|'m'|'n'|<value>} for all entries."""
    result: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("# CONFIG_") and line.endswith(" is not set"):
            key = line[2:].split(" ")[0]   # CONFIG_FOO
            result[key] = "n"
        elif line.startswith("CONFIG_") and "=" in line:
            key, _, val = line.partition("=")
            result[key.strip()] = val.strip()
    return result


def _fetch_defconfig(url: str) -> dict:
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "netos-configurator/1.0"}
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            text = r.read().decode()
        parsed = _parse_defconfig(text)
        return {"ok": True, "url": url, "config": parsed, "total": len(parsed)}
    except Exception as exc:
        return {"ok": False, "url": url, "config": {}, "error": str(exc)}


# ── target metadata (mirrors targets.py, avoid circular import) ────────────

_TARGET_META: dict[str, dict] = {
    "pi5":       {"source": "rpi",      "arch": "arm64",   "defconfig": "bcm2712_defconfig"},
    "zero2w":    {"source": "rpi",      "arch": "arm64",   "defconfig": "bcm2711_defconfig"},
    "pi4":       {"source": "rpi",      "arch": "arm64",   "defconfig": "bcm2711_defconfig"},
    "qemu-x86":  {"source": "mainline", "arch": "x86",     "defconfig": "x86_64_defconfig"},
    "qemu-virt": {"source": "mainline", "arch": "arm64",   "defconfig": "defconfig"},
    "qemu-wifi": {"source": "mainline", "arch": "arm64",   "defconfig": "defconfig"},
}


# ── endpoint ───────────────────────────────────────────────────────────────

@router.get("/kernel-config/defconfig")
def get_defconfig(
    target: str = "zero2w",
    branch: str = "",
    version: str = "",
) -> dict:
    """Return parsed defconfig for target.

    ``branch``  — RPi branch, e.g. ``rpi-6.12.y``
    ``version`` — mainline version, e.g. ``6.12.27``
    """
    meta = _TARGET_META.get(target)
    if not meta:
        raise HTTPException(status_code=404, detail=f"Unknown target: {target}")

    url = _defconfig_url(
        kernel_source=meta["source"],
        kernel_arch=meta["arch"],
        defconfig=meta["defconfig"],
        branch=branch or None,
        version=version or None,
    )

    cache_key = url
    result = _cached(cache_key, lambda: _fetch_defconfig(url))
    return result
