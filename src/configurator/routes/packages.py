from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]

router = APIRouter()

_PACKAGES_YAML = Path(__file__).parent.parent / "packages.yaml"


def _load_packages() -> dict:
    if yaml is None:
        # Minimal YAML parser fallback is not needed — PyYAML is in requirements
        raise RuntimeError("PyYAML is not installed. Run: pip install pyyaml")
    with _PACKAGES_YAML.open() as f:
        return yaml.safe_load(f)


@router.get("/packages")
def get_packages():
    """Return the full packages catalogue grouped by category."""
    return _load_packages()
