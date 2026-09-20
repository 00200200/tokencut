"""Execute once in the native shell; RTK only processes the captured text."""

from __future__ import annotations

import functools
import os
import shutil
import subprocess
from pathlib import Path

from tokencut.core.cache import ContextCache
from tokencut.core.companion_state import paused
from tokencut.core.redactor import redact_secrets

# This version's stdin filters are covered by real-binary preservation fixtures.
# Never use `rtk git status`: it executes git status twice in 0.49.0.
TESTED_RTK = {"rtk 0.49.0"}
FILTERS = {("git", "status"): "git-status", ("git", "diff", "--stat"): "git-diff"}


def rtk_path() -> str | None:
    return shutil.which("rtk") or next(
        (
            str(p)
            for p in (Path("/opt/homebrew/bin/rtk"), Path("/usr/local/bin/rtk"))
            if p.is_file() and os.access(p, os.X_OK)
        ),
        None,
    )


@functools.lru_cache(maxsize=8)
def _version(path: str, mtime: int) -> str | None:
    try:
        result = subprocess.run(
            [path, "--version"],
            capture_output=True,
            text=True,
            timeout=3,
            env=os.environ | {"RTK_TELEMETRY_DISABLED": "1"},
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def rtk_version() -> str | None:
    path = rtk_path()
    try:
        return _version(path, Path(path).stat().st_mtime_ns) if path else None
    except OSError:
        return None


def select_engine(requested: str, command: list[str]) -> str:
    if requested not in {"auto", "tokencut", "rtk", "none"}:
        raise ValueError("engine must be auto, tokencut, rtk, or none")
    if paused() or requested == "none":
        return "none"
    if requested == "tokencut":
        return requested
    supported = tuple(command) in FILTERS
    available = supported and rtk_version() in TESTED_RTK
    if requested == "rtk" and not available:
        raise ValueError(
            "RTK requires tested version 0.49.0 and exactly git status or git diff --stat. Use --engine tokencut instead."
        )
    return "rtk" if available else "tokencut"


def filter_rtk(raw: str, command: list[str], exit_code: int) -> str:
    """No user command is passed to RTK. Failure returns the captured original.

    In v1 only blank lines may disappear. Every nonblank line, including all
    paths and diagnostics, must survive in order. This also catches unsupported
    shapes and truncation in upstream filters. Counts include our recovery hint.
    """
    raw = redact_secrets(raw)
    if exit_code or not raw:
        return raw
    try:
        result = subprocess.run(
            [rtk_path(), "pipe", "--filter", FILTERS[tuple(command)]],
            input=raw,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=5,
            env=os.environ | {"RTK_TELEMETRY_DISABLED": "1", "RTK_NO_TOML": "1"},
        )
        output = result.stdout
        if result.returncode or result.stderr:
            return raw
        if [s for s in raw.splitlines() if s.strip()] != [
            s for s in output.splitlines() if s.strip()
        ]:
            return raw
        if output == raw:
            return raw
        # Cache failures must not remove any context.
        ref = ContextCache().store(raw, source="rtk", namespace="rtk")
        output += f"\n[TokenCut: full output after redaction: tokencut retrieve {ref}]\n"
        return output if len(output.encode()) < len(raw.encode()) else raw
    except Exception:
        return raw
