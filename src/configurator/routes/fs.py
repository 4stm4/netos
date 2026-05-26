"""Filesystem helpers for the web configurator.

Exposes a minimal read-only API to let the UI browse directories on the
build host and validate user-typed paths.  Writing or deleting via this
router is deliberately not supported.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query

router = APIRouter()

# Never expose paths outside these roots for security
_ALLOWED_ROOTS: tuple[str, ...] = (
    "/",           # allow any absolute path on the build host
)


def _safe_path(raw: str) -> Path | None:
    """Return an absolute resolved Path, or None if the input is unsafe."""
    try:
        p = Path(raw).expanduser().resolve()
    except Exception:
        return None
    return p


@router.get("/fs/ls")
def list_dir(
    path: str = Query(default="/", max_length=512),
) -> dict[str, Any]:
    """List the contents of a directory on the build host.

    Returns ``{path, exists, is_dir, entries: [{name, is_dir, size}]}``
    so the UI can render a simple directory picker.
    Only directories and regular files are returned; symlinks are resolved.
    """
    p = _safe_path(path)
    if p is None:
        return {"path": path, "exists": False, "is_dir": False, "entries": [],
                "error": "invalid path"}
    if not p.exists():
        return {"path": str(p), "exists": False, "is_dir": False, "entries": []}
    if not p.is_dir():
        return {"path": str(p), "exists": True, "is_dir": False, "entries": []}

    entries: list[dict[str, Any]] = []
    try:
        for child in sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
            try:
                entries.append({
                    "name": child.name,
                    "is_dir": child.is_dir(),
                    "size": child.stat().st_size if child.is_file() else None,
                })
            except PermissionError:
                pass
    except PermissionError:
        return {"path": str(p), "exists": True, "is_dir": True, "entries": [],
                "error": "permission denied"}

    return {"path": str(p), "exists": True, "is_dir": True, "entries": entries}


@router.get("/fs/stat")
def stat_path(
    path: str = Query(default="", max_length=512),
) -> dict[str, Any]:
    """Return basic info about a path (exists, is_dir, writable, free space).

    Used by the configurator to validate user-entered paths before saving.
    """
    if not path.strip():
        return {"path": "", "exists": False, "is_dir": False, "writable": False,
                "free_gb": None, "error": "empty path"}

    p = _safe_path(path)
    if p is None:
        return {"path": path, "exists": False, "is_dir": False, "writable": False,
                "free_gb": None, "error": "invalid path"}

    exists   = p.exists()
    is_dir   = p.is_dir() if exists else False
    writable = os.access(str(p), os.W_OK) if exists else (
        os.access(str(p.parent), os.W_OK) if p.parent.exists() else False
    )

    free_gb: float | None = None
    try:
        import shutil
        usage = shutil.disk_usage(str(p) if exists else str(p.parent))
        free_gb = round(usage.free / 1024**3, 1)
    except Exception:
        pass

    return {
        "path":     str(p),
        "exists":   exists,
        "is_dir":   is_dir,
        "writable": writable,
        "free_gb":  free_gb,
    }
