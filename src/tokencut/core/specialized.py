from __future__ import annotations

import re

from tokencut.core.diff_slimmer import slim_git_diff

# `git log` indents commit messages by exactly four spaces. Patch bodies (-p) and
# --stat blocks sit at other indents, so they must be detected explicitly instead
# of being mistaken for message text.
_COMMIT_RE = re.compile(r"^commit ([0-9a-f]{7,40})\b")
_DIFF_RE = re.compile(r"^diff --(?:git|cc|combined) ")
_STAT_FILE_RE = re.compile(r"^ \S.*\|\s+(?:\d+|Bin)\b")
_STAT_SUMMARY_RE = re.compile(r"^ \d+ files? changed")


def _starts_payload(line: str) -> bool:
    """Detect the first line of a --stat block or a -p patch body."""
    return bool(_DIFF_RE.match(line) or _STAT_FILE_RE.match(line) or _STAT_SUMMARY_RE.match(line))


def _compact_payload(payload_lines: list[str], max_context_lines: int) -> str:
    """Compact a commit's --stat/-p payload instead of discarding it.

    Stat blocks are already dense and are kept verbatim; patch bodies are routed
    through the shared diff compactor so added and removed lines survive.
    """
    diff_start = next((i for i, line in enumerate(payload_lines) if _DIFF_RE.match(line)), None)
    if diff_start is None:
        return "\n".join(payload_lines).strip("\n")

    stat_part = "\n".join(payload_lines[:diff_start]).strip("\n")
    diff_part = "\n".join(payload_lines[diff_start:])
    slimmed = slim_git_diff(diff_part, max_context_lines=max_context_lines).strip("\n")
    return f"{stat_part}\n{slimmed}".strip("\n") if stat_part else slimmed


def filter_git_log(raw_log: str, max_commits: int = 15, max_context_lines: int = 2) -> str:
    """Compress verbose git log into dense 1-line format, saving ~75% tokens.

    Patch bodies (`-p`) and stat blocks (`--stat`) are compacted rather than
    dropped, and never leak into the commit message.
    """
    if not raw_log.strip():
        return raw_log

    lines = raw_log.splitlines()
    commits: list[str] = []
    current_hash = ""
    current_author = ""
    current_msg: list[str] = []
    current_payload: list[str] = []
    in_payload = False

    def flush_commit():
        nonlocal current_hash, current_author, current_msg, current_payload, in_payload
        if current_hash:
            msg = " ".join(current_msg).strip()
            author_short = current_author.split("<")[0].strip() if current_author else ""
            entry = f"{current_hash[:7]} [{author_short}] {msg}".rstrip()
            payload = _compact_payload(current_payload, max_context_lines)
            if payload:
                entry = f"{entry}\n{payload}"
            commits.append(entry)
        current_hash = ""
        current_author = ""
        current_msg = []
        current_payload = []
        in_payload = False

    for line in lines:
        commit_match = _COMMIT_RE.match(line)
        if commit_match:
            # Unified diff bodies always prefix their lines, so a bare `commit <sha>`
            # at column zero reliably terminates the previous commit's payload.
            flush_commit()
            current_hash = commit_match.group(1)
        elif in_payload:
            current_payload.append(line)
        elif _starts_payload(line):
            in_payload = True
            current_payload.append(line)
        elif line.startswith("Author:"):
            current_author = line.replace("Author:", "").strip()
        elif line.startswith("Date:"):
            continue
        elif line.startswith("    "):
            current_msg.append(line.strip())

    flush_commit()

    if len(commits) > max_commits:
        omitted = len(commits) - max_commits
        return "\n".join(
            commits[:max_commits] + [f"[... {omitted} older commits omitted by tokencut ...]"]
        )
    return "\n".join(commits) if commits else raw_log


def filter_git_status(raw_status: str) -> str:
    """Group and condense massive untracked file listings in git status."""
    lines = raw_status.splitlines()
    untracked_dirs: dict[str, int] = {}
    cleaned_lines: list[str] = []
    in_untracked = False

    for line in lines:
        stripped = line.strip()
        if "Untracked files:" in line:
            in_untracked = True
            cleaned_lines.append(line)
            continue

        if in_untracked:
            if stripped.startswith("(") and stripped.endswith(")"):
                continue
            if not stripped:
                in_untracked = False
                # Flush untracked summary
                if untracked_dirs:
                    for d, count in untracked_dirs.items():
                        cleaned_lines.append(f"\t{d}/ ({count} untracked files)")
                    untracked_dirs = {}
                cleaned_lines.append(line)
                continue

            # Check if untracked line has a folder
            parts = stripped.split("/", 1)
            if len(parts) > 1:
                top_dir = parts[0]
                untracked_dirs[top_dir] = untracked_dirs.get(top_dir, 0) + 1
            else:
                cleaned_lines.append(line)
        else:
            cleaned_lines.append(line)

    if untracked_dirs:
        for d, count in untracked_dirs.items():
            cleaned_lines.append(f"\t{d}/ ({count} untracked files)")

    return "\n".join(cleaned_lines)


def auto_specialize_command_output(command: str, raw_output: str) -> str | None:
    """Detect if command has a specialized ultra-dense filter."""
    cmd_lower = command.lower().strip()
    if cmd_lower.startswith("git log"):
        return filter_git_log(raw_output)
    elif cmd_lower.startswith("git status"):
        return filter_git_status(raw_output)
    return None
