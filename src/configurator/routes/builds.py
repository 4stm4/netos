from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from src.configurator.build_runner import (
    get_build,
    list_builds,
    start_build,
    stream_events,
)
from src.configurator.models import Profile
from src.configurator.profile_map import profile_to_env
from src.configurator.routes.profiles import _load_profile

router = APIRouter()


@router.get("/builds")
def get_builds() -> list[dict[str, Any]]:
    return list_builds()


@router.get("/builds/{build_id}")
def get_build_info(build_id: str) -> dict[str, Any]:
    state = get_build(build_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Build not found")
    return {
        "build_id": state.build_id,
        "target": state.target,
        "status": state.status,
        "stage": state.stage,
        "log_lines": state.log_lines,
    }


@router.post("/profiles/{name}/build")
async def start_build_for_profile(name: str) -> dict[str, str]:
    profile = _load_profile(name)
    env   = profile_to_env(profile)
    extra = profile.packages.extra_packages()   # enabled keys + custom raw lines
    build_id = start_build(
        target=profile.target,
        env_override=env,
        extra_packages=extra,
    )
    return {"build_id": build_id, "target": profile.target}


@router.post("/builds/start")
async def start_build_inline(profile_data: dict[str, Any]) -> dict[str, str]:
    """Start a build from an inline profile (not yet saved to disk)."""
    try:
        profile = Profile(**profile_data)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    env   = profile_to_env(profile)
    extra = profile.packages.extra_packages()   # enabled keys + custom raw lines
    build_id = start_build(
        target=profile.target,
        env_override=env,
        extra_packages=extra,
    )
    return {"build_id": build_id, "target": profile.target}


@router.get("/builds/{build_id}/events")
async def build_events(build_id: str) -> StreamingResponse:
    """SSE stream for a running or completed build."""
    state = get_build(build_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Build not found")

    async def event_generator():
        async for chunk in stream_events(build_id):
            yield chunk

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
