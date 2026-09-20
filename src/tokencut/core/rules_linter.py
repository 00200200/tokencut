from __future__ import annotations

import re
from dataclasses import dataclass

from tokencut.metrics.tokenizer import count_tokens

CACHE_BUSTING_PATTERNS = [
    (
        re.compile(
            r"\b(?:current\s+(?:time|date|timestamp)|now\(\)|datetime\.now)\b", re.IGNORECASE
        ),
        "Dynamic timestamp breaks Anthropic / Gemini prompt caching!",
    ),
    (
        re.compile(r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\b"),
        "Hardcoded ISO timestamp in instructions.",
    ),
    (
        re.compile(r"\b(?:session_id|uuid|request_id)\s*[:=]\s*['\"][0-9a-fA-F-]{16,}['\"]"),
        "Dynamic UUID in prompt prefix invalidates prompt cache.",
    ),
]

VERBOSE_BOILERPLATE_PATTERNS = [
    (
        re.compile(
            r"You are a helpful (?:coding )?assistant.*?(?:expert|world-class).*?\.", re.IGNORECASE
        ),
        "Verbose persona intro wastes tokens with zero impact on reasoning.",
    ),
    (
        re.compile(r"Please make sure to always remember to never forget.*?\.", re.IGNORECASE),
        "Hyper-verbose phrasing.",
    ),
]


@dataclass
class RuleIssue:
    line_num: int
    rule_name: str
    message: str
    snippet: str


@dataclass
class LintResult:
    file_path: str
    token_count: int
    line_count: int
    issues: list[RuleIssue]
    is_cache_friendly: bool


def lint_rule_content(content: str, file_name: str = "rules") -> LintResult:
    lines = content.splitlines()
    issues: list[RuleIssue] = []
    is_cache_friendly = True

    for idx, line in enumerate(lines, 1):
        for pat, desc in CACHE_BUSTING_PATTERNS:
            if pat.search(line):
                issues.append(
                    RuleIssue(
                        line_num=idx,
                        rule_name="cache-busting",
                        message=desc,
                        snippet=line.strip()[:60],
                    )
                )
                is_cache_friendly = False

        for pat, desc in VERBOSE_BOILERPLATE_PATTERNS:
            if pat.search(line):
                issues.append(
                    RuleIssue(
                        line_num=idx,
                        rule_name="verbose-boilerplate",
                        message=desc,
                        snippet=line.strip()[:60],
                    )
                )

    # Check consecutive empty lines
    consecutive_empty = 0
    for idx, line in enumerate(lines, 1):
        if not line.strip():
            consecutive_empty += 1
            if consecutive_empty > 2:
                issues.append(
                    RuleIssue(
                        line_num=idx,
                        rule_name="excessive-newlines",
                        message="Multiple blank lines waste tokens",
                        snippet="<blank line>",
                    )
                )
        else:
            consecutive_empty = 0

    tokens = count_tokens(content).avg

    return LintResult(
        file_path=file_name,
        token_count=tokens,
        line_count=len(lines),
        issues=issues,
        is_cache_friendly=is_cache_friendly,
    )


def minify_rules(content: str) -> str:
    """Minify rule markdown while preserving all instructions and formatting semantics."""
    lines = content.splitlines()
    minified_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        # Collapse multiple spaces
        if stripped:
            # Preserve indentation level for markdown lists
            indent = len(line) - len(line.lstrip())
            norm_indent = " " * (indent if indent <= 4 else 2)
            # Remove trailing comments
            clean_line = re.sub(r"\s*<!--.*?-->\s*", "", stripped)
            if clean_line:
                minified_lines.append(norm_indent + clean_line)
        else:
            if minified_lines and minified_lines[-1] != "":
                minified_lines.append("")

    return "\n".join(minified_lines).strip()
