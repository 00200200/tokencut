from __future__ import annotations

import json
import re
import shlex
from pathlib import PurePath

from tokencut.core.cache import ContextCache
from tokencut.core.diff_slimmer import slim_git_diff
from tokencut.core.json_slimmer import slim_json, slim_json_data
from tokencut.core.spill import spill_large_output

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


def filter_git_diff(raw_output: str, max_context_lines: int = 2) -> str:
    """Compact ``git diff`` / ``git show`` payloads via the shared diff slimmer.

    Lockfiles and generated artifacts collapse to a one-line notice; added and
    removed lines in source hunks are preserved. Non-diff output is untouched.
    """
    if not raw_output.strip() or "diff --git" not in raw_output:
        return raw_output
    return slim_git_diff(raw_output, max_context_lines=max_context_lines)


# Cargo / nextest print one progress line per passing test. Collapse those hard,
# keep fail/pass identity + test names + assertion lines, and drop stack frames.
_NEXTEST_PASS = re.compile(r"^PASS\s+\[\s*[0-9.]+s\]\s+.+")
_CARGO_PASS_LINE = re.compile(r"^(?:test \S+ \.\.\. ok|PASS\s+\[\s*[0-9.]+s\]\s+.+)$")
_CARGO_FAILED_LINE = re.compile(r"^(?:test \S+ \.\.\. FAILED|FAIL\s+\[\s*[0-9.]+s\]\s+.+)$")
_CARGO_BACKTRACE_START = re.compile(r"^stack backtrace:\s*$", re.IGNORECASE)
_CARGO_BACKTRACE_NOTE = re.compile(
    r"^note: run with `RUST_BACKTRACE=1` environment variable to display a backtrace\s*$"
)


def _is_cargo_pass_progress(line: str) -> bool:
    return bool(_CARGO_PASS_LINE.fullmatch(line.strip()))


def filter_cargo_test(raw_output: str) -> str:
    """Collapse cargo/nextest pass progress; keep failures dense.

    Passing ``test ... ok`` / nextest ``PASS [..]`` runs collapse to one marker.
    Failed tests keep their status line, name, panic location, and assertion
    (including ``left:`` / ``right:``). Stack backtraces are dropped — they are
    the bulk of the tokens and do not add identity beyond the assertion line.
    Passes that appear after a failure stay as named lines. The trailing
    ``test result:`` / nextest ``Summary`` line is preserved.
    """
    lines = raw_output.splitlines()
    result: list[str] = []
    index = 0
    changed = False
    in_backtrace = False
    seen_failure = False

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        if in_backtrace:
            if (
                stripped.startswith("test ")
                or stripped.startswith("test result:")
                or stripped.startswith("failures:")
                or stripped.startswith("error:")
                or _NEXTEST_PASS.fullmatch(stripped)
                or stripped.startswith("FAIL ")
                or stripped.startswith("Summary ")
                or stripped.startswith("────")
                or stripped.startswith("───")
            ):
                in_backtrace = False
            else:
                changed = True
                index += 1
                continue

        if _CARGO_BACKTRACE_START.match(stripped):
            in_backtrace = True
            changed = True
            index += 1
            continue

        if _CARGO_BACKTRACE_NOTE.match(stripped):
            changed = True
            index += 1
            continue

        if _CARGO_FAILED_LINE.fullmatch(stripped):
            seen_failure = True
            result.append(line)
            index += 1
            continue

        if _is_cargo_pass_progress(line):
            if seen_failure:
                result.append(line)
                index += 1
                continue
            end = index + 1
            while end < len(lines) and _is_cargo_pass_progress(lines[end]):
                end += 1
            passed = end - index
            result.append(f"[TokenCut: {passed} passing tests, {passed} progress records]")
            changed = True
            index = end
            continue

        result.append(line)
        index += 1

    if not changed:
        return raw_output
    return "\n".join(result)


# Go test outputs pairs or lines of '=== RUN' and '--- PASS:'.
# Keep --- FAIL / panic assertion lines; drop goroutine stack dumps.
_GO_TEST_OK = re.compile(r"^\s*(?:=== RUN\s+\S+|--- PASS:\s+\S+\s+\([0-9.]+s\))$")
_GO_PASS_RECORD = re.compile(r"^\s*--- PASS:\s+\S+\s+\([0-9.]+s\)")
_GO_GOROUTINE = re.compile(r"^goroutine \d+ \[")
_GO_STACK_FILE = re.compile(r"^\S+\.go:\d+\s+\+0x[0-9a-fA-F]+")
_GO_STACK_FUNC = re.compile(r"^[0-9a-zA-Z_./\-]+(?:\.|·|/)\S*\(.*\)\s*$")


def filter_go_test(raw_output: str) -> str:
    """Collapse passing go test records; keep fail identity and panic lines dense."""
    lines = raw_output.splitlines()
    result: list[str] = []
    index = 0
    changed = False
    in_stack = False

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        if in_stack:
            if (
                stripped.startswith("=== ")
                or stripped.startswith("--- ")
                or stripped.startswith("panic:")
                or stripped == "PASS"
                or stripped == "FAIL"
                or stripped.startswith("FAIL\t")
                or stripped.startswith("ok\t")
                or stripped.startswith("PASS\t")
            ):
                in_stack = False
            elif (
                _GO_GOROUTINE.match(stripped)
                or _GO_STACK_FILE.match(stripped)
                or _GO_STACK_FUNC.match(stripped)
                or stripped.startswith("created by ")
            ):
                changed = True
                index += 1
                continue
            else:
                # Unknown stack-adjacent noise — drop while in a dump.
                changed = True
                index += 1
                continue

        if _GO_GOROUTINE.match(stripped):
            in_stack = True
            changed = True
            index += 1
            continue

        if _GO_TEST_OK.match(stripped):
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
                changed = True
                index = end
                continue
            result.extend(chunk)
            index = end
            continue

        result.append(line)
        index += 1

    if not changed:
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
# Jest console.* dumps and Vitest stdout| / stderr| / ● Console blocks.
_JS_CONSOLE_HEAD = re.compile(
    r"^\s*(?:"
    r"console\.(?:log|info|debug|warn|error|dir|table|trace)\b|"
    r"stdout\s*\||"
    r"stderr\s*\||"
    r"●\s*Console"
    r")\s*"
)
_JS_SUMMARY = re.compile(r"^\s*(?:Test (?:Suites|Files)|Tests|Snapshots|Time|Duration|Start at)\b")
_JS_FAIL_SUITE = re.compile(r"^\s*(?:FAIL\s+\S+|✕|×)")
# Vitest states a per-file test count; Jest prints a bare suite header instead.
_JS_FILE_COUNT_RE = re.compile(r"\((\d+)\s+tests?\)")
_JS_SUITE_RE = re.compile(r"^PASS\s+\S+")


def _js_console_head(line: str) -> bool:
    return bool(_JS_CONSOLE_HEAD.match(line.strip()))


def _js_hard_boundary(line: str) -> bool:
    """Suite/test/summary lines that end console folding (not another console dump)."""
    stripped = line.strip()
    if not stripped:
        return False
    return bool(
        _JS_TEST_OK.match(stripped) or _JS_FAIL_SUITE.match(stripped) or _JS_SUMMARY.match(stripped)
    )


def _js_should_keep_verbatim(line: str) -> bool:
    """True when the rest of the run must stay untouched (real failure signal).

    ``console.error`` must not trip this: ``\\bError\\b`` matches inside it under
    IGNORECASE, which used to freeze filtering for the rest of the log.
    """
    stripped = line.strip()
    if not stripped or _JS_TEST_OK.match(stripped) or _JS_CONSOLE_HEAD.match(stripped):
        return False
    if _JS_FAIL_SUITE.match(stripped):
        return True
    return bool(_JS_DIAGNOSTIC.search(line))


def _summarize_js_records(chunk: list[str]) -> str:
    """Describe a collapsed run without inflating the test count.

    A per-file record already accounts for the individual records printed beneath
    it, so the two are never added together. Counts that the output does not state
    are reported as files rather than guessed at.
    """
    declared = 0
    counted_files = 0
    bare_files = 0
    individual = 0

    for raw_line in chunk:
        line = raw_line.strip()
        match = _JS_FILE_COUNT_RE.search(line)
        if match:
            declared += int(match.group(1))
            counted_files += 1
        elif _JS_SUITE_RE.match(line):
            bare_files += 1
        else:
            individual += 1

    def plural(count: int, noun: str) -> str:
        return f"{count} {noun}" if count == 1 else f"{count} {noun}s"

    if not counted_files and not bare_files:
        return f"{individual} passing tests"
    if not counted_files:
        return f"{plural(bare_files, 'passing test file')}"
    if bare_files:
        return f"{declared} passing tests and {plural(bare_files, 'more test file')}"
    return f"{declared} passing tests in {plural(counted_files, 'file')}"


def filter_jest_vitest(raw_output: str) -> str:
    """Collapse passing Jest/Vitest records and console dumps; keep failures dense."""
    lines = raw_output.splitlines()
    result: list[str] = []
    index = 0
    collapsed = False

    while index < len(lines):
        line = lines[index]

        if _js_should_keep_verbatim(line):
            result.extend(lines[index:])
            break

        if _js_console_head(line):
            end = index + 1
            while end < len(lines):
                nxt = lines[end]
                if _js_hard_boundary(nxt):
                    break
                if _js_console_head(nxt):
                    end += 1
                    continue
                if not nxt.strip():
                    look = end + 1
                    while look < len(lines) and not lines[look].strip():
                        look += 1
                    if look >= len(lines) or _js_hard_boundary(lines[look]):
                        break
                end += 1
            omitted = end - index
            result.append(f"[TokenCut: {omitted} console lines omitted]")
            collapsed = True
            index = end
            continue

        if _JS_TEST_OK.match(line.strip()):
            end = index + 1
            while end < len(lines):
                if not _JS_TEST_OK.match(lines[end].strip()):
                    break
                end += 1
            records = end - index
            summary = _summarize_js_records(lines[index:end])
            result.append(f"[TokenCut: {summary}, {records} progress records]")
            collapsed = True
            index = end
            continue

        result.append(line)
        index += 1

    if not collapsed:
        return raw_output
    return "\n".join(result)


# TypeScript compiler pretty mode repeats source frames, squiggles, and nested
# type notes. Keep one dense row per unique diagnostic: file, line, rule, message.
_TSC_HEADER_RE = re.compile(
    r"^(\S+?):(\d+):(\d+)\s+-\s+error\s+(TS\d+):\s*(.*)$|"
    r"^(\S+?)\((\d+),(\d+)\):\s*error\s+(TS\d+):\s*(.*)$"
)
_SQUIGGLE_RE = re.compile(r"^\s*[~^]+\s*$")
_TSC_FRAME_LINE_RE = re.compile(r"^(?:>\s*)?\d+\s+\||^[|\s~^]+$")
_TSC_SUMMARY_RE = re.compile(r"^Found \d+ errors?\b")
_TSC_FILE_TABLE_RE = re.compile(r"^(Errors\s+Files|\s+\d+\s+\S+:\d+\s*)$")


def filter_tsc(raw_output: str) -> str:
    """Compact verbose tsc pretty output into dense unique diagnostics."""
    lines = raw_output.splitlines()
    if not any("error TS" in line for line in lines):
        return raw_output

    result: list[str] = []
    seen: set[str] = set()
    summary: str | None = None

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if _SQUIGGLE_RE.match(stripped) or _TSC_FRAME_LINE_RE.match(stripped):
            continue
        if _TSC_FILE_TABLE_RE.match(stripped):
            continue

        header = _TSC_HEADER_RE.match(stripped)
        if header:
            if header.group(1) is not None:
                path, lineno, col, code, message = header.group(1, 2, 3, 4, 5)
            else:
                path, lineno, col, code, message = header.group(6, 7, 8, 9, 10)
            entry = f"{path}:{lineno}:{col} {code} {message.strip()}"
            if entry not in seen:
                seen.add(entry)
                result.append(entry)
            continue

        if _TSC_SUMMARY_RE.match(stripped):
            summary = stripped
            continue

        # Drop nested type-continuation notes and leftover pretty padding.
        if stripped.startswith("Type ") or stripped.startswith("Type '"):
            continue

    if summary:
        result.append(summary)
    return "\n".join(result) if result else raw_output


# Ruff's default ``full`` format repeats source frames and caret underlines for
# every diagnostic. Keep the actionable header + optional help; drop the frame.
_RUFF_HEADER_RE = re.compile(r"^(\S+:\d+:\d+:\s+[A-Z]\d+\b.*)$")
_RUFF_HELP_RE = re.compile(r"^=\s*help:\s*(.+)$")
_RUFF_FRAME_LINE_RE = re.compile(r"^(?:\||\d+\s+\||[\^~]+)$|^(?:\||\d+\s+\|)")


def filter_ruff(raw_output: str) -> str:
    """Compact verbose Ruff ``full`` frames into dense single-line diagnostics."""
    lines = raw_output.splitlines()
    if not any(_RUFF_HEADER_RE.match(line.strip()) for line in lines):
        return raw_output

    result: list[str] = []
    current: str | None = None

    def flush():
        nonlocal current
        if current is not None:
            result.append(current)
            current = None

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        help_match = _RUFF_HELP_RE.match(stripped)
        if help_match and current is not None:
            current = f"{current} | help: {help_match.group(1).strip()}"
            continue

        if _RUFF_HEADER_RE.match(stripped):
            flush()
            current = stripped
            continue

        if current is not None and _RUFF_FRAME_LINE_RE.match(stripped):
            continue

        flush()
        result.append(stripped)

    flush()
    return "\n".join(result)


# BuildKit / docker build print one progress stream per step (`#12 ...`). Collapse
# routine progress; once a failure or final image tag appears, keep it intact.
_DOCKER_STEP_RE = re.compile(r"^#\d+\s")
_DOCKER_KEEP_RE = re.compile(
    r"(?i)(?:\berror\b|failed to solve|successfully tagged|"
    r"writing image sha256|naming to\s+\S+)"
)


def filter_docker_build(raw_output: str) -> str:
    """Collapse BuildKit layer progress while keeping failures and final tags."""
    if not raw_output.strip():
        return raw_output

    lines = raw_output.splitlines()
    if not any(_DOCKER_STEP_RE.match(line) for line in lines):
        return raw_output

    result: list[str] = []
    progress = 0
    collapsed = False

    def flush_progress() -> None:
        nonlocal progress, collapsed
        if progress:
            result.append(f"[TokenCut: {progress} docker build progress lines]")
            progress = 0
            collapsed = True

    for index, line in enumerate(lines):
        if _DOCKER_KEEP_RE.search(line):
            flush_progress()
            # Failures and their trailing detail blocks stay verbatim.
            if re.search(r"(?i)\berror\b|failed to solve", line):
                result.extend(lines[index:])
                collapsed = True
                break
            result.append(line)
            continue

        if _DOCKER_STEP_RE.match(line):
            progress += 1
            continue

        flush_progress()
        result.append(line)

    flush_progress()
    if not collapsed:
        return raw_output
    return "\n".join(result)


# Pyright/basedpyright print a dense header, then indented path + source + caret.
_PYRIGHT_DIAG_RE = re.compile(
    r"^(\S+?:\d+:\d+ - (?:error|warning|information): .+)$",
    re.IGNORECASE,
)
_PYRIGHT_SUMMARY_RE = re.compile(
    r"^\d+ errors?, \d+ warnings?, \d+ informations?\s*$",
    re.IGNORECASE,
)


def filter_pyright(raw_output: str) -> str:
    """Compact Pyright source frames into dense diagnostic headers."""
    lines = raw_output.splitlines()
    if not any(_PYRIGHT_DIAG_RE.match(line.strip()) for line in lines):
        return raw_output

    result: list[str] = []
    changed = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if _PYRIGHT_DIAG_RE.match(stripped) or _PYRIGHT_SUMMARY_RE.match(stripped):
            result.append(stripped)
            continue
        if line[:1].isspace():
            changed = True
            continue
        result.append(stripped)

    if not changed:
        return raw_output
    return "\n".join(result)


# ESLint stylish (default) prints an absolute path header then padded columns.
# Codeframe embeds source lines and caret underlines. Collapse both to dense
# ``file:line:col severity message rule`` rows while keeping the summary.
_ESLINT_STYLISH_DIAG_RE = re.compile(r"^(\d+):(\d+)\s+(error|warning|info)\s+(.+?)\s{2,}(\S+)\s*$")
_ESLINT_CODEFRAME_RE = re.compile(
    r"^(error|warning|info):\s+(.+?)\s+\(([^)]+)\)\s+at\s+(\S+):(\d+):(\d+):?\s*$"
)
_ESLINT_SUMMARY_RE = re.compile(r"^[✖×]\s+\d+\s+problems?\b")
_ESLINT_FIXABLE_RE = re.compile(r"potentially fixable with the `--fix` option")
_ESLINT_FRAME_LINE_RE = re.compile(r"^(?:>\s*)?\d+\s+\||^[|\s^~]+$")
_ESLINT_PATH_RE = re.compile(r"^(?:[A-Za-z]:)?[\\/].+\.[A-Za-z0-9]+$|^[^:\s].+\.[A-Za-z0-9]+$")


def _eslint_relpath(path: str) -> str:
    """Prefer a repo-relative looking suffix when stylish prints absolute paths."""
    normalized = path.replace("\\", "/")
    # Already relative — keep the full project path for actionable locations.
    if not normalized.startswith("/") and not re.match(r"^[A-Za-z]:/", normalized):
        return path
    markers = ("/src/", "/lib/", "/app/", "/apps/", "/packages/", "/test/", "/tests/")
    for marker in markers:
        idx = normalized.find(marker)
        if idx != -1:
            return normalized[idx + 1 :]
    return normalized.rsplit("/", 1)[-1]


# mypy --pretty repeats source/caret frames under each diagnostic.
# Keep error/note headers (with codes); drop the pretty frame body.
_MYPY_DIAG_RE = re.compile(r"^(\S+:\d+:(?:\d+:)?\s+(?:error|warning|note|unreachable):\s+.+)$")


def filter_mypy(raw_output: str) -> str:
    """Compact mypy ``--pretty`` frames into dense diagnostics with codes kept."""
    lines = raw_output.splitlines()
    if not any(
        ": error:" in line or ": warning:" in line or ": note:" in line or ": unreachable:" in line
        for line in lines
    ):
        return raw_output

    result: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if _MYPY_DIAG_RE.match(stripped):
            result.append(stripped)
            continue
        if stripped.startswith(("Found ", "Success:")):
            result.append(stripped)
            continue
        # Drop pretty source context and caret underlines.
        continue

    return "\n".join(result)


def filter_eslint(raw_output: str) -> str:
    """Compact verbose ESLint stylish/codeframe output into dense unique diagnostics."""
    lines = raw_output.splitlines()
    has_stylish = any(_ESLINT_STYLISH_DIAG_RE.match(line.strip()) for line in lines)
    has_codeframe = any(_ESLINT_CODEFRAME_RE.match(line.strip()) for line in lines)
    if not has_stylish and not has_codeframe:
        return raw_output

    result: list[str] = []
    seen: set[str] = set()
    current_file: str | None = None
    summary: str | None = None

    def add(entry: str) -> None:
        if entry not in seen:
            seen.add(entry)
            result.append(entry)

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # Stack frames and codeframe source rows are pure noise for agents.
        if stripped.startswith("at ") or _ESLINT_FRAME_LINE_RE.match(stripped):
            continue
        if _ESLINT_FIXABLE_RE.search(stripped):
            continue

        codeframe = _ESLINT_CODEFRAME_RE.match(stripped)
        if codeframe:
            severity, message, rule, path, lineno, col = codeframe.groups()
            add(f"{_eslint_relpath(path)}:{lineno}:{col} {severity} {message} ({rule})")
            current_file = None
            continue

        stylish = _ESLINT_STYLISH_DIAG_RE.match(stripped)
        if stylish and current_file is not None:
            lineno, col, severity, message, rule = stylish.groups()
            add(f"{current_file}:{lineno}:{col} {severity} {message.strip()} {rule}")
            continue

        if _ESLINT_SUMMARY_RE.match(stripped):
            summary = stripped
            current_file = None
            continue

        # Stylish file headers: a bare path line before indented diagnostics.
        if has_stylish and _ESLINT_PATH_RE.match(stripped) and not re.search(r":\d+:\d+", stripped):
            current_file = _eslint_relpath(stripped)
            continue

    if summary:
        result.append(summary)
    return "\n".join(result) if result else raw_output


_GH_BODY_KEYS = frozenset({"body", "bodyText", "messageBody", "text"})
_GH_ARRAY_CAPS = {
    "commits": 5,
    "files": 8,
    "reviews": 3,
    "comments": 3,
    "labels": 8,
    "assignees": 5,
    "reviewRequests": 5,
    "statusCheckRollup": 5,
}
_GH_TEXT_BODY_KEEP = 600


def _gh_argv(command: str) -> list[str] | None:
    if not command or "\n" in command:
        return None
    try:
        words = shlex.split(command)
    except ValueError:
        return None
    return words or None


def _is_gh_command(command: str) -> bool:
    words = _gh_argv(command)
    return bool(words) and PurePath(words[0]).name == "gh"


def _is_gh_json_command(command: str) -> bool:
    """Recognize ``gh api`` and any ``gh … --json`` invocation."""
    words = _gh_argv(command)
    if not words or PurePath(words[0]).name != "gh":
        return False
    if len(words) >= 2 and words[1] == "api":
        return True
    return any(word == "--json" or word.startswith("--json=") for word in words[1:])


def _is_gh_text_view_command(command: str) -> bool:
    words = _gh_argv(command)
    if not words or PurePath(words[0]).name != "gh" or len(words) < 3:
        return False
    if any(word == "--json" or word.startswith("--json=") for word in words[1:]):
        return False
    return words[1] in {"pr", "issue"} and words[2] == "view"


def _truncate_gh_string(value: str, limit: int = 400) -> str:
    if len(value) <= limit:
        return value
    omitted = len(value) - limit
    return value[:limit] + f"... [{omitted} chars omitted]"


def _slim_gh_payload(data: object) -> object:
    """Prefer PR/issue signal fields; cap noisy arrays and long markdown bodies."""
    if isinstance(data, list):
        cap = 5
        kept = [_slim_gh_payload(item) for item in data[:cap]]
        if len(data) > cap:
            kept.append(f"... {len(data) - cap} array items omitted by tokencut ...")
        return kept

    if not isinstance(data, dict):
        if isinstance(data, str):
            return _truncate_gh_string(data, 120)
        return data

    result: dict[str, object] = {}
    for key, value in data.items():
        if key in {"author", "user", "editor", "mergedBy"} and isinstance(value, dict):
            login = value.get("login")
            result[key] = {"login": login} if isinstance(login, str) else _slim_gh_payload(value)
            continue
        if key in _GH_BODY_KEYS and isinstance(value, str):
            result[key] = _truncate_gh_string(value, 400)
            continue
        if key == "commits" and isinstance(value, list):
            cap = _GH_ARRAY_CAPS["commits"]
            commits = []
            for item in value[:cap]:
                if isinstance(item, dict):
                    commits.append(
                        {
                            "oid": item.get("oid") or item.get("sha"),
                            "messageHeadline": item.get("messageHeadline")
                            or item.get("message_headline")
                            or item.get("message"),
                        }
                    )
                else:
                    commits.append(_slim_gh_payload(item))
            if len(value) > cap:
                commits.append(f"... {len(value) - cap} array items omitted by tokencut ...")
            result[key] = commits
            continue
        if key == "files" and isinstance(value, list):
            cap = _GH_ARRAY_CAPS["files"]
            files = []
            for item in value[:cap]:
                if isinstance(item, dict):
                    files.append(
                        {
                            "path": item.get("path") or item.get("filename"),
                            "additions": item.get("additions"),
                            "deletions": item.get("deletions"),
                        }
                    )
                else:
                    files.append(_slim_gh_payload(item))
            if len(value) > cap:
                files.append(f"... {len(value) - cap} array items omitted by tokencut ...")
            result[key] = files
            continue
        if key == "labels" and isinstance(value, list):
            names: list[object] = []
            for item in value[: _GH_ARRAY_CAPS["labels"]]:
                if isinstance(item, dict) and isinstance(item.get("name"), str):
                    names.append(item["name"])
                elif isinstance(item, str):
                    names.append(item)
                else:
                    names.append(_slim_gh_payload(item))
            if len(value) > _GH_ARRAY_CAPS["labels"]:
                names.append(f"... {len(value) - _GH_ARRAY_CAPS['labels']} labels omitted ...")
            result[key] = names
            continue
        if key in _GH_ARRAY_CAPS and isinstance(value, list):
            cap = _GH_ARRAY_CAPS[key]
            kept = [_slim_gh_payload(item) for item in value[:cap]]
            if len(value) > cap:
                kept.append(f"... {len(value) - cap} array items omitted by tokencut ...")
            result[key] = kept
            continue
        result[key] = _slim_gh_payload(value)
    return result


def filter_gh_text_view(raw_output: str) -> str | None:
    """Fold long markdown bodies from ``gh pr view`` / ``gh issue view`` text mode."""
    if not raw_output.strip():
        return None
    lines = raw_output.splitlines()
    meta: list[str] = []
    body_start = 0
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            body_start = index + 1
            break
        # gh prints ``key:\tvalue`` metadata before the blank-line-separated body.
        if ":\t" in line or (":" in line and index < 12):
            meta.append(line)
            body_start = index + 1
            continue
        body_start = index
        break
    else:
        return None

    body = "\n".join(lines[body_start:])
    if len(body) < _GH_TEXT_BODY_KEEP + 200:
        return None

    kept = body[:_GH_TEXT_BODY_KEEP].rstrip()
    omitted = len(body) - len(kept)
    parts = meta + [
        "",
        kept,
        f"[TokenCut: {omitted} body chars omitted; full output recoverable via spill/CCR]",
    ]
    return "\n".join(parts)


def filter_gh_command_output(command: str, raw_output: str) -> str | None:
    """Specialize ``gh pr view`` / ``gh api`` (and related) with JSON spill + slim.

    Large JSON payloads are written to the spill directory and CCR, then replaced
    with a structured slim that keeps PR/issue signal fields. Text-mode
    ``gh pr|issue view`` folds oversized markdown bodies.
    """
    if not raw_output or not _is_gh_command(command):
        return None

    stripped = raw_output.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            parsed = json.loads(stripped)
        except (json.JSONDecodeError, ValueError):
            parsed = None
        if parsed is not None:
            slimmed_data = _slim_gh_payload(parsed)
            # Fall back to generic depth/string limits for residual nesting.
            slimmed_data = slim_json_data(
                slimmed_data, max_array_items=3, max_string_len=120, max_depth=6
            )
            slimmed = json.dumps(slimmed_data, indent=2)
            explicit = _is_gh_json_command(command)
            if not explicit and len(slimmed) > len(raw_output) * 0.85:
                return None

            spilled = spill_large_output(raw_output, source="gh-json")
            if spilled is not None:
                header = (
                    f"[TokenCut spill: {spilled.bytes_written:,} bytes → {spilled.path}]\n"
                    f"// [tokencut: raw JSON ({len(raw_output):,} bytes) compacted. "
                    f"Ref: {spilled.ref_id}]\n"
                )
            else:
                ref_id = ContextCache().store(raw_output, source="gh-json")
                header = (
                    f"// [tokencut: raw JSON ({len(raw_output):,} bytes) compacted. "
                    f"Ref: {ref_id}]\n"
                )
            return header + slimmed

    if _is_gh_text_view_command(command):
        return filter_gh_text_view(raw_output)
    return None


def filter_json_output(raw_output: str, command: str = "") -> str | None:
    """Automatically slim large or verbose JSON output from commands.

    Targeted for commands like `gh api`, `gh pr view --json`, `docker inspect`,
    `curl`, `kubectl -o json`, or any command output that is valid JSON with
    substantial array or nested structures. Full uncompressed payload is cached
    in SQLite CCR with a recovery reference.
    """
    stripped = raw_output.strip()
    if not (stripped.startswith("{") or stripped.startswith("[")):
        return None

    cmd_lower = command.lower().strip()
    is_explicit_json_cmd = any(
        kw in cmd_lower
        for kw in (
            "gh api",
            "gh pr",
            "gh issue",
            "--json",
            "docker inspect",
            "podman inspect",
            "-o json",
            "-o=json",
            "--format json",
            "--format=json",
            "--output json",
            "--output=json",
        )
    )

    # For general commands, avoid compacting small objects or short responses (< 10 lines and < 300 chars)
    if not is_explicit_json_cmd and len(stripped) < 300 and stripped.count("\n") < 10:
        return None

    try:
        json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        return None

    slimmed = slim_json(raw_output, max_array_items=3, cache_full=True)
    # Only return specialized output if we actually achieved significant reduction (>= 15%)
    if len(slimmed) <= len(raw_output) * 0.85:
        return slimmed

    return None


_CARGO_STEP_RE = re.compile(
    r"^\s*(?:Compiling|Downloading|Checking)\s+([a-zA-Z0-9_-]+)\s+v([^\s]+)"
)


def filter_cargo_build(raw_output: str) -> str:
    """Compact cargo build / cargo check output, suppressing routine compilation lines."""
    if not raw_output.strip():
        return raw_output

    lines = raw_output.splitlines()
    result: list[str] = []
    compiled_crates: list[str] = []

    def flush_crates():
        nonlocal compiled_crates
        if compiled_crates:
            if len(compiled_crates) > 2:
                result.append(f"[TokenCut: compiled/checked {len(compiled_crates)} crates]")
            else:
                for c in compiled_crates:
                    result.append(f"   Compiling {c}")
            compiled_crates = []

    for line in lines:
        m = _CARGO_STEP_RE.match(line)
        if m:
            compiled_crates.append(f"{m.group(1)} v{m.group(2)}")
            continue

        flush_crates()
        result.append(line)

    flush_crates()
    return "\n".join(result)


_PIP_PROGRESS_RE = re.compile(r"^\s*(?:━+|\|+|\d+%).*(?:kB/s|MB/s|eta)")
_PIP_COLLECTING_RE = re.compile(r"^\s*Collecting\s+([a-zA-Z0-9_.-]+)")
_PIP_DOWNLOAD_RE = re.compile(r"^\s*(?:Downloading|Using cached)\s+([a-zA-Z0-9_.-]+)")
_PIP_SATISFIED_RE = re.compile(r"^\s*Requirement already satisfied:\s+([a-zA-Z0-9_.-]+)")


def _normalize_pip_pkg(raw: str) -> str:
    base = re.split(r"[><=~;\[\s]", raw)[0]
    base = base.split("-")[0]
    return base.lower()


def filter_pip_install(raw_output: str) -> str:
    """Compact pip / uv pip install output, suppressing progress bars and download lines."""
    if not raw_output.strip():
        return raw_output

    lines = raw_output.splitlines()
    result: list[str] = []
    downloaded_pkgs: set[str] = set()
    satisfied_count = 0

    def flush_downloads():
        nonlocal downloaded_pkgs
        if downloaded_pkgs:
            result.append(f"[TokenCut: resolved/downloaded {len(downloaded_pkgs)} packages]")
            downloaded_pkgs = set()

    def flush_satisfied():
        nonlocal satisfied_count
        if satisfied_count > 0:
            result.append(f"[TokenCut: {satisfied_count} requirements already satisfied]")
            satisfied_count = 0

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        if _PIP_PROGRESS_RE.search(stripped):
            continue

        m_sat = _PIP_SATISFIED_RE.match(stripped)
        if m_sat:
            flush_downloads()
            satisfied_count += 1
            continue

        m_coll = _PIP_COLLECTING_RE.match(stripped)
        if m_coll:
            flush_satisfied()
            downloaded_pkgs.add(_normalize_pip_pkg(m_coll.group(1)))
            continue

        m_down = _PIP_DOWNLOAD_RE.match(stripped)
        if m_down:
            flush_satisfied()
            downloaded_pkgs.add(_normalize_pip_pkg(m_down.group(1)))
            continue

        if stripped.startswith("Installing collected packages:"):
            flush_downloads()
            flush_satisfied()
            result.append(stripped)
            continue

        flush_downloads()
        flush_satisfied()
        result.append(line)

    flush_downloads()
    flush_satisfied()
    return "\n".join(result)


_NPM_WARN_DEPRECATED = re.compile(r"^\s*npm\s+warn\s+deprecated\s+(.*)")


def filter_npm_install(raw_output: str) -> str:
    """Compact npm/pnpm/yarn install output, grouping routine deprecations and funding messages."""
    if not raw_output.strip():
        return raw_output

    lines = raw_output.splitlines()
    result: list[str] = []
    deprecations: list[str] = []

    def flush_deprecations():
        nonlocal deprecations
        if deprecations:
            if len(deprecations) > 2:
                result.append(
                    f"[TokenCut: {len(deprecations)} package deprecation warnings collapsed]"
                )
            else:
                for d in deprecations:
                    result.append(f"npm warn deprecated {d}")
            deprecations = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        m_dep = _NPM_WARN_DEPRECATED.match(stripped)
        if m_dep:
            deprecations.append(m_dep.group(1))
            continue

        if "packages are looking for funding" in stripped or stripped.startswith("run `npm fund`"):
            flush_deprecations()
            continue

        flush_deprecations()
        result.append(line)

    flush_deprecations()
    return "\n".join(result)


def auto_specialize_command_output(command: str, raw_output: str) -> str | None:
    """Detect if command has a specialized ultra-dense filter."""
    cmd_lower = command.lower().strip()
    cargo_sub = _cargo_subcommand(command.strip())
    gh_compact = filter_gh_command_output(command, raw_output)
    if gh_compact is not None:
        return gh_compact
    if cmd_lower.startswith("git log"):
        return filter_git_log(raw_output)
    elif cmd_lower.startswith("git status"):
        return filter_git_status(raw_output)
    elif cmd_lower.startswith(("git diff", "git show")):
        return filter_git_diff(raw_output)
    elif cargo_sub in {"test", "nextest"}:
        return filter_cargo_test(raw_output)
    elif cargo_sub in {"build", "check"}:
        return filter_cargo_build(raw_output)
    elif _is_go_test_command(command.strip()):
        return filter_go_test(raw_output)
    elif any(
        cmd_lower.startswith(prefix)
        for prefix in (
            "pip install",
            "pip3 install",
            "uv pip install",
            "poetry add",
            "poetry install",
        )
    ) or any(kw in cmd_lower for kw in ("python -m pip install", "python3 -m pip install")):
        return filter_pip_install(raw_output)
    elif any(
        cmd_lower.startswith(prefix)
        for prefix in (
            "npm test",
            "npm run test",
            "pnpm test",
            "pnpm run test",
            "yarn test",
            "yarn run test",
            "bun test",
            "bun run test",
            "vitest",
            "npx vitest",
            "jest",
            "npx jest",
        )
    ):
        return filter_jest_vitest(raw_output)
    elif any(
        cmd_lower.startswith(prefix)
        for prefix in (
            "npm install",
            "npm i ",
            "pnpm install",
            "pnpm i ",
            "pnpm add",
            "yarn add",
            "yarn install",
            "bun add",
            "bun install",
        )
    ) or cmd_lower in ("npm i", "pnpm i", "yarn", "pnpm install", "npm install"):
        return filter_npm_install(raw_output)
    elif any(
        cmd_lower.startswith(prefix)
        for prefix in (
            "tsc",
            "npx tsc",
            "pnpm tsc",
            "yarn tsc",
            "bun x tsc",
        )
    ):
        return filter_tsc(raw_output)
    elif _is_mypy_command(cmd_lower):
        return filter_mypy(raw_output)
    elif _is_eslint_command(cmd_lower):
        return filter_eslint(raw_output)
    elif _is_ruff_command(cmd_lower):
        return filter_ruff(raw_output)
    elif _is_docker_build_command(cmd_lower):
        return filter_docker_build(raw_output)
    elif _is_pyright_command(cmd_lower):
        return filter_pyright(raw_output)

    # Check for large or verbose JSON output
    json_result = filter_json_output(raw_output, command=command)
    if json_result is not None:
        return json_result

    return None


_CARGO_VALUE_FLAGS = frozenset(
    {
        "--manifest-path",
        "--target",
        "--target-dir",
        "--color",
        "--config",
        "-Z",
        "--profile",
        "--package",
        "-p",
        "--features",
        "--bin",
        "--example",
        "--test",
        "--bench",
        "--message-format",
        "--jobs",
        "-j",
    }
)


def _cargo_subcommand(command: str) -> str | None:
    """Return cargo's subcommand (``test``, ``nextest``, ``build``, …) or None."""
    try:
        words = shlex.split(command)
    except ValueError:
        return None
    if not words or PurePath(words[0]).name.lower() not in {"cargo", "cargo.exe"}:
        return None
    index = 1
    while index < len(words):
        word = words[index]
        if word == "--":
            return None
        if word.startswith("+"):
            index += 1
            continue
        if word in _CARGO_VALUE_FLAGS:
            index += 2
            continue
        if word.startswith("--") and "=" in word:
            index += 1
            continue
        if word.startswith("-"):
            index += 1
            continue
        return word.lower()
    return None


def _is_go_test_command(command: str) -> bool:
    """Recognize ``go test`` including absolute paths to the go binary."""
    try:
        words = shlex.split(command)
    except ValueError:
        return False
    if len(words) < 2:
        return False
    return PurePath(words[0]).name.lower() in {"go", "go.exe"} and words[1] == "test"


def _is_mypy_command(cmd_lower: str) -> bool:
    """Recognize direct and common launcher forms for mypy."""
    prefixes = (
        "mypy",
        "uv run mypy",
        "uvx mypy",
        "python -m mypy",
        "python3 -m mypy",
        "poetry run mypy",
        "pipenv run mypy",
    )
    return any(
        cmd_lower == prefix
        or cmd_lower.startswith(prefix + " ")
        or cmd_lower.startswith(prefix + "\t")
        for prefix in prefixes
    )


def _is_eslint_command(cmd_lower: str) -> bool:
    """Recognize direct and common launcher forms for ESLint."""
    prefixes = (
        "eslint ",
        "eslint\t",
        "npx eslint",
        "pnpm eslint",
        "yarn eslint",
        "bunx eslint",
        "bun x eslint",
        "npm exec eslint",
    )
    if cmd_lower == "eslint" or any(cmd_lower.startswith(prefix) for prefix in prefixes):
        return True
    return False


def _is_ruff_command(cmd_lower: str) -> bool:
    """Recognize direct and common launcher forms for Ruff."""
    prefixes = (
        "ruff ",
        "ruff\t",
        "uv run ruff",
        "uvx ruff",
        "python -m ruff",
        "python3 -m ruff",
    )
    if cmd_lower == "ruff" or any(cmd_lower.startswith(prefix) for prefix in prefixes):
        return True
    return False


def _is_docker_build_command(cmd_lower: str) -> bool:
    """Recognize docker/podman build and buildx build forms."""
    prefixes = (
        "docker build",
        "docker buildx build",
        "docker-compose build",
        "docker compose build",
        "podman build",
        "podman buildx build",
    )
    return any(cmd_lower == prefix or cmd_lower.startswith(prefix + " ") for prefix in prefixes)


def _is_pyright_command(cmd_lower: str) -> bool:
    """Recognize Pyright and basedpyright, including npx/pnpm/yarn launchers."""
    prefixes = (
        "pyright",
        "basedpyright",
        "npx pyright",
        "npx basedpyright",
        "pnpm pyright",
        "pnpm exec pyright",
        "yarn pyright",
        "yarn exec pyright",
        "bunx pyright",
        "bunx basedpyright",
    )
    return any(
        cmd_lower == prefix
        or cmd_lower.startswith(prefix + " ")
        or cmd_lower.startswith(prefix + "\t")
        for prefix in prefixes
    )
