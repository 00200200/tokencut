from __future__ import annotations

import re

LOCKFILE_PATTERNS = [
    re.compile(
        r"(?:package-lock\.json|yarn\.lock|pnpm-lock\.yaml|uv\.lock|poetry\.lock|Cargo\.lock|Gemfile\.lock|composer\.lock|go\.sum)"
    ),
    re.compile(r"\.(?:min\.js|min\.css|map|svg|snap)$"),
    re.compile(r"(?:\.pb\.go|_pb2\.py|_pb2_grpc\.py)$"),
]


def is_lockfile_or_generated(filename: str, extra_patterns: list[re.Pattern] | None = None) -> bool:
    if any(p.search(filename) for p in LOCKFILE_PATTERNS):
        return True
    if extra_patterns and any(p.search(filename) for p in extra_patterns):
        return True
    return False


def slim_git_diff(
    raw_diff: str,
    max_context_lines: int = 2,
    extra_patterns: list[str] | None = None,
) -> str:
    """Compress unified git diffs.

    - Detects lockfiles & generated files, collapsing them into concise 1-line notices.
    - Preserves all added (+) and deleted (-) lines and file headers.
    - Suppresses excessive unchanged context lines.
    """
    if not raw_diff:
        return ""

    compiled_extra = [re.compile(p) for p in extra_patterns] if extra_patterns else None

    lines = raw_diff.splitlines()
    output_lines: list[str] = []

    current_file = ""
    is_collapsing_file = False
    collapsed_lines_count = 0

    hunk_context_count = 0

    for line in lines:
        if line.startswith("diff --git"):
            # Flush previous collapsed file notice
            if is_collapsing_file:
                output_lines.append(
                    f"  [... {collapsed_lines_count} lines of lockfile/generated diff omitted by usagetrim ...]\n"
                )
                is_collapsing_file = False
                collapsed_lines_count = 0

            # Extract filename (e.g. diff --git a/foo/bar.py b/foo/bar.py)
            parts = line.split()
            current_file = parts[-1] if len(parts) >= 4 else line
            is_collapsing_file = is_lockfile_or_generated(current_file, compiled_extra)
            output_lines.append(line)
            hunk_context_count = 0
            continue

        if is_collapsing_file:
            collapsed_lines_count += 1
            continue

        if line.startswith("@@"):
            output_lines.append(line)
            hunk_context_count = 0
            continue

        if line.startswith(("+", "-")) and not line.startswith(("+++", "---")):
            output_lines.append(line)
            hunk_context_count = 0
            continue

        # Header lines
        if line.startswith(("index ", "--- ", "+++ ", "new file mode", "deleted file mode")):
            output_lines.append(line)
            continue

        # Unchanged context line (starts with space or empty)
        hunk_context_count += 1
        if hunk_context_count <= max_context_lines:
            output_lines.append(line)
        elif hunk_context_count == max_context_lines + 1:
            output_lines.append("  ...")

    if is_collapsing_file:
        output_lines.append(
            f"  [... {collapsed_lines_count} lines of lockfile/generated diff omitted by usagetrim ...]\n"
        )

    return "\n".join(output_lines)
