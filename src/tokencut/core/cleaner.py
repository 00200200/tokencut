from __future__ import annotations

import re
from dataclasses import dataclass

from tokencut.core.cache import ContextCache
from tokencut.core.redactor import redact_secrets

# Regular expressions for ANSI & terminal control sequences
ANSI_CSI_PATTERN = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")
ANSI_OSC_PATTERN = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
ANSI_GENERIC_PATTERN = re.compile(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")

# Progress indicator patterns (spinners, dots, hashes)
SPINNER_CHARS = {"⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏", "◐", "◓", "◑", "◒", "-\\|/"}
PROGRESS_BAR_PATTERN = re.compile(r"(?:\[[=#\-\s]{5,}\]|\b\d{1,3}%\b|\b\d+/\d+\b)")

# Error & traceback signatures
ERROR_SIGNATURES = [
    re.compile(r"Traceback \(most recent call last\):", re.IGNORECASE),
    re.compile(r"={3,}\s*(?:FAILURES|ERRORS)\s*={3,}", re.IGNORECASE),
    re.compile(r"\bFAILED\s*(?:\(|\[)", re.IGNORECASE),
    re.compile(
        r"\b(?:AssertionError|ValueError|TypeError|KeyError|AttributeError|RuntimeError|Exception):"
    ),
    re.compile(r"\b(?:panic:|fatal error:|NullPointerException|Segmentation fault)", re.IGNORECASE),
    re.compile(r"\b(?:npm ERR!|yarn error|error\[E\d+\]:|TS\d+:)", re.IGNORECASE),
    re.compile(r"^(?:Error|FATAL|CRITICAL):", re.IGNORECASE | re.MULTILINE),
]


@dataclass
class CleanerOptions:
    max_lines: int = 80
    head_lines: int = 20
    tail_lines: int = 40
    strip_ansi: bool = True
    dedup_lines: bool = True
    preserve_errors: bool = True
    normalize_whitespace: bool = True
    redact_keys: bool = True
    enable_cache: bool = True


def strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences, OSC strings, and control characters."""
    if not text:
        return ""
    text = ANSI_OSC_PATTERN.sub("", text)
    text = ANSI_CSI_PATTERN.sub("", text)
    text = ANSI_GENERIC_PATTERN.sub("", text)
    return text


def resolve_carriage_returns(text: str) -> str:
    """Resolve carriage returns (\\r) by keeping the final overwrite of each line."""
    if "\r" not in text:
        return text

    resolved_lines: list[str] = []
    text = text.replace("\r\n", "\n")

    for raw_line in text.split("\n"):
        if "\r" in raw_line:
            parts = raw_line.split("\r")
            non_empty = [p for p in parts if p.strip()]
            resolved_lines.append(non_empty[-1] if non_empty else "")
        else:
            resolved_lines.append(raw_line)

    return "\n".join(resolved_lines)


def deduplicate_repetitive_lines(lines: list[str], max_consecutive: int = 2) -> list[str]:
    """Collapse consecutive duplicate or highly repetitive lines."""
    if not lines:
        return []

    result: list[str] = []
    prev_line = None
    repeat_count = 0

    def flush_repeat():
        nonlocal repeat_count, prev_line
        if repeat_count > max_consecutive:
            omitted = repeat_count - max_consecutive
            result.append(f"  [... {omitted} identical lines omitted by tokencut ...]")
        repeat_count = 0

    for line in lines:
        stripped = line.strip()
        if stripped and stripped == prev_line:
            repeat_count += 1
            if repeat_count <= max_consecutive:
                result.append(line)
        else:
            flush_repeat()
            prev_line = stripped
            repeat_count = 1
            result.append(line)

    flush_repeat()
    return result


def find_first_error_index(lines: list[str]) -> int | None:
    """Find line index where error/traceback starts."""
    for idx, line in enumerate(lines):
        for sig in ERROR_SIGNATURES:
            if sig.search(line):
                return idx
    return None


def compact_terminal_output(raw_text: str, options: CleanerOptions | None = None) -> str:
    """State-of-the-art terminal log compactor.

    - Strips ANSI colors and terminal garbage
    - Scrubs API keys & sensitive secrets
    - Resolves \\r progress bar overwrites
    - Deduplicates repeated lines
    - If errors/tracebacks exist: preserves full error & stacktrace, truncating routine logs
    - If no errors: preserves head and tail of output
    - Stores full original in local cache for 100% reversible retrieval via ref ID
    """
    if not raw_text:
        return ""

    opts = options or CleanerOptions()
    text = raw_text

    if opts.redact_keys:
        text = redact_secrets(text)

    if opts.strip_ansi:
        text = strip_ansi(text)

    text = resolve_carriage_returns(text)
    lines = text.splitlines()

    if opts.dedup_lines:
        lines = deduplicate_repetitive_lines(lines)

    total_lines = len(lines)
    if total_lines <= opts.max_lines:
        cleaned = "\n".join(lines)
        if opts.normalize_whitespace:
            cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned.strip()

    # Store in local cache to ensure 100% reversibility
    ref_tag = ""
    if opts.enable_cache:
        try:
            cache = ContextCache()
            ref_id = cache.store(raw_text, source="terminal_output")
            ref_tag = f" [ref: {ref_id}]"
        except Exception:
            pass

    # Truncation logic
    head_count = opts.head_lines
    tail_count = opts.tail_lines

    if opts.preserve_errors:
        err_idx = find_first_error_index(lines)
        if err_idx is not None:
            if err_idx < head_count:
                kept_head = lines[:head_count]
                kept_tail = (
                    lines[-tail_count:]
                    if total_lines > head_count + tail_count
                    else lines[head_count:]
                )
                omitted = max(0, total_lines - len(kept_head) - len(kept_tail))
                if omitted > 0:
                    summary_line = (
                        f"\n[... {omitted} lines of logs omitted by tokencut{ref_tag} ...]\n"
                    )
                    res = kept_head + [summary_line] + kept_tail
                else:
                    res = kept_head + kept_tail
            else:
                kept_head = lines[:head_count]
                error_lines = lines[err_idx:]
                if len(error_lines) > tail_count * 2:
                    error_lines = (
                        lines[err_idx : err_idx + 20]
                        + [
                            f"\n[... {len(lines) - err_idx - 50} lines inside error omitted{ref_tag} ...]\n"
                        ]
                        + lines[-30:]
                    )

                omitted = max(0, err_idx - head_count)
                summary_line = (
                    f"\n[... {omitted} lines of routine output omitted by tokencut{ref_tag} ...]\n"
                )
                res = kept_head + [summary_line] + error_lines

            cleaned = "\n".join(res)
            if opts.normalize_whitespace:
                cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
            return cleaned.strip()

    # No error found
    kept_head = lines[:head_count]
    kept_tail = lines[-tail_count:]
    omitted = total_lines - head_count - tail_count
    summary_line = f"\n[... {omitted} lines omitted by tokencut{ref_tag} ...]\n"
    res = kept_head + [summary_line] + kept_tail

    cleaned = "\n".join(res)
    if opts.normalize_whitespace:
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()
