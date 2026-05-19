"""Manages build subprocesses and SSE streaming."""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncGenerator, Literal

PROJECT_ROOT = Path(__file__).parent.parent.parent

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
    _queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    _loop: asyncio.AbstractEventLoop | None = None


# Global registry
_builds: dict[str, BuildState] = {}


def get_build(build_id: str) -> BuildState | None:
    return _builds.get(build_id)


def list_builds() -> list[dict]:
    result = []
    for b in _builds.values():
        result.append({
            "build_id": b.build_id,
            "target": b.target,
            "status": b.status,
            "stage": b.stage,
            "log_lines": len(b.log_lines),
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
    try:
        for raw in proc.stdout:
            line = raw.rstrip("\n")
            state.log_lines.append(line)

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
        asyncio.run_coroutine_threadsafe(
            state._queue.put(final), loop
        )
        # sentinel to signal EOF
        asyncio.run_coroutine_threadsafe(
            state._queue.put(None), loop
        )
    except Exception as exc:
        state.status = "error"
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
    _builds[build_id] = state

    loop = asyncio.get_event_loop()
    state._loop = loop

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
