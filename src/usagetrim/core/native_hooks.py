"""Native client adapters: change returned text, never permissions or commands."""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from usagetrim.core.companion_state import already_wrapped, paused
from usagetrim.core.safe_filter import safe_compact_output
from usagetrim.core.telemetry import record_text


def claude_post_tool_use(payload: Any) -> dict[str, Any]:
    """Return a replacement Bash response only when it can be safely recognized.

    Claude validates updatedToolOutput against its tool schema. Preserve all
    metadata and stderr; do not turn a failing/interrupted command into success.
    Malformed or unsupported events fail open with no additional model context.
    """
    start = time.perf_counter()
    if paused() or not isinstance(payload, dict):
        return {}
    if payload.get("hook_event_name") != "PostToolUse" or payload.get("tool_name") != "Bash":
        return {}
    original = payload.get("tool_response")
    tool_input = payload.get("tool_input")
    if not isinstance(original, dict) or not isinstance(tool_input, dict):
        return {}
    if original.get("isImage") or original.get("interrupted"):
        return {}
    command = tool_input.get("command", "")
    if not isinstance(command, str) or already_wrapped(command):
        return {}
    result = original.copy()
    for stream in ("stdout", "stderr"):
        text = original.get(stream)
        if text is not None and not isinstance(text, str):
            return {}
        if text:
            result[stream] = safe_compact_output(text, command=command)
    if result == original:
        return {}
    identity = payload.get("tool_use_id")
    session = payload.get("session_id")
    event_id = (
        "hook:" + hashlib.sha256(f"{session}:{identity}".encode()).hexdigest()
        if isinstance(identity, str) and isinstance(session, str)
        else None
    )
    record_text(
        "".join(original.get(k) or "" for k in ("stdout", "stderr")),
        "".join(result.get(k) or "" for k in ("stdout", "stderr")),
        client="claude-code",
        project=payload.get("cwd"),
        delivery="prepared",
        event_id=event_id,
        duration_s=time.perf_counter() - start,
    )
    return {"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedToolOutput": result}}


def run_hook_filter(client: str, stream: Any, output: Any) -> None:
    """Bound input and emit only the hook protocol, even on a local failure."""
    response = {}
    try:
        raw = stream.read(8 * 1024 * 1024 + 1)
        if len(raw) <= 8 * 1024 * 1024 and client == "claude":
            response = claude_post_tool_use(json.loads(raw))
    except Exception:
        pass
    output.write(json.dumps(response, ensure_ascii=False) + "\n")


def install_claude_hook(executable: Path, settings_path: Path | None = None) -> Path:
    """Opt-in installation; preserve existing settings, permissions and hooks."""
    executable = executable.resolve(strict=True)
    settings = (settings_path or Path.home() / ".claude" / "settings.json").resolve()
    data = json.loads(settings.read_text()) if settings.exists() else {}
    if not isinstance(data, dict) or not isinstance(data.get("hooks", {}), dict):
        raise ValueError("Claude settings/hooks must be JSON objects")
    hooks = data.setdefault("hooks", {})
    entries = hooks.setdefault("PostToolUse", [])
    if not isinstance(entries, list):
        raise ValueError("Claude PostToolUse hooks must be a list")
    if any(
        not isinstance(entry, dict)
        or not isinstance(entry.get("hooks"), list)
        or any(not isinstance(hook, dict) for hook in entry["hooks"])
        for entry in entries
    ):
        raise ValueError("Each Claude PostToolUse entry must contain a list of hook objects")
    command = shlex.join([str(executable), "hook-filter", "--client", "claude"])
    if any(
        isinstance(entry, dict)
        and entry.get("matcher") == "^Bash$"
        and any(isinstance(h, dict) and h.get("command") == command for h in entry.get("hooks", []))
        for entry in entries
    ):
        return settings
    entries.append(
        {"matcher": "^Bash$", "hooks": [{"type": "command", "command": command, "timeout": 5}]}
    )
    settings.parent.mkdir(parents=True, exist_ok=True)
    if settings.exists():
        # One unique backup per actual change; never overwrite an earlier backup.
        with tempfile.NamedTemporaryFile(
            prefix=settings.name + ".pre-usagetrim-", dir=settings.parent, delete=False
        ) as backup:
            backup_path = Path(backup.name)
        shutil.copy2(settings, backup_path)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=settings.parent, delete=False
    ) as staged:
        temp_path = Path(staged.name)
        json.dump(data, staged, indent=2, ensure_ascii=False)
        staged.write("\n")
    try:
        if settings.exists():
            os.chmod(temp_path, settings.stat().st_mode & 0o777)
        temp_path.replace(settings)
    finally:
        temp_path.unlink(missing_ok=True)
    return settings
