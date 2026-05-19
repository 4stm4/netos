from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]

from src.configurator.models import Profile

router = APIRouter()

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
PROFILES_DIR = PROJECT_ROOT / "profiles"


def _ensure_profiles_dir():
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)


def _profile_path(name: str) -> Path:
    return PROFILES_DIR / f"{name}.yaml"


def _load_profile(name: str) -> Profile:
    path = _profile_path(name)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Profile '{name}' not found")
    if yaml is None:
        raise RuntimeError("PyYAML is not installed")
    with path.open() as f:
        data = yaml.safe_load(f)
    return Profile(**data)


def _save_profile(profile: Profile) -> None:
    _ensure_profiles_dir()
    path = _profile_path(profile.name)
    if yaml is None:
        raise RuntimeError("PyYAML is not installed")
    with path.open("w") as f:
        yaml.safe_dump(profile.model_dump(), f, allow_unicode=True, sort_keys=False)


@router.get("/profiles")
def list_profiles() -> list[dict[str, Any]]:
    _ensure_profiles_dir()
    result = []
    for p in sorted(PROFILES_DIR.glob("*.yaml")):
        name = p.stem
        try:
            profile = _load_profile(name)
            result.append({
                "name": profile.name,
                "target": profile.target,
                "version": profile.branding.version,
            })
        except Exception:
            result.append({"name": name, "target": "unknown", "version": "?"})
    return result


@router.get("/profiles/{name}")
def get_profile(name: str) -> dict[str, Any]:
    profile = _load_profile(name)
    return profile.model_dump()


@router.put("/profiles/{name}")
def put_profile(name: str, data: dict[str, Any]) -> dict[str, Any]:
    # Ensure the name in the URL is canonical
    data["name"] = name
    try:
        profile = Profile(**data)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _save_profile(profile)
    return profile.model_dump()


@router.delete("/profiles/{name}")
def delete_profile(name: str) -> dict[str, str]:
    path = _profile_path(name)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Profile '{name}' not found")
    path.unlink()
    return {"deleted": name}


@router.post("/profiles/{name}/dry-run", response_class=PlainTextResponse)
def dry_run(name: str) -> str:
    """Return the generated defconfig text without actually building."""
    profile = _load_profile(name)

    # Import builder and resolve target
    import sys
    sys.path.insert(0, str(PROJECT_ROOT / "src"))
    from src.targets import get_target
    from src.adapters.netos_buildroot import NetOSBuildrootBuilder

    try:
        target = get_target(profile.target)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Apply branding env vars so the defconfig picks them up
    import os
    from src.configurator.profile_map import profile_to_env
    env_vars = profile_to_env(profile)
    old_env = {}
    for k, v in env_vars.items():
        old_env[k] = os.environ.get(k)
        os.environ[k] = v

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            builder = NetOSBuildrootBuilder(
                rootfs_path=tmp_path / "rootfs",
                temp_path=tmp_path,
                target=target,
                extra_packages=profile.packages.custom,
            )
            # Only write the external tree (generates the defconfig file)
            builder._write_external_tree()
            defconfig_path = (
                tmp_path
                / "netos-buildroot-external"
                / "configs"
                / builder.defconfig_name
            )
            return defconfig_path.read_text()
    finally:
        # Restore env
        for k, v in old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
