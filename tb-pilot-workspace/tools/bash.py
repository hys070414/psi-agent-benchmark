"""Bash tool — execute shell commands inside the task container.

Unlike the plain host bash, this tool runs every command inside the
Terminal-Bench  task container (the one named by the env var
`PSI_PILOT_CONTAINER`) using `docker exec`, so the agent's actions actually
modify the isolated environment that the verifier will later check.
"""

from __future__ import annotations

import asyncio
import os


def _container() -> str:
    return os.environ.get("PSI_PILOT_CONTAINER", "")


async def bash(command: str, timeout_seconds: int = 300) -> str:
    """Run a shell command inside the task container (cwd = /app).

    Args:
        command: The shell command to run. Executed with `bash -lc` inside the
            container, starting from /app.
        timeout_seconds: Max seconds to wait for the command to finish.

    Returns:
        Combined stdout/stderr, with a trailing exit code on failure.
    """
    container = _container()
    if not container:
        return (
            "[Error] PSI_PILOT_CONTAINER is not set. There is no task container "
            "to operate in. You must use the tools to act inside the container."
        )

    # Run inside the task container, defaulting to /app (the standard workdir).
    full = f"cd /app && {command}"

    proc = await asyncio.create_subprocess_exec(
        "docker", "exec", container, "bash", "-lc", full,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=timeout_seconds
        )
    except TimeoutError:
        proc.kill()
        await proc.communicate()
        return f"[Error] Command timed out after {timeout_seconds}s: {command}"

    out = stdout.decode(errors="replace")
    err = stderr.decode(errors="replace")
    combined = (out + err).rstrip()

    if proc.returncode != 0:
        combined += f"\n[Exit code: {proc.returncode}]"

    return combined or "(no output)"