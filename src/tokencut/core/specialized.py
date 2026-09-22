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


# Cargo prints one line per test. Only unambiguous passes are collapsed, and the
# diagnostic vocabulary mirrors safe_filter so failures are never reinterpreted.
_CARGO_OK = re.compile(r"^test \S+ \.\.\. ok$")
_CARGO_DIAGNOSTIC = re.compile(
    r"\b(?:FAILED|failures|failed|panicked|error|warning|timeout)\b", re.IGNORECASE
)


def filter_cargo_test(raw_output: str) -> str:
    """Collapse runs of passing cargo test records while keeping every diagnostic.

    Mirrors the pytest handling in ``safe_filter``: once a diagnostic line appears
    the remainder of the output is kept verbatim, so failures, panics and
    backtraces always reach the model intact. The trailing ``test result:`` summary
    carries the authoritative pass and fail counts and is never rewritten.
    """
    lines = raw_output.splitlines()
    result: list[str] = []
    index = 0
    collapsed = False

    while index < len(lines):
        line = lines[index]
        # A record matching the anchored pass pattern ends in "... ok" and cannot be
        # a diagnostic, so test names containing "error" still collapse.
        if not _CARGO_OK.fullmatch(line.strip()) and _CARGO_DIAGNOSTIC.search(line):
            result.extend(lines[index:])
            break

        if _CARGO_OK.fullmatch(line.strip()):
            end = index + 1
            while end < len(lines):
                if not _CARGO_OK.fullmatch(lines[end].strip()):
                    break
                end += 1
            passed = end - index
            result.append(f"[TokenCut: {passed} passing tests, {passed} progress records]")
            collapsed = True
            index = end
            continue

        result.append(line)
        index += 1

    if not collapsed:
        return raw_output
    return "\n".join(result)


# Go test outputs pairs or lines of '=== RUN' and '--- PASS:'.
# Diagnosing lines contain '--- FAIL:', 'panic:', 'FAIL', etc.
_GO_TEST_OK = re.compile(r"^\s*(?:=== RUN\s+\S+|--- PASS:\s+\S+\s+\([0-9.]+s\))$")
_GO_PASS_RECORD = re.compile(r"^\s*--- PASS:\s+\S+\s+\([0-9.]+s\)")
_GO_DIAGNOSTIC = re.compile(
    r"\b(?:FAIL|panic|fatal|error|warning|timeout|SIGSEGV)\b|--- FAIL:", re.IGNORECASE
)


def filter_go_test(raw_output: str) -> str:
    """Collapse runs of passing go test records while keeping diagnostics verbatim."""
    lines = raw_output.splitlines()
    result: list[str] = []
    index = 0
    collapsed = False

    while index < len(lines):
        line = lines[index]
        if not _GO_TEST_OK.match(line.strip()) and _GO_DIAGNOSTIC.search(line):
            result.extend(lines[index:])
            break

        if _GO_TEST_OK.match(line.strip()):
            end = index + 1
            while end < len(lines):
                if not _GO_TEST_OK.match(lines[end].strip()):
                    break
                end += 1
            chunk = lines[index:end]
            passed = sum(1 for ln in chunk if _GO_PASS_RECORD.match(ln.strip()))
            records = len(chunk)
            if passed > 0:
                result.append(f"[TokenCut: {passed} passing tests, {records} progress records]")
                collapsed = True
                index = end
                continue
            else:
                result.extend(chunk)
                index = end
                continue

        result.append(line)
        index += 1

    if not collapsed:
        return raw_output
    return "\n".join(result)


# Jest and Vitest print progress records with checkmarks or PASS prefixes.
_JS_TEST_OK = re.compile(
    r"^\s*(?:PASS\s+\S+|[✓√]\s+.*(?:\([0-9.]+\s*m?s\)|\(\d+\s+tests?\)|$))\s*$"
)
_JS_DIAGNOSTIC = re.compile(
    r"\b(?:FAIL|failed|failure|failures|Error|AssertionError|panic|fatal|warning|timeout)\b|[✕×]",
    re.IGNORECASE,
)


def filter_jest_vitest(raw_output: str) -> str:
    """Collapse runs of passing Jest/Vitest records while keeping diagnostics verbatim."""
    lines = raw_output.splitlines()
    result: list[str] = []
    index = 0
    collapsed = False

    while index < len(lines):
        line = lines[index]
        if not _JS_TEST_OK.match(line.strip()) and _JS_DIAGNOSTIC.search(line):
            result.extend(lines[index:])
            break

        if _JS_TEST_OK.match(line.strip()):
            end = index + 1
            while end < len(lines):
                if not _JS_TEST_OK.match(lines[end].strip()):
                    break
                end += 1
            passed = end - index
            result.append(f"[TokenCut: {passed} passing tests, {passed} progress records]")
            collapsed = True
            index = end
            continue

        result.append(line)
        index += 1

    if not collapsed:
        return raw_output
    return "\n".join(result)


def auto_specialize_command_output(command: str, raw_output: str) -> str | None:
    """Detect if command has a specialized ultra-dense filter."""
    cmd_lower = command.lower().strip()
    if cmd_lower.startswith("git log"):
        return filter_git_log(raw_output)
    elif cmd_lower.startswith("git status"):
        return filter_git_status(raw_output)
    elif cmd_lower.startswith("cargo test"):
        return filter_cargo_test(raw_output)
    elif cmd_lower.startswith("go test"):
        return filter_go_test(raw_output)
    elif any(
        cmd_lower.startswith(prefix)
        for prefix in (
            "npm test",
            "pnpm test",
            "yarn test",
            "bun test",
            "vitest",
            "npx vitest",
            "jest",
            "npx jest",
        )
    ):
        return filter_jest_vitest(raw_output)
    return None
