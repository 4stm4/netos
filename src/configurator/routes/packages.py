from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]

router = APIRouter()

_PACKAGES_YAML = Path(__file__).parent.parent / "packages.yaml"
_BUILDROOT_PY = Path(__file__).parent.parent.parent / "adapters" / "netos_buildroot.py"

_BR2_PKG_RE = re.compile(r'"(BR2_PACKAGE_[A-Z0-9_]+)=y"')


def _load_packages() -> dict:
    if yaml is None:
        raise RuntimeError("PyYAML is not installed. Run: pip install pyyaml")
    with _PACKAGES_YAML.open() as f:
        return yaml.safe_load(f)


def _parse_default_packages() -> list[str]:
    """Extract BR2_PACKAGE_*=y keys from the _defconfig() method in netos_buildroot.py.

    Parses the source file statically — no import needed.
    """
    src = _BUILDROOT_PY.read_text()
    # Only scan inside _defconfig method body
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
