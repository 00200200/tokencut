"""Normalize argv into a short tool family for telemetry (never the full command)."""

from __future__ import annotations

import re
from pathlib import PurePath

_PYTHON = re.compile(r"python(?:\d+(?:\.\d+)*)?(?:\.exe)?$", re.IGNORECASE)
_NODE = re.compile(r"node(?:\.exe)?$", re.IGNORECASE)


def command_family(argv: list[str] | tuple[str, ...] | None) -> str:
    """Return a stable tool family label such as ``pytest`` or ``git``.

    Only the executable identity is kept — never flags, paths, or arguments —
    so telemetry stays free of full command text.
    """
    if not argv:
        return "unknown"
    words = [str(part) for part in argv if str(part).strip()]
    if not words:
        return "unknown"

    # Common launchers: drop the wrapper, keep the tool.
    if words[0] in {"uv", "poetry", "pipenv"} and len(words) >= 2 and words[1] == "run":
        words = words[2:]
    elif PurePath(words[0]).name in {"npx", "pnpm", "yarn", "bun", "npm"} and len(words) >= 2:
        # npm/pnpm/yarn/bun run <script> → keep script name when present
        if words[1] == "run" and len(words) >= 3:
            return _clean(words[2])
        return _clean(words[1])
    elif PurePath(words[0]).name in {"cargo"} and len(words) >= 2:
        return f"cargo-{_clean(words[1])}"
    elif PurePath(words[0]).name in {"go"} and len(words) >= 2:
        return f"go-{_clean(words[1])}"

    if not words:
        return "unknown"

    name = PurePath(words[0]).name
    if _PYTHON.fullmatch(name) and len(words) >= 3 and words[1] == "-m":
        return _clean(words[2])
    if _NODE.fullmatch(name) and len(words) >= 2:
        return _clean(PurePath(words[1]).name)

    return _clean(name)


def _clean(name: str) -> str:
    base = PurePath(name).name
    if base.endswith(".exe"):
        base = base[:-4]
    base = base.strip().lower() or "unknown"
    # Keep labels short and telemetry-safe.
    return re.sub(r"[^a-z0-9._+-]+", "-", base)[:48]
