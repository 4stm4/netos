"""Manages build subprocesses and SSE streaming."""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator, Literal

PROJECT_ROOT = Path(__file__).parent.parent.parent

# Directory where build state/log JSON files are persisted.
# Override priority: set_builds_dir() call > NETOS_BUILDS_DIR env var > default.
BUILDS_DIR = Path(os.environ.get("NETOS_BUILDS_DIR", str(PROJECT_ROOT / "builds")))


def get_builds_dir() -> Path:
    """Return the currently configured builds directory."""
    return BUILDS_DIR


def set_builds_dir(path: Path | str) -> Path:
    """Update the builds directory at runtime (used by settings API)."""
    global BUILDS_DIR
    BUILDS_DIR = Path(path)
    BUILDS_DIR.mkdir(parents=True, exist_ok=True)
    return BUILDS_DIR


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

# Stage detection patterns (checked in order against each output line)
_STAGE_PATTERNS: list[tuple[str, str]] = [
    ("Устанавливаем зависимости", "host_deps"),
    ("Готовим исходники ядра", "kernel"),
    ("Собираем ядро", "kernel"),
    ("Building 4stm4 netOS rootfs with Buildroot", "buildroot"),
    ("Creating raw disk image", "image"),
    ("create_img", "image"),
    ("OVSDB_STARTED", "boot_test"),
    ("NET_AGENT_STARTED", "boot_test"),
]

_MAKE_PROGRESS_PREFIX = ">>> "

Status = Literal["running", "done", "error"]


@dataclass
class BuildState:
    build_id: str
    target: str
    status: Status = "running"
    stage: str = "init"
    log_lines: list[str] = field(default_factory=list)
    started_at: str = ""
    finished_at: str = ""
    _queue: asyncio.Queue | None = None
    _loop: asyncio.AbstractEventLoop | None = None


# Global registry
_builds: dict[str, BuildState] = {}


def _write_meta(state: BuildState) -> None:
    try:
        BUILDS_DIR.mkdir(exist_ok=True)
        (BUILDS_DIR / f"{state.build_id}.json").write_text(json.dumps({
            "build_id": state.build_id,
            "target": state.target,
            "status": state.status,
            "stage": state.stage,
            "started_at": state.started_at,
            "finished_at": state.finished_at,
        }))
    except Exception:
        pass


def _write_log(state: BuildState) -> None:
    try:
        (BUILDS_DIR / f"{state.build_id}.log").write_text("\n".join(state.log_lines))
    except Exception:
        pass


def _load_builds_from_disk() -> None:
    if not BUILDS_DIR.exists():
        return
    for f in sorted(BUILDS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            meta = json.loads(f.read_text())
            bid = meta["build_id"]
            if bid in _builds:
                continue
            # A build is "crashed" only if it was running AND has no log file
            # (log file means it was writing to disk — might still be running).
            disk_status = meta.get("status", "error")
            log_file = BUILDS_DIR / f"{bid}.log"
            if disk_status == "running" and not log_file.exists():
                disk_status = "error"   # lost — no log, no process
            state = BuildState(
                build_id=bid,
                target=meta.get("target", ""),
                status=disk_status,
                stage=meta.get("stage", ""),
                started_at=meta.get("started_at", ""),
                finished_at=meta.get("finished_at", ""),
            )
            if disk_status == "error" and not meta.get("finished_at"):
                state.finished_at = state.started_at
                _write_meta(state)
            log_file = BUILDS_DIR / f"{bid}.log"
            if log_file.exists():
                state.log_lines = log_file.read_text().splitlines()
            _builds[bid] = state
        except Exception:
            pass


def get_build(build_id: str) -> BuildState | None:
    return _builds.get(build_id)


def delete_build(build_id: str) -> bool:
    state = _builds.pop(build_id, None)
    if state is None:
        return False
    if state.status == "running":
        _builds[build_id] = state  # не удаляем запущенную сборку
        return False
    (BUILDS_DIR / f"{build_id}.json").unlink(missing_ok=True)
    (BUILDS_DIR / f"{build_id}.log").unlink(missing_ok=True)
    return True


def list_builds() -> list[dict]:
    result = []
    for b in sorted(_builds.values(), key=lambda b: b.started_at, reverse=True):
        result.append({
            "build_id": b.build_id,
            "target": b.target,
            "status": b.status,
            "stage": b.stage,
            "log_lines": len(b.log_lines),
            "started_at": b.started_at,
            "finished_at": b.finished_at,
        })
    return result


def _detect_stage(line: str) -> str | None:
    for pattern, stage in _STAGE_PATTERNS:
        if pattern in line:
            return stage
    return None


def _reader_thread(
    proc: subprocess.Popen,
    state: BuildState,
    loop: asyncio.AbstractEventLoop,
) -> None:
    """Reads subprocess stdout in a thread and puts events onto the async queue."""
    assert proc.stdout is not None
    _log_file = BUILDS_DIR / f"{state.build_id}.log"
    _flush_every = 50          # append to disk every N lines
    _unflushed = 0
    try:
        for raw in proc.stdout:
            line = raw.rstrip("\n")
            state.log_lines.append(line)
            # Incremental write: append line to log file so it survives uvicorn restart
            try:
                with _log_file.open("a") as _lf:
                    _lf.write(line + "\n")
            except Exception:
                pass

            event_type = "log"
            if line.startswith(_MAKE_PROGRESS_PREFIX):
                event_type = "make_progress"

            new_stage = _detect_stage(line)
            if new_stage and new_stage != state.stage:
                state.stage = new_stage
                stage_event = json.dumps({
                    "event": "stage",
                    "stage": new_stage,
                    "data": f"Stage: {new_stage}",
                    "build_id": state.build_id,
                })
                asyncio.run_coroutine_threadsafe(
                    state._queue.put(stage_event), loop
                )

            payload = json.dumps({
                "event": event_type,
                "data": line,
                "stage": state.stage,
                "build_id": state.build_id,
            })
            asyncio.run_coroutine_threadsafe(
                state._queue.put(payload), loop
            )

        proc.wait()
        if proc.returncode == 0:
            state.status = "done"
            final = json.dumps({
                "event": "done",
                "data": "Build completed successfully.",
                "stage": state.stage,
                "build_id": state.build_id,
            })
        else:
            state.status = "error"
            final = json.dumps({
                "event": "error",
                "data": f"Build failed with exit code {proc.returncode}.",
                "stage": state.stage,
                "build_id": state.build_id,
            })
        state.finished_at = _now()
        _write_meta(state)
        _write_log(state)
        asyncio.run_coroutine_threadsafe(
            state._queue.put(final), loop
        )
        # sentinel to signal EOF
        asyncio.run_coroutine_threadsafe(
            state._queue.put(None), loop
        )
    except Exception as exc:
        state.status = "error"
        state.finished_at = _now()
        _write_meta(state)
        _write_log(state)
        error_payload = json.dumps({
            "event": "error",
            "data": str(exc),
            "stage": state.stage,
            "build_id": state.build_id,
        })
        asyncio.run_coroutine_threadsafe(
            state._queue.put(error_payload), loop
        )
        asyncio.run_coroutine_threadsafe(
            state._queue.put(None), loop
        )


def start_build(
    target: str,
    env_override: dict[str, str] | None = None,
    extra_packages: list[str] | None = None,
) -> str:
    """Start a build subprocess and return a build_id."""
    build_id = uuid.uuid4().hex[:12]
    state = BuildState(build_id=build_id, target=target)
    state.started_at = _now()
    _builds[build_id] = state
    _write_meta(state)

    loop = asyncio.get_event_loop()
    state._loop = loop
    state._queue = asyncio.Queue()

    env = dict(os.environ)
    if env_override:
        env.update(env_override)

    cmd = [
        "python3",
        str(PROJECT_ROOT / "src" / "main.py"),
        "--target", target,
    ]
    if extra_packages:
        # Write extra packages to a temp file and pass via --packages-file
        import tempfile
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, prefix="netos_pkgs_"
        )
        tmp.write("\n".join(extra_packages) + "\n")
        tmp.close()
        cmd += ["--packages-file", tmp.name]

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=str(PROJECT_ROOT),
            env=env,
        )
    except Exception as exc:
        state.status = "error"
        state.log_lines.append(str(exc))
        # Put a terminal event so the SSE generator can finish
        async def _put_error():
            await state._queue.put(json.dumps({
                "event": "error",
                "data": str(exc),
                "stage": "init",
                "build_id": build_id,
            }))
            await state._queue.put(None)
        loop.call_soon_threadsafe(lambda: asyncio.ensure_future(_put_error()))
        return build_id

    t = threading.Thread(
        target=_reader_thread,
        args=(proc, state, loop),
        daemon=True,
    )
    t.start()

    return build_id


async def stream_events(build_id: str) -> AsyncGenerator[str, None]:
    """Async generator yielding SSE-formatted strings for the given build."""
    state = _builds.get(build_id)
    if state is None:
        yield f"data: {json.dumps({'event': 'error', 'data': 'Build not found', 'build_id': build_id, 'stage': ''})}\n\n"
        return

    # Replay existing log lines first (for reconnects)
    for line in list(state.log_lines):
        payload = json.dumps({
            "event": "log",
            "data": line,
            "stage": state.stage,
            "build_id": build_id,
        })
        yield f"data: {payload}\n\n"

    if state.status != "running":
        final = json.dumps({
            "event": state.status,
            "data": "Build already finished.",
            "stage": state.stage,
            "build_id": build_id,
        })
        yield f"data: {final}\n\n"
        return

    if state._queue is None:
        yield f"data: {json.dumps({'event': 'error', 'data': 'Build queue unavailable.', 'build_id': build_id, 'stage': state.stage})}\n\n"
        return

    # Stream live events from queue
    while True:
        try:
            item = await asyncio.wait_for(state._queue.get(), timeout=30.0)
        except asyncio.TimeoutError:
            # Send keepalive comment
            yield ": keepalive\n\n"
            continue

        if item is None:
            break
        yield f"data: {item}\n\n"


# Populate registry from disk on import (survives server restarts)
_load_builds_from_disk()
