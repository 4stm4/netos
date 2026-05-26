from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]

router = APIRouter()

_PACKAGES_YAML = Path(__file__).parent.parent / "packages.yaml"
_BR2_PKG_JSON  = Path(__file__).parent.parent / "br2_packages.json"
_BUILDROOT_PY  = Path(__file__).parent.parent.parent / "adapters" / "netos_buildroot.py"

_BR2_PKG_RE = re.compile(r'"(BR2_PACKAGE_[A-Z0-9_]+)=y"')

_br2_pkg_cache: list[dict[str, str]] | None = None


def _load_packages() -> dict:
    if yaml is None:
        raise RuntimeError("PyYAML is not installed. Run: pip install pyyaml")
    with _PACKAGES_YAML.open() as f:
        return yaml.safe_load(f)


def _load_br2_packages() -> list[dict[str, str]]:
    global _br2_pkg_cache
    if _br2_pkg_cache is None:
        _br2_pkg_cache = json.loads(_BR2_PKG_JSON.read_text())
    return _br2_pkg_cache


def _parse_default_packages() -> list[str]:
    """Extract BR2_PACKAGE_*=y keys from the _defconfig() method in netos_buildroot.py."""
    src = _BUILDROOT_PY.read_text()
    m = re.search(r"def _defconfig\(self\)(.*?)^\s{4}def ", src, re.DOTALL | re.MULTILINE)
    body = m.group(1) if m else src
    return _BR2_PKG_RE.findall(body)


@router.get("/packages")
def get_packages():
    """Return the full packages catalogue grouped by category."""
    return _load_packages()


@router.get("/defaults")
def get_defaults():
    """Return BR2_PACKAGE keys that are enabled in the default netOS build."""
    return {"keys": _parse_default_packages()}


def _search_br2(q: str, limit: int = 20) -> list[dict[str, Any]]:
    """Core search logic — usable both from FastAPI and tests."""
    pkgs = _load_br2_packages()
    q_lower = q.strip().lower()
    if not q_lower:
        return sorted(pkgs, key=lambda p: p["name"])[:limit]

    seen: set[str] = set()
    results: list[dict[str, Any]] = []

    def _add(p: dict) -> None:
        if p["key"] not in seen:
            seen.add(p["key"])
            results.append(p)

    # 1. Exact name prefix (highest priority)
    for p in pkgs:
        if p["name"].lower().startswith(q_lower):
            _add(p)
    # 2. Key suffix prefix (BR2_PACKAGE_ stripped)
    suffix_q = q_lower.upper()
    for p in pkgs:
        if p["key"][len("BR2_PACKAGE_"):].startswith(suffix_q):
            _add(p)
    # 3. Any substring anywhere
    for p in pkgs:
        if (q_lower in p["name"].lower()
                or q_lower in p["key"].lower()
                or q_lower in p["desc"].lower()):
            _add(p)

    return results[:limit]


@router.get("/packages/search")
def search_packages(
    q: str = Query(default="", min_length=0, max_length=80),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[dict[str, Any]]:
    """Search the bundled Buildroot package list.

    Returns packages whose key, name, or description contains *q* (case-insensitive).
    An empty query returns the first *limit* packages sorted by name.
    Priority: exact name prefix → key suffix prefix → substring anywhere.
    """
    return _search_br2(q, limit)
