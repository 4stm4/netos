from __future__ import annotations

from fastapi import APIRouter

from src.configurator.presets import PRESETS

router = APIRouter()


@router.get("/presets")
def list_presets() -> list[dict]:
    """Return all built-in profile presets."""
    return PRESETS


@router.get("/presets/{preset_id}")
def get_preset(preset_id: str) -> dict:
    for p in PRESETS:
        if p["id"] == preset_id:
            return p
    from fastapi import HTTPException
    raise HTTPException(status_code=404, detail=f"Preset '{preset_id}' not found")
