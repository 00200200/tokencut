"""Conservative, recoverable filtering for automatic command-output routing."""

from __future__ import annotations

import re
import shlex
from pathlib import PurePath

from tokencut.core.cache import ContextCache
from tokencut.core.redactor import redact_secrets
from tokencut.metrics.tokenizer import count_tokens

# Avoid cache notices and extra work for already small command results.
_MIN_TOKENS = 256
_COLOR = re.compile(r"\x1b\[[0-9;]*m")
_PYTHON = re.compile(r"python(?:\d+(?:\.\d+)*)?")
_PASSED = re.compile(
    r"(?:\[gw\d+\]\s+\[\s*\d+%\]\s+PASSED\s+\S+\.py::\S+"
    r"|\S+\.py::\S+\s+PASSED(?:\s+\[\s*\d+%\])?)\s*"
)
_DOTS = re.compile(r"(?:\S+\.py\s+)?(?P<dots>\.+)\s+\[\s*\d+%\]\s*")
_DIAGNOSTIC = re.compile(
    r"\b(?:traceback|error|errors|failed|failure|failures|warning|warnings|"
    r"exception|assertionerror|assert|fatal|panic)\b|^\s*[EF]\s+",
    re.IGNORECASE,
)


def _pytest_command(command: str) -> bool:
    """Recognize direct invocations only; never guess what a shell pipeline runs."""
    if not command or "\n" in command:
        return False
    try:
        words = shlex.split(command)
    except ValueError:
        return False
    if not words or any(re.search(r"[|;&<>`$]", word) for word in words):
        return False
    if words[:2] == ["uv", "run"]:
        words = words[2:]
    if not words:
        return False
    executable = PurePath(words[0]).name
    return executable in {"pytest", "py.test"} or (
        bool(_PYTHON.fullmatch(executable)) and words[1:3] == ["-m", "pytest"]
    )


def _pytest_session(lines: list[str]) -> bool:
    """Require a whole pytest session shape when the command is unavailable."""
    nonempty = [_COLOR.sub("", line).strip() for line in lines if line.strip()]
    return bool(
        nonempty
        and re.fullmatch(r"=+ test session starts =+", nonempty[0])
        and any(re.fullmatch(r"collected \d+ items?.*", line) for line in nonempty[1:8])
        and re.fullmatch(r"=+ .+ in [0-9.]+s(?: \([^\n]*\))? =+", nonempty[-1])
    )


def _passed_count(line: str) -> int:
    line = _COLOR.sub("", line.rstrip("\r\n"))
    if _PASSED.fullmatch(line):
        return 1
    match = _DOTS.fullmatch(line)
    return len(match["dots"]) if match else 0


def safe_compact_output(text: str, *, command: str = "", exit_code: int | None = None) -> str:
    """Filter routine records without truncating arbitrary output or diagnostics.

    Only recognized pytest pass records and exact contiguous duplicate lines are
    compacted. Once a diagnostic begins, the remaining output is kept verbatim.
    Exit status is never inferred from pass records; callers retain ``exit_code``
    separately. The redacted original is cached before a shorter result is used.
    Any cache/tokenizer failure returns the original after best-effort redaction.
    Counts are local estimates, not model billing or subscription usage.
    """
    original = redact_secrets(text)
    if not original:
        return original
    try:
        original_tokens = count_tokens(original).openai
    except Exception:
        return original
    if original_tokens < _MIN_TOKENS:
        return original

    lines = original.splitlines(keepends=True)
    pytest_output = _pytest_command(command) or _pytest_session(lines)
    result: list[str] = []
    i = 0
    changed = False
    while i < len(lines):
        line = lines[i]
        # Tracebacks may themselves contain repeated lines or text that resembles
        # passing test records. Never interpret anything inside/after diagnostics.
        if _DIAGNOSTIC.search(_COLOR.sub("", line)):
            result.extend(lines[i:])
            break

        passed = _passed_count(line) if pytest_output else 0
        if passed:
            end = i + 1
            while end < len(lines):
                if _DIAGNOSTIC.search(_COLOR.sub("", lines[end])):
                    break
                count = _passed_count(lines[end])
                if not count:
                    break
                passed += count
                end += 1
            result.append(f"[TokenCut: {passed} passing tests, {end - i} progress records]\n")
            changed = True
            i = end
            continue

        end = i + 1
        while end < len(lines) and lines[end] == line:
            end += 1
        result.append(line)
        if end - i > 1 and line.strip():
            if not line.endswith(("\n", "\r")):
                result.append("\n")
            result.append(f"[TokenCut: preceding line repeated {end - i} times total]\n")
            changed = True
        else:
            result.extend(lines[i + 1 : end])
        i = end

    if not changed:
        return original
    compact = "".join(result)
    try:
        # Avoid writing cache entries for candidates that cannot possibly save.
        if count_tokens(compact).openai >= original_tokens:
            return original
        cache = ContextCache()
        ref = cache.store(original, source="safe-command-output")
        separator = "" if compact.endswith(("\n", "\r")) else "\n"
        compact += f"{separator}[TokenCut: full output after redaction: tokencut retrieve {ref}]\n"
        if count_tokens(compact).openai >= original_tokens:
            return original
        return compact
    except Exception:
        # Filtering must not turn disk, database, or tokenizer problems into
        # missing command output. The caller still receives complete diagnostics.
        return original
