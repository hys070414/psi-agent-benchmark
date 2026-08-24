"""Edit tool — make a precise string replacement inside the task container.

The replacement is performed by a small Python script piped into `docker exec`,
so old/new strings with arbitrary special characters do not require shell
escaping.
"""

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


_EDITOR = r"""
import sys
path = sys.argv[1]
old = sys.stdin.buffer.readline().decode('utf-8', 'replace').rstrip('\n')
new = sys.stdin.buffer.readline().decode('utf-8', 'replace').rstrip('\n')
try:
    content = open(path, 'r', encoding='utf-8', errors='replace').read()
except FileNotFoundError:
    print('[Error] File not found: ' + path, file=sys.stderr)
    sys.exit(1)
count = content.count(old)
if count == 0:
    print('[Error] old_string not found in file', file=sys.stderr)
    sys.exit(2)
if count > 1:
    print('[Error] old_string appears %d times; must be unique to edit safely' % count, file=sys.stderr)
    sys.exit(3)
content = content.replace(old, new, 1)
open(path, 'w', encoding='utf-8').write(content)
print('[OK] Replaced 1 occurrence in ' + path)
"""


async def edit(file_path: str, old_string: str, new_string: str) -> str:
    """Replace a unique old_string with new_string in a file in the container.

    Args:
        file_path: Path to the file (absolute, or relative to /app).
        old_string: Exact text to find (must be unique).
        new_string: Text to replace it with.

    Returns:
        Success or error message.
    """
    container = _container()
    if not container:
        return "[Error] PSI_PILOT_CONTAINER is not set."

    resolved = _resolve(file_path)

    proc = await asyncio.create_subprocess_exec(
        "docker", "exec", "-i", container, "python3", "-c", _EDITOR, resolved,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    payload = f"{old_string}\n{new_string}\n".encode("utf-8")
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(payload), timeout=60
        )
    except TimeoutError:
        proc.kill()
        await proc.communicate()
        return f"[Error] Edit timed out: {file_path}"

    out = stdout.decode(errors="replace").strip()
    err = stderr.decode(errors="replace").strip()
    combined = out or err

    if proc.returncode != 0:
        return combined or f"[Error] Edit failed for {resolved}"
    return combined