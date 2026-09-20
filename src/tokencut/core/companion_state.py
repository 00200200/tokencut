"""Small, read-only from clients, local companion preferences."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import tempfile
from pathlib import Path


def state_dir() -> Path:
    return Path(os.environ.get("TOKENCUT_STATE_DIR", str(Path.home() / ".tokencut")))


def settings() -> dict:
    try:
        value = json.loads((state_dir() / "companion.json").read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def paused() -> bool:
    return settings().get("paused") is True


def update_settings(**changes) -> dict:
    path = state_dir() / "companion.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = settings() | changes
    # Atomic replace plus a distinct backup for every actual configuration change.
    if path.exists() and data == settings():
        return data
    if path.exists():
        fd, backup = tempfile.mkstemp(prefix="companion.json.backup-", dir=path.parent)
        os.close(fd)
        shutil.copy2(path, backup)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=".companion-")
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)
    return data


def already_wrapped(command: str) -> bool:
    """Avoid composing filters, including commands with environment assignments.

    Conservatively skip the hook for compound commands containing a wrapper too.
    No shell execution is used to inspect the command.
    """
    try:
        words = shlex.split(command, posix=True)
    except ValueError:
        return False
    return any(Path(word).name in {"tokencut", "rtk"} for word in words)


def project_for(path: str | Path | None = None) -> str | None:
    if path is None:
        path = Path.cwd()
    target = Path(path).absolute()
    if not target.is_dir():
        target = target.parent
    for candidate in (target, *target.parents):
        if (candidate / ".git").exists():
            return str(candidate)
    return None


def client_name(default: str = "cli") -> str:
    explicit = os.environ.get("TOKENCUT_CLIENT")
    if explicit in {"codex", "claude-code", "claude-desktop", "antigravity", "cli", "mcp"}:
        return explicit
    if os.environ.get("CODEX_THREAD_ID"):
        return "codex"
    return default
