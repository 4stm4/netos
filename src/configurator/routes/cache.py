from __future__ import annotations

import hashlib
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from src.targets import TARGETS

router = APIRouter()

_PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
_TEMP_PATH    = _PROJECT_ROOT / "temp"
_HASH_FILE    = ".last_toolchain_hash"

# Опции toolchain — если они изменились, нужна чистка toolchain
_TOOLCHAIN_KEYS = {
    "BR2_TOOLCHAIN_BUILDROOT_GLIBC",
    "BR2_TOOLCHAIN_BUILDROOT_CXX",
    "BR2_aarch64",
    "BR2_x86_64",
    "BR2_arm",
}


def _output_dir(target: str) -> Path:
    return _TEMP_PATH / f"buildroot-output-{target}"


def _toolchain_cross_prefix(target: str) -> str:
    from src.targets import TARGETS
    t = TARGETS.get(target)
    if t is None:
        return "aarch64-buildroot-linux-gnu"
    arch = t.buildroot_arch  # aarch64 | x86_64
    return f"{arch}-buildroot-linux-gnu"


def _dir_size_gb(path: Path) -> float:
    """Подсчёт размера через du -sk (1K-блоки, быстрее чем --block-size=1)."""
    import subprocess
    try:
        out = subprocess.check_output(
            ["du", "-sk", str(path)],
            timeout=60,
            stderr=subprocess.DEVNULL,
        )
        kb = int(out.split()[0])
        return round(kb / 1024**2, 2)  # KB → GB
    except Exception:
        return 0.0


def _disk_info(path: Path) -> dict[str, float]:
    usage = shutil.disk_usage(path if path.exists() else path.parent)
    return {
        "total_gb": round(usage.total / 1024**3, 1),
        "used_gb":  round(usage.used  / 1024**3, 1),
        "free_gb":  round(usage.free  / 1024**3, 1),
        "path":     str(path),
    }


def _compute_defconfig_hash(target: str) -> str:
    """Хэш toolchain-параметров цели для обнаружения изменений конфига."""
    t = TARGETS.get(target)
    if t is None:
        return ""
    # Собираем только toolchain-значимые поля напрямую из TargetConfig
    parts = [
        f"arch={t.buildroot_arch}",
        f"kernel_source={t.kernel_source}",
        f"kernel_arch={t.kernel_arch}",
        f"cross_compile={t.cross_compile}",
    ]
    return hashlib.md5("\n".join(parts).encode()).hexdigest()


def _saved_hash(output_dir: Path) -> str:
    p = output_dir / _HASH_FILE
    return p.read_text().strip() if p.exists() else ""


def _save_hash(output_dir: Path, h: str) -> None:
    (output_dir / _HASH_FILE).write_text(h)


@router.get("/cache/{target}")
def get_cache_status(target: str) -> dict[str, Any]:
    if target not in TARGETS:
        raise HTTPException(status_code=404, detail=f"Unknown target: {target}")

    t         = TARGETS[target]
    out_dir   = _output_dir(target)
    image_path = _PROJECT_ROOT / t.image_name

    # Диск
    disk_root = _TEMP_PATH if _TEMP_PATH.exists() else _PROJECT_ROOT
    disk = _disk_info(disk_root)

    # Output dir (размер не считаем — слишком долго на большом дереве Buildroot)
    out_exists  = out_dir.exists()
    out_size_gb = None
    out_mtime   = (
        datetime.fromtimestamp(out_dir.stat().st_mtime, tz=timezone.utc).isoformat()
        if out_exists else None
    )

    # Toolchain
    prefix  = _toolchain_cross_prefix(target)
    gpp_bin = out_dir / "host" / "bin" / f"{prefix}-g++"
    gcc_bin = out_dir / "host" / "bin" / f"{prefix}-gcc"
    tc_ok   = gcc_bin.exists()
    cxx_ok  = gpp_bin.exists()
    tc_mtime = (
        datetime.fromtimestamp(gcc_bin.stat().st_mtime, tz=timezone.utc).isoformat()
        if tc_ok else None
    )

    # Stale detection
    # Смотрим наличие stamp-файлов gcc-final (.stamp_built) и виртуальных пакетов.
    # Если built-стамп gcc-final есть, но g++ отсутствует — нужна чистка toolchain.
    import glob as _glob
    _TC_VIRTUAL_DIRS = ["toolchain-buildroot", "toolchain-buildroot-aux", "toolchain-buildroot-initial"]
    _gcc_final_built = bool(out_exists and any(
        Path(p).exists()
        for p in _glob.glob(str(out_dir / "build" / "host-gcc-final-*" / ".stamp_built"))
    ))
    tc_stamps_exist = out_exists and (
        _gcc_final_built or
        any((out_dir / "build" / d).exists() for d in _TC_VIRTUAL_DIRS)
    )
    current_hash = _compute_defconfig_hash(target)
    saved_hash   = _saved_hash(out_dir)
    config_stale = bool(saved_hash and current_hash and current_hash != saved_hash)
    needs_tc_clean = config_stale or (tc_stamps_exist and not cxx_ok)
    stale_reason = ""
    if config_stale:
        stale_reason = "Toolchain-конфиг изменился с последней сборки"
    elif tc_stamps_exist and not cxx_ok:
        stale_reason = "g++ не найден — toolchain собран без BR2_TOOLCHAIN_BUILDROOT_CXX"

    # Image
    img_exists  = image_path.exists()
    img_size_mb = round(image_path.stat().st_size / 1024**2) if img_exists else 0
    img_mtime   = (
        datetime.fromtimestamp(image_path.stat().st_mtime, tz=timezone.utc).isoformat()
        if img_exists else None
    )

    return {
        "target":   target,
        "disk":     disk,
        "output": {
            "exists":   out_exists,
            "path":     str(out_dir),
            "size_gb":  out_size_gb,
            "mtime":    out_mtime,
        },
        "toolchain": {
            "ok":       tc_ok,
            "cxx_ok":   cxx_ok,
            "mtime":    tc_mtime,
        },
        "image": {
            "exists":   img_exists,
            "path":     str(image_path),
            "size_mb":  img_size_mb,
            "mtime":    img_mtime,
        },
        "config_stale": needs_tc_clean,
        "stale_reason": stale_reason,
    }


class CleanRequest(BaseModel):
    mode: str  # "toolchain" | "full" | "image"


@router.post("/cache/{target}/clean")
def clean_cache(target: str, req: CleanRequest) -> dict[str, Any]:
    if target not in TARGETS:
        raise HTTPException(status_code=404, detail=f"Unknown target: {target}")
    if req.mode not in ("toolchain", "full", "image"):
        raise HTTPException(status_code=422, detail="mode must be toolchain|full|image")

    t          = TARGETS[target]
    out_dir    = _output_dir(target)
    image_path = _PROJECT_ROOT / t.image_name
    freed_gb   = 0.0

    if req.mode == "image":
        if image_path.exists():
            freed_gb = round(image_path.stat().st_size / 1024**3, 2)
            image_path.unlink()
        return {"ok": True, "freed_gb": freed_gb, "mode": "image"}

    if req.mode == "toolchain":
        if out_dir.exists():
            prefix  = _toolchain_cross_prefix(target)
            build_dir = out_dir / "build"

            # 1. Виртуальные пакеты toolchain-buildroot (зависимости gcc-final)
            for d in ["toolchain-buildroot", "toolchain-buildroot-aux", "toolchain-buildroot-initial"]:
                stamp_dir = build_dir / d
                if stamp_dir.exists():
                    shutil.rmtree(stamp_dir)

            # 2. host-gcc-final — именно здесь компилируется g++.
            #    Удаляем стампы built/configured/host_installed чтобы Buildroot
            #    пересконфигурировал GCC с --enable-languages=c,c++ и пересобрал.
            import glob as _glob
            for gcc_dir in _glob.glob(str(build_dir / "host-gcc-final-*")):
                for stamp in ["built", "configured", "host_installed", "installed",
                              "staging_installed", "target_installed"]:
                    p = Path(gcc_dir) / f".stamp_{stamp}"
                    if p.exists():
                        p.unlink()

            # 3. Удаляем g++ и c++ из host/bin
            for suffix in ["-g++", "-c++"]:
                b = out_dir / "host" / "bin" / f"{prefix}{suffix}"
                if b.exists():
                    b.unlink()

            # 4. Удаляем сохранённый хэш конфига
            hash_file = out_dir / _HASH_FILE
            if hash_file.exists():
                hash_file.unlink()
        return {"ok": True, "freed_gb": round(freed_gb, 2), "mode": "toolchain"}

    if req.mode == "full":
        if out_dir.exists():
            freed_gb = 0.0  # du слишком долго, не считаем
            shutil.rmtree(out_dir)
        if image_path.exists():
            freed_gb += round(image_path.stat().st_size / 1024**3, 2)
            image_path.unlink()
        return {"ok": True, "freed_gb": round(freed_gb, 2), "mode": "full"}


@router.post("/cache/{target}/save-hash")
def save_cache_hash(target: str) -> dict[str, Any]:
    """Вызывается после успешной сборки, сохраняет хэш конфига toolchain."""
    if target not in TARGETS:
        raise HTTPException(status_code=404, detail=f"Unknown target: {target}")
    out_dir = _output_dir(target)
    if not out_dir.exists():
        return {"ok": False, "reason": "output_dir not found"}
    h = _compute_defconfig_hash(target)
    _save_hash(out_dir, h)
    return {"ok": True, "hash": h}


# ---------------------------------------------------------------------------
# Artifact cache (M3 toolchains / M5 rootfs archives)
# ---------------------------------------------------------------------------

_ARTIFACT_CACHE_ROOT = _TEMP_PATH / "cache"
_ARTIFACT_DIRS = ("toolchains", "rootfs")


def _artifact_cache_dir(subdir: str) -> Path:
    return _ARTIFACT_CACHE_ROOT / subdir


@router.get("/artifact-cache/stats")
def artifact_cache_stats() -> dict[str, Any]:
    """Статистика артефактного кэша — toolchains/ и rootfs/ архивы."""
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    from netos_build.cache_eviction import CacheEvictor

    result: dict[str, Any] = {}
    for subdir in _ARTIFACT_DIRS:
        d = _artifact_cache_dir(subdir)
        s = CacheEvictor(d).stats()
        result[subdir] = s
    return result


class EvictRequest(BaseModel):
    dir: str               # "toolchains" | "rootfs" | "all"
    max_size_mb:  float | None = None
    max_age_days: float | None = None
    max_entries:  int   | None = None
    dry_run: bool = False


@router.post("/artifact-cache/evict")
def artifact_cache_evict(req: EvictRequest) -> dict[str, Any]:
    """Запустить вытеснение по заданной политике."""
    if req.dir not in _ARTIFACT_DIRS and req.dir != "all":
        raise HTTPException(status_code=422, detail=f"dir must be one of {_ARTIFACT_DIRS} or 'all'")

    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    from netos_build.cache_eviction import CacheEvictor

    dirs_to_evict = list(_ARTIFACT_DIRS) if req.dir == "all" else [req.dir]
    total_deleted = 0
    total_freed_mb = 0.0
    details: dict[str, Any] = {}

    for subdir in dirs_to_evict:
        d = _artifact_cache_dir(subdir)
        ev = CacheEvictor(
            d,
            max_size_mb  = req.max_size_mb,
            max_age_days = req.max_age_days,
            max_entries  = req.max_entries,
        )
        deleted = ev.evict(dry_run=req.dry_run)
        freed_mb = sum(p.stat().st_size for p in deleted if p.exists()) / 1e6 if not req.dry_run else 0.0
        total_deleted  += len(deleted)
        total_freed_mb += freed_mb
        details[subdir] = {"deleted": len(deleted), "freed_mb": round(freed_mb, 1)}

    return {
        "ok": True,
        "dry_run": req.dry_run,
        "total_deleted": total_deleted,
        "total_freed_mb": round(total_freed_mb, 1),
        "details": details,
    }


@router.delete("/artifact-cache/{subdir}/{key}")
def artifact_cache_delete_entry(subdir: str, key: str) -> dict[str, Any]:
    """Удалить одну запись из артефактного кэша по ключу."""
    import json as _json

    if subdir not in _ARTIFACT_DIRS:
        raise HTTPException(status_code=422, detail=f"subdir must be one of {_ARTIFACT_DIRS}")

    d = _artifact_cache_dir(subdir)
    if not d.exists():
        raise HTTPException(status_code=404, detail="cache dir not found")

    # Find archive files matching the key
    deleted_files: list[str] = []
    for pattern in ("*.tar.gz", "*.rootfs.tar.gz"):
        for p in d.glob(pattern):
            stem = p.name.replace(".rootfs.tar.gz", "").replace(".tar.gz", "")
            if stem == key:
                p.unlink(missing_ok=True)
                deleted_files.append(p.name)

    if not deleted_files:
        raise HTTPException(status_code=404, detail=f"archive for key '{key}' not found")

    # Update index.json
    index_path = d / "index.json"
    if index_path.exists():
        try:
            idx = _json.loads(index_path.read_text())
            idx.pop(key, None)
            index_path.write_text(_json.dumps(idx, indent=2, ensure_ascii=False))
        except Exception:
            pass

    return {"ok": True, "deleted": deleted_files}
