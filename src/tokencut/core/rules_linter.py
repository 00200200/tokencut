from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

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
        re.compile(
            r"\b(?:session_id|uuid|request_id)\s*[:=]\s*['\"][0-9a-fA-F-]{16,}['\"]",
            re.IGNORECASE,
        ),
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

    in_dynamic_block = False
    for idx, line in enumerate(lines, 1):
        if "Dynamic Runtime Context" in line or "dynamic context" in line.lower():
            in_dynamic_block = True
            continue
        if in_dynamic_block:
            continue

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


def generate_desktop_rules(client: str = "claude") -> str:
    """Generate concise, cache-friendly instructions for CLAUDE.md or AGENTS.md."""
    if client.lower() in {"codex", "codex-desktop"}:
        return (
            "# TokenCut Codex Rules\n"
            "- Targeted inspection: use `tokencut_code` (outline, symbols, callers) and `tokencut_read` (symbols/ranges) instead of dumping full files.\n"
            "- Precise changes: use `tokencut_edit_symbol` for hash-guarded atomic updates.\n"
            "- Shell execution: use `tokencut_exec` or run `tokencut run -- <cmd>` in terminal to fold build/test noise.\n"
            "- Recovery: if folded diagnostics or logs are needed, call `tokencut_retrieve(ref_id=...)`.\n"
            "- Task memory: save milestone checkpoints with `tokencut_context`.\n"
        )
    return (
        "# TokenCut Claude Rules\n"
        "- Targeted inspection: use `tokencut_code` (symbols, callers, outline) and `tokencut_read` (targeted symbol/lines) rather than dumping full files.\n"
        "- Precise changes: use `tokencut_edit_symbol` for hash-guarded symbol replacements.\n"
        "- Command output: use `tokencut_exec` to collapse routine test and build noise.\n"
        "- Context recovery: use `tokencut_retrieve(ref_id=...)` to retrieve full uncompacted outputs.\n"
        "- Task milestones: save checkpoints with `tokencut_context`.\n"
    )


def optimize_rules(content: str) -> dict[str, Any]:
    """Optimize rules for Claude Desktop (CLAUDE.md) and Codex (AGENTS.md).

    1. Prunes conversational pleasantries and zero-signal boilerplate.
    2. Moves volatile cache-busting tokens (timestamps, ISO dates, session IDs) from prefix
       to a dedicated suffix block so Anthropic and OpenAI prompt caching can hit.
    3. Minifies comments, excess whitespace, and formatting padding.
    """
    orig_tokens = count_tokens(content).avg
    lines = content.splitlines()

    static_lines: list[str] = []
    dynamic_lines: list[str] = []

    simplifications = [
        (
            re.compile(
                r"^\s*You are a (?:helpful|world-class|expert|senior)\s+(?:coding\s+|software\s+)?assistant[^\n]*\.\s*$",
                re.IGNORECASE,
            ),
            "",
        ),
        (
            re.compile(r"\bPlease make sure to always remember to never forget\b", re.IGNORECASE),
            "Always",
        ),
        (re.compile(r"\bPlease (?:ensure|make sure) (?:that you |to )?", re.IGNORECASE), ""),
        (re.compile(r"\bFeel free to\b", re.IGNORECASE), "You may"),
        (re.compile(r"\bKeep in mind that\b", re.IGNORECASE), "Note:"),
        (re.compile(r"\bAs an AI (?:language model|assistant)[^,.]*[,.]", re.IGNORECASE), ""),
    ]

    for line in lines:
        stripped = line.strip()
        clean = re.sub(r"<!--.*?-->", "", stripped).strip()
        if not clean:
            if static_lines and static_lines[-1] != "":
                static_lines.append("")
            continue

        for pat, repl in simplifications:
            clean = pat.sub(repl, clean).strip()

        if not clean:
            continue

        is_dynamic = False
        for pat, _ in CACHE_BUSTING_PATTERNS:
            if pat.search(clean):
                is_dynamic = True
                break

        if is_dynamic:
            dynamic_lines.append(clean)
        else:
            indent = len(line) - len(line.lstrip())
            norm_indent = " " * min(indent, 4)
            static_lines.append(norm_indent + clean)

    optimized_parts = []
    static_text = "\n".join(static_lines).strip()
    if static_text:
        optimized_parts.append(static_text)

    if dynamic_lines:
        dynamic_block = (
            "\n<!-- Dynamic Runtime Context (isolated for prompt caching) -->\n"
            + "\n".join(f"> {line}" for line in dynamic_lines)
        )
        optimized_parts.append(dynamic_block)

    optimized_content = "\n".join(optimized_parts).strip() + "\n"
    opt_tokens = count_tokens(optimized_content).avg
    saved_tokens = max(0, orig_tokens - opt_tokens)
    savings_pct = round((saved_tokens / orig_tokens * 100), 1) if orig_tokens > 0 else 0.0

    lint_res = lint_rule_content(optimized_content)

    return {
        "original_tokens": orig_tokens,
        "optimized_tokens": opt_tokens,
        "saved_tokens": saved_tokens,
        "savings_pct": savings_pct,
        "optimized_content": optimized_content,
        "is_cache_friendly": lint_res.is_cache_friendly,
    }
