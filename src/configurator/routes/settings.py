"""Global server settings — persistent across restarts via .netos_settings.json."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

from src.configurator.build_runner import PROJECT_ROOT, get_builds_dir, set_builds_dir

router = APIRouter()

_SETTINGS_FILE = PROJECT_ROOT / ".netos_settings.json"


def _load_settings() -> dict:
    if _SETTINGS_FILE.exists():
        try:
            return json.loads(_SETTINGS_FILE.read_text())
        except Exception:
            pass
    return {}


def _save_settings(data: dict) -> None:
    _SETTINGS_FILE.write_text(json.dumps(data, indent=2))


def apply_saved_settings() -> None:
    """Called at app startup to restore persisted settings."""
    s = _load_settings()
    if "builds_dir" in s and s["builds_dir"]:
        set_builds_dir(s["builds_dir"])


class Settings(BaseModel):
    builds_dir: str = ""


@router.get("/settings")
def get_settings() -> dict:
    s = _load_settings()
    return {
        "builds_dir": s.get("builds_dir", ""),
        "builds_dir_effective": str(get_builds_dir()),
    }


@router.post("/settings")
def save_settings(body: Settings) -> dict:
    s = _load_settings()
    if body.builds_dir:
        s["builds_dir"] = body.builds_dir
        set_builds_dir(body.builds_dir)
    else:
        s.pop("builds_dir", None)
        # reset to env-var / default
        from src.configurator.build_runner import PROJECT_ROOT
        import os
        default = Path(os.environ.get("NETOS_BUILDS_DIR", str(PROJECT_ROOT / "builds")))
        set_builds_dir(default)
    _save_settings(s)
    return {
        "builds_dir": s.get("builds_dir", ""),
        "builds_dir_effective": str(get_builds_dir()),
    }
