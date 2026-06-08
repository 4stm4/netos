"""Kernel version catalogue — fetches live data from kernel.org and GitHub."""
from __future__ import annotations

import re
import time
import urllib.request
import json as _json
from typing import Any

from fastapi import APIRouter

router = APIRouter()

# ── simple in-process cache ────────────────────────────────────────────────
_CACHE: dict[str, tuple[float, Any]] = {}
_TTL = 3600  # 1 hour


def _cached(key: str, fetch_fn):
    now = time.monotonic()
    if key in _CACHE:
        ts, val = _CACHE[key]
        if now - ts < _TTL:
            return val
    val = fetch_fn()
    _CACHE[key] = (now, val)
    return val


# ── mainline (kernel.org) ──────────────────────────────────────────────────

def _fetch_mainline() -> list[dict]:
    url = "https://www.kernel.org/releases.json"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "netos-configurator/1.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = _json.loads(r.read())
        releases = []
        for rel in data.get("releases", []):
            releases.append({
                "version":  rel["version"],
                "moniker":  rel["moniker"],      # stable / longterm / mainline / linux-next
                "iseol":    rel.get("iseol", False),
                "released": rel.get("released", {}).get("isodate", ""),
                "eol":      rel.get("eol", ""),
            })
        return releases
    except Exception as exc:
        # fallback: well-known LTS + stable versions
        return _MAINLINE_FALLBACK


_MAINLINE_FALLBACK = [
    {"version": "6.12.27", "moniker": "stable",   "iseol": False, "released": "2025-04-16", "eol": "2026-01"},
    {"version": "6.6.87",  "moniker": "longterm",  "iseol": False, "released": "2025-04-09", "eol": "2026-12"},
    {"version": "6.1.133", "moniker": "longterm",  "iseol": False, "released": "2025-04-09", "eol": "2028-01"},
    {"version": "5.15.179","moniker": "longterm",  "iseol": False, "released": "2025-04-09", "eol": "2026-10"},
    {"version": "5.10.236","moniker": "longterm",  "iseol": False, "released": "2025-04-09", "eol": "2026-12"},
    {"version": "5.4.292", "moniker": "longterm",  "iseol": False, "released": "2025-04-09", "eol": "2025-12"},
    {"version": "4.19.330","moniker": "longterm",  "iseol": False, "released": "2025-04-09", "eol": "2024-12"},
    {"version": "4.14.x",  "moniker": "longterm",  "iseol": True,  "released": "2017-11-12", "eol": "2024-01"},
    {"version": "4.9.x",   "moniker": "longterm",  "iseol": True,  "released": "2016-12-11", "eol": "2023-01"},
    {"version": "4.4.x",   "moniker": "longterm",  "iseol": True,  "released": "2016-01-10", "eol": "2022-02"},
]


# ── RPi branches (github.com/raspberrypi/linux) ────────────────────────────

_RPI_BRANCH_RE = re.compile(r"^rpi-(\d+)\.(\d+)\.y$")


def _fetch_rpi() -> list[dict]:
    url = "https://api.github.com/repos/raspberrypi/linux/branches?per_page=100"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "netos-configurator/1.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = _json.loads(r.read())
        branches = []
        for b in data:
            name = b["name"]
            m = _RPI_BRANCH_RE.match(name)
            if m:
                major, minor = int(m.group(1)), int(m.group(2))
                branches.append({"branch": name, "major": major, "minor": minor})
        branches.sort(key=lambda x: (x["major"], x["minor"]), reverse=True)
        # annotate LTS
        _LTS_MINORS = {(6, 12), (6, 6), (6, 1), (5, 15), (5, 10), (5, 4), (4, 19)}
        result = []
        for b in branches:
            lts = (b["major"], b["minor"]) in _LTS_MINORS
            result.append({
                "branch":  b["branch"],
                "version": f"{b['major']}.{b['minor']}",
                "lts":     lts,
                "major":   b["major"],
                "minor":   b["minor"],
            })
        return result
    except Exception:
        return _RPI_FALLBACK


_RPI_FALLBACK = [
    {"branch": "rpi-6.12.y", "version": "6.12", "lts": True,  "major": 6, "minor": 12},
    {"branch": "rpi-6.6.y",  "version": "6.6",  "lts": True,  "major": 6, "minor": 6},
    {"branch": "rpi-6.1.y",  "version": "6.1",  "lts": True,  "major": 6, "minor": 1},
    {"branch": "rpi-5.15.y", "version": "5.15", "lts": True,  "major": 5, "minor": 15},
    {"branch": "rpi-5.10.y", "version": "5.10", "lts": True,  "major": 5, "minor": 10},
    {"branch": "rpi-5.4.y",  "version": "5.4",  "lts": False, "major": 5, "minor": 4},
    {"branch": "rpi-4.19.y", "version": "4.19", "lts": False, "major": 4, "minor": 19},
]


# ── endpoints ──────────────────────────────────────────────────────────────

@router.get("/kernel-versions")
def get_kernel_versions(source: str = "mainline") -> dict:
    """Return available kernel versions.

    *source* = ``"mainline"`` → kernel.org releases
    *source* = ``"rpi"``      → raspberrypi/linux branches
    """
    if source == "rpi":
        return {
            "source": "rpi",
            "default_branch": "rpi-6.12.y",
            "branches": _cached("rpi", _fetch_rpi),
        }
    # mainline
    return {
        "source": "mainline",
        "default_version": "6.12.27",
        "releases": _cached("mainline", _fetch_mainline),
    }
