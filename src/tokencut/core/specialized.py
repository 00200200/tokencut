from __future__ import annotations

import json
import re

from tokencut.core.diff_slimmer import slim_git_diff
from tokencut.core.json_slimmer import slim_json

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
# Vitest states a per-file test count; Jest prints a bare suite header instead.
_JS_FILE_COUNT_RE = re.compile(r"\((\d+)\s+tests?\)")
_JS_SUITE_RE = re.compile(r"^PASS\s+\S+")


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


# TypeScript compiler outputs multi-line error frames with ASCII squiggles (~~~).
# Compact them into dense single-line error descriptions with exact file, line, col, code, and source snippet.
_TSC_HEADER_RE = re.compile(
    r"^(\S+?)(?::(\d+):(\d+)\s+-\s+error\s+(TS\d+):\s*(.*)|\((\d+),(\d+)\):\s*error\s+(TS\d+):\s*(.*))$"
)
_SQUIGGLE_RE = re.compile(r"^\s*[~^]+\s*$")
_LINE_NUM_CODE_RE = re.compile(r"^\s*\d+\s+(.*)$")


def filter_tsc(raw_output: str) -> str:
    """Compact verbose TypeScript compiler (tsc) output by stripping squiggle underlines and padding."""
    lines = raw_output.splitlines()
    if not any("error TS" in line for line in lines):
        return raw_output

    result: list[str] = []
    current_error = ""
    current_continuations: list[str] = []
    current_source = ""

    def flush_error():
        nonlocal current_error, current_continuations, current_source
        if current_error:
            entry = current_error
            if current_continuations:
                entry += " " + " ".join(current_continuations)
            if current_source:
                entry += f" | `{current_source}`"
            result.append(entry)
        current_error = ""
        current_continuations = []
        current_source = ""

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if _SQUIGGLE_RE.match(stripped):
            continue

        if _TSC_HEADER_RE.match(stripped):
            flush_error()
            current_error = stripped
            continue

        if current_error:
            if stripped.startswith("Found ") or stripped.startswith("==="):
                flush_error()
                result.append(stripped)
            elif _LINE_NUM_CODE_RE.match(stripped):
                current_source = _LINE_NUM_CODE_RE.match(stripped).group(1).strip()
            elif not current_source and not stripped.startswith("error TS"):
                current_continuations.append(stripped)
            else:
                flush_error()
                result.append(line)
        else:
            result.append(line)

    flush_error()
    return "\n".join(result)


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


def filter_json_output(raw_output: str, command: str = "") -> str | None:
    """Automatically slim large or verbose JSON output from commands.

    Targeted for commands like `gh api`, `docker inspect`, `curl`, `kubectl -o json`,
    or any command output that is valid JSON with substantial array or nested structures.
    Full uncompressed payload is cached in SQLite CCR with a recovery reference.
    """
    stripped = raw_output.strip()
    if not (stripped.startswith("{") or stripped.startswith("[")):
        return None

    cmd_lower = command.lower().strip()
    is_explicit_json_cmd = any(
        kw in cmd_lower
        for kw in (
            "gh api",
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
    if cmd_lower.startswith("git log"):
        return filter_git_log(raw_output)
    elif cmd_lower.startswith("git status"):
        return filter_git_status(raw_output)
    elif cmd_lower.startswith(("git diff", "git show")):
        return filter_git_diff(raw_output)
    elif cmd_lower.startswith("cargo test"):
        return filter_cargo_test(raw_output)
    elif any(
        cmd_lower.startswith(prefix)
        for prefix in (
            "cargo build",
            "cargo check",
        )
    ):
        return filter_cargo_build(raw_output)
    elif cmd_lower.startswith("go test"):
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
