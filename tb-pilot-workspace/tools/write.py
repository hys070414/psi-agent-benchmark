"""Write tool — create or overwrite a file inside the task container."""

from __future__ import annotations

import asyncio
import os
import shlex


def _container() -> str:
    return os.environ.get("PSI_PILOT_CONTAINER", "")


def _resolve(path: str) -> str:
    if path.startswith("/"):
        return path
    return f"/app/{path}"


async def write(file_path: str, content: str) -> str:
    """Create or overwrite a file inside the task container.

    Args:
        file_path: Path to the file (absolute, or relative to /app).
        content: The exact content to write.

    Returns:
        Success or error message.
    """
    container = _container()
    if not container:
        return "[Error] PSI_PILOT_CONTAINER is not set."

    resolved = _resolve(file_path)
    parent = f"/app" if resolved == "/app" else resolved.rsplit("/", 1)[0]

    # Rely on `tee` with stdin so content is written verbatim (no shell escaping).
    inner = (
        f"mkdir -p {shlex.quote(parent)} && "
        f"cat > {shlex.quote(resolved)}"
    )

    proc = await asyncio.create_subprocess_exec(
        "docker", "exec", "-i", container, "bash", "-lc", inner,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(content.encode("utf-8")), timeout=60
        )
    except TimeoutError:
        proc.kill()
        await proc.communicate()
        return f"[Error] Write timed out: {file_path}"

    err = stderr.decode(errors="replace")
    if proc.returncode != 0:
        return f"[Error] Cannot write {file_path}: {err}".rstrip()

    size = len(content.encode("utf-8"))
    return f"[OK] Written {size} bytes to {resolved}"