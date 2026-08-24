"""Read tool — read a file's contents inside the task container."""

from __future__ import annotations

import asyncio
import os
import shlex


def _container() -> str:
    return os.environ.get("PSI_PILOT_CONTAINER", "")


def _resolve(path: str) -> str:
    # Relative paths are interpreted relative to /app, the container workdir.
    if path.startswith("/"):
        return path
    return f"/app/{path}"


async def read(file_path: str, offset: int = 0, limit: int = 0) -> str:
    """Read file contents from inside the task container.

    Args:
        file_path: Path to the file (absolute, or relative to /app).
        offset: Line number to start reading from (0 = beginning).
        limit: Max lines to read (0 = no limit).

    Returns:
        File contents, or an error message if unreadable.
    """
    container = _container()
    if not container:
        return "[Error] PSI_PILOT_CONTAINER is not set."

    resolved = _resolve(file_path)
    # `cat` for full read; `sed` when paging.
    inner = f"cat {shlex.quote(resolved)}"
    if offset > 0 or limit > 0:
        start = offset + 1
        if limit > 0:
            inner = (
                f"sed -n '{start},{start + limit - 1}p' {shlex.quote(resolved)}"
            )
        else:
            inner = f"sed -n '{start},$p' {shlex.quote(resolved)}"

    proc = await asyncio.create_subprocess_exec(
        "docker", "exec", container, "bash", "-lc", inner,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
    except TimeoutError:
        proc.kill()
        await proc.communicate()
        return f"[Error] Read timed out: {file_path}"

    out = stdout.decode(errors="replace")
    err = stderr.decode(errors="replace")
    if proc.returncode != 0 or "No such file" in err:
        return f"[Error] Cannot read {file_path}: {err}".rstrip()

    return out.rstrip() or "(empty file)"