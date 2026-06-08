"""Kernel CONFIG_* catalog API."""
from __future__ import annotations

from pathlib import Path

import yaml
from fastapi import APIRouter

router = APIRouter()

_CATALOG_FILE = Path(__file__).parent.parent / "kernel_catalog.yaml"
_catalog: dict | None = None


def _load() -> dict:
    global _catalog
    if _catalog is None:
        _catalog = yaml.safe_load(_CATALOG_FILE.read_text())
    return _catalog


@router.get("/kernel-catalog/{section}")
def get_kernel_catalog(section: str) -> list:
    """Return catalog for section: options | modules | drivers."""
    data = _load()
    return data.get(section, [])
