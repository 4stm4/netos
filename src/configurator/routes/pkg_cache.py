"""Package & kernel pre-cache manager.

Endpoints
---------
GET  /api/pkg-cache/status          — overview: buildroot version, sizes, kernel status
GET  /api/pkg-cache/packages        — list packages already in dl cache
POST /api/pkg-cache/fetch-package   — start background download of a package into dl cache
GET  /api/pkg-cache/kernels         — list kernel tarballs / extracted sources
POST /api/pkg-cache/fetch-kernel    — start background download of a kernel
GET  /api/pkg-cache/jobs            — list active/recent download jobs
DELETE /api/pkg-cache/packages/{name} — remove a package from dl cache
"""

from __future__ import annotations

import asyncio
import glob
import logging
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.configurator.build_runner import PROJECT_ROOT

logger = logging.getLogger(__name__)
router = APIRouter(tags=["pkg-cache"])

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _buildroot_dl_dir() -> Optional[Path]:
    """Return the first buildroot dl/ directory found under temp/."""
    temp = PROJECT_ROOT / "temp"
    for d in sorted(temp.glob("buildroot-*/dl"), reverse=True):
        if d.is_dir():
            return d
    return None


def _buildroot_version() -> Optional[str]:
    temp = PROJECT_ROOT / "temp"
    # match only versioned dirs like buildroot-2026.02.1, not buildroot-output-*
    import re
    for d in sorted(temp.glob("buildroot-[0-9]*"), reverse=True):
        if re.match(r"buildroot-\d{4}\.\d+", d.name) and d.is_dir():
            return d.name.replace("buildroot-", "")
    return None


def _dir_size(path: Path) -> int:
    """Recursive size in bytes."""
    total = 0
    try:
        for entry in os.scandir(path):
            if entry.is_file(follow_symlinks=False):
                total += entry.stat().st_size
            elif entry.is_dir(follow_symlinks=False):
                total += _dir_size(Path(entry.path))
    except PermissionError:
        pass
    return total


def _fmt_size(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


# ---------------------------------------------------------------------------
# In-memory job registry
# ---------------------------------------------------------------------------

_jobs: dict[str, dict] = {}          # job_id → {status, label, log, started, finished}
_MAX_JOBS = 50


def _new_job(label: str) -> str:
    job_id = uuid.uuid4().hex[:12]
    _jobs[job_id] = {
        "id":       job_id,
        "label":    label,
        "status":   "running",   # running | done | error
        "log":      [],
        "started":  time.time(),
        "finished": None,
    }
    # evict oldest if too many
    if len(_jobs) > _MAX_JOBS:
        oldest = min(_jobs, key=lambda k: _jobs[k]["started"])
        if oldest != job_id:
            del _jobs[oldest]
    return job_id


def _job_log(job_id: str, line: str):
    if job_id in _jobs:
        _jobs[job_id]["log"].append(line)


def _job_done(job_id: str, ok: bool):
    if job_id in _jobs:
        _jobs[job_id]["status"] = "done" if ok else "error"
        _jobs[job_id]["finished"] = time.time()


# ---------------------------------------------------------------------------
# Background download worker
# ---------------------------------------------------------------------------

async def _run_cmd(job_id: str, cmd: list[str], cwd: Optional[Path] = None):
    """Run *cmd* in a subprocess, stream stdout/stderr into job log."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(cwd) if cwd else None,
        )
        assert proc.stdout
        async for raw in proc.stdout:
            line = raw.decode(errors="replace").rstrip()
            _job_log(job_id, line)
        await proc.wait()
        return proc.returncode == 0
    except Exception as exc:
        _job_log(job_id, f"ERROR: {exc}")
        return False


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

class FetchPackageRequest(BaseModel):
    name: str                 # e.g. "openssl"
    version: str              # e.g. "3.3.1"
    url: str                  # direct tarball URL
    filename: Optional[str] = None   # override filename if different from URL basename


class FetchKernelRequest(BaseModel):
    source: str               # "rpi" | "mainline"
    branch: Optional[str] = None     # for rpi: "rpi-6.12.y"
    version: Optional[str] = None    # for mainline: "6.12.27"


@router.get("/pkg-cache/status")
def pkg_cache_status():
    dl_dir = _buildroot_dl_dir()
    br_version = _buildroot_version()
    dl_size = _dir_size(dl_dir) if dl_dir else 0
    pkg_count = 0
    if dl_dir:
        pkg_count = sum(
            1 for d in dl_dir.iterdir()
            if d.is_dir() and not d.name.startswith(".")
        )

    # kernel status
    temp = PROJECT_ROOT / "temp"
    rpi_kernels = [
        {"branch": p.name.replace("rpi_linux-", "").replace(".tar.gz", ""), "path": str(p), "size": _fmt_size(p.stat().st_size)}
        for p in sorted(temp.glob("rpi_linux-*.tar.gz"))
        if p.is_file()
    ]
    mainline_kernels = [
        {"version": p.name.replace("linux-", "").replace(".tar.xz", ""), "path": str(p), "size": _fmt_size(p.stat().st_size)}
        for p in sorted(temp.glob("linux-*.tar.xz"))
        if p.is_file()
    ]
    rpi_extracted = (temp / "rpi_linux").exists() and (temp / "rpi_linux" / "Makefile").exists()
    mainline_extracted = (temp / "mainline_linux").exists() and (temp / "mainline_linux" / "Makefile").exists()

    return {
        "buildroot_version": br_version,
        "dl_dir": str(dl_dir) if dl_dir else None,
        "dl_size": _fmt_size(dl_size),
        "dl_size_bytes": dl_size,
        "package_count": pkg_count,
        "rpi_kernel_tarballs": rpi_kernels,
        "mainline_kernel_tarballs": mainline_kernels,
        "rpi_extracted": rpi_extracted,
        "mainline_extracted": mainline_extracted,
    }


@router.get("/pkg-cache/packages")
def list_packages():
    dl_dir = _buildroot_dl_dir()
    if not dl_dir:
        return {"packages": []}

    result = []
    for pkg_dir in sorted(dl_dir.iterdir()):
        if not pkg_dir.is_dir() or pkg_dir.name.startswith("."):
            continue
        files = []
        for f in pkg_dir.iterdir():
            if f.is_file() and not f.name.startswith("."):
                st = f.stat()
                files.append({
                    "name": f.name,
                    "size": _fmt_size(st.st_size),
                    "size_bytes": st.st_size,
                    "mtime": st.st_mtime,
                })
        result.append({
            "package": pkg_dir.name,
            "files": files,
            "total_size": _fmt_size(sum(fi["size_bytes"] for fi in files)),
        })
    return {"packages": result}


@router.post("/pkg-cache/fetch-package")
async def fetch_package(req: FetchPackageRequest):
    dl_dir = _buildroot_dl_dir()
    if not dl_dir:
        raise HTTPException(status_code=400, detail="Buildroot dl cache directory not found. Run a build first to initialize Buildroot.")

    filename = req.filename or req.url.split("/")[-1].split("?")[0]
    pkg_dir = dl_dir / req.name
    pkg_dir.mkdir(parents=True, exist_ok=True)
    dest = pkg_dir / filename

    label = f"Скачать {req.name}-{req.version}"
    job_id = _new_job(label)

    async def _worker():
        _job_log(job_id, f"Загружаем {req.url}")
        _job_log(job_id, f"Сохраняем в {dest}")
        ok = await _run_cmd(
            job_id,
            ["wget", "-c", "-O", str(dest), "--tries=5", "--timeout=60",
             "--progress=dot:mega", req.url],
        )
        if ok:
            _job_log(job_id, f"✓ Готово: {filename}")
        else:
            _job_log(job_id, "✗ Ошибка скачивания")
            # remove partial file
            if dest.exists() and dest.stat().st_size == 0:
                dest.unlink(missing_ok=True)
        _job_done(job_id, ok)

    asyncio.create_task(_worker())
    return {"job_id": job_id, "label": label, "dest": str(dest)}


@router.get("/pkg-cache/kernels")
def list_kernels():
    temp = PROJECT_ROOT / "temp"
    rpi_tarballs = []
    for p in sorted(temp.glob("rpi_linux-*.tar.gz")):
        if p.is_file():
            st = p.stat()
            branch = p.name.replace("rpi_linux-", "").replace(".tar.gz", "")
            rpi_tarballs.append({
                "type": "rpi", "branch": branch,
                "filename": p.name, "path": str(p),
                "size": _fmt_size(st.st_size), "size_bytes": st.st_size,
                "mtime": st.st_mtime,
            })

    mainline_tarballs = []
    for p in sorted(temp.glob("linux-*.tar.xz")):
        if p.is_file():
            st = p.stat()
            version = p.name.replace("linux-", "").replace(".tar.xz", "")
            mainline_tarballs.append({
                "type": "mainline", "version": version,
                "filename": p.name, "path": str(p),
                "size": _fmt_size(st.st_size), "size_bytes": st.st_size,
                "mtime": st.st_mtime,
            })

    rpi_src = temp / "rpi_linux"
    mainline_src = temp / "mainline_linux"

    def _kernel_ver(src: Path) -> Optional[str]:
        release = src / "include/config/kernel.release"
        if release.exists():
            return release.read_text().strip()
        makefile = src / "Makefile"
        if makefile.exists():
            for line in makefile.read_text().splitlines()[:10]:
                if line.startswith("VERSION") or line.startswith("PATCHLEVEL"):
                    pass
        return None

    return {
        "rpi_tarballs": rpi_tarballs,
        "mainline_tarballs": mainline_tarballs,
        "rpi_extracted": {
            "present": rpi_src.is_dir() and (rpi_src / "Makefile").exists(),
            "version": _kernel_ver(rpi_src) if rpi_src.is_dir() else None,
            "path": str(rpi_src),
        },
        "mainline_extracted": {
            "present": mainline_src.is_dir() and (mainline_src / "Makefile").exists(),
            "version": _kernel_ver(mainline_src) if mainline_src.is_dir() else None,
            "path": str(mainline_src),
        },
    }


@router.post("/pkg-cache/fetch-kernel")
async def fetch_kernel(req: FetchKernelRequest):
    temp = PROJECT_ROOT / "temp"
    temp.mkdir(parents=True, exist_ok=True)

    if req.source == "rpi":
        branch = req.branch or "rpi-6.12.y"
        url = f"https://github.com/raspberrypi/linux/archive/refs/heads/{branch}.tar.gz"
        dest = temp / f"rpi_linux-{branch}.tar.gz"
        label = f"Ядро RPi {branch}"
        job_id = _new_job(label)

        async def _rpi_worker():
            _job_log(job_id, f"Загружаем {url}")
            _job_log(job_id, f"Файл: {dest}")
            _job_log(job_id, "Это может занять несколько минут (~150MB)...")
            ok = await _run_cmd(
                job_id,
                ["wget", "-c", "-O", str(dest), "--tries=3", "--timeout=120",
                 "--progress=dot:mega", url],
            )
            if ok:
                sz = dest.stat().st_size if dest.exists() else 0
                _job_log(job_id, f"✓ Готово: {_fmt_size(sz)}")
            else:
                _job_log(job_id, "✗ Ошибка скачивания")
                if dest.exists() and dest.stat().st_size < 1024:
                    dest.unlink(missing_ok=True)
            _job_done(job_id, ok)

        asyncio.create_task(_rpi_worker())
        return {"job_id": job_id, "label": label, "dest": str(dest)}

    elif req.source == "mainline":
        version = req.version or "6.12.27"
        major = version.split(".")[0]
        filename = f"linux-{version}.tar.xz"
        url = f"https://cdn.kernel.org/pub/linux/kernel/v{major}.x/{filename}"
        dest = temp / filename
        label = f"Ядро mainline {version}"
        job_id = _new_job(label)

        async def _ml_worker():
            _job_log(job_id, f"Загружаем {url}")
            _job_log(job_id, f"Файл: {dest}")
            _job_log(job_id, "Это может занять несколько минут (~130MB)...")
            ok = await _run_cmd(
                job_id,
                ["wget", "-c", "-O", str(dest), "--tries=3", "--timeout=120",
                 "--progress=dot:mega", url],
            )
            if ok:
                sz = dest.stat().st_size if dest.exists() else 0
                _job_log(job_id, f"✓ Готово: {_fmt_size(sz)}")
            else:
                _job_log(job_id, "✗ Ошибка скачивания")
                if dest.exists() and dest.stat().st_size < 1024:
                    dest.unlink(missing_ok=True)
            _job_done(job_id, ok)

        asyncio.create_task(_ml_worker())
        return {"job_id": job_id, "label": label, "dest": str(dest)}

    else:
        raise HTTPException(status_code=400, detail=f"Неизвестный source: {req.source}")


@router.get("/pkg-cache/jobs")
def list_jobs():
    jobs = sorted(_jobs.values(), key=lambda j: j["started"], reverse=True)
    return {"jobs": jobs}


@router.get("/pkg-cache/jobs/{job_id}")
def get_job(job_id: str):
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    return _jobs[job_id]


@router.delete("/pkg-cache/packages/{name}")
def delete_package(name: str):
    dl_dir = _buildroot_dl_dir()
    if not dl_dir:
        raise HTTPException(status_code=400, detail="dl cache not found")
    pkg_dir = dl_dir / name
    if not pkg_dir.exists():
        raise HTTPException(status_code=404, detail=f"Package {name} not in cache")
    shutil.rmtree(pkg_dir)
    return {"deleted": name}


@router.delete("/pkg-cache/kernels/{filename}")
def delete_kernel(filename: str):
    temp = PROJECT_ROOT / "temp"
    # only allow known patterns
    if not (filename.startswith("rpi_linux-") or filename.startswith("linux-")):
        raise HTTPException(status_code=400, detail="Неверное имя файла")
    target = temp / filename
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"Файл не найден: {filename}")
    target.unlink()
    return {"deleted": filename}
