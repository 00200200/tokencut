"""Prompt cache aligner and cacheability optimizer for Anthropic, OpenAI, and Gemini prompt caching."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from usagetrim.metrics.tokenizer import count_tokens

_TIMESTAMP_PATTERN = re.compile(
    r"\b(?:today(?:'s)? date|current time|timestamp|date is|time is|utc|iso8601)\b[^\n]*|"
    r"\b\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}(?::\d{2})?[^\n]*|"
    r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}[^\n]*",
    re.IGNORECASE,
)
_UUID_PATTERN = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)
_DYNAMIC_SESSION_PATTERN = re.compile(
    r"\b(?:session(?:_id)?|request(?:_id)?|turn(?:_id)?|conversation(?:_id)?)\s*[:=]\s*\S+",
    re.IGNORECASE,
)


@dataclass
class PromptAlignResult:
    original_tokens: int
    aligned_tokens: int
    cacheability_score: int
    issues_found: list[str]
    aligned_text: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "original_tokens": self.original_tokens,
            "aligned_tokens": self.aligned_tokens,
            "cacheability_score": self.cacheability_score,
            "issues_found": self.issues_found,
            "aligned_text": self.aligned_text,
        }


def lint_prompt(text: str) -> dict[str, Any]:
    """Audit prompt for cache-busting dynamic elements in prefix."""
    lines = text.splitlines()
    if not lines:
        return {"cacheability_score": 100, "issues": [], "recommendations": []}

    prefix_cutoff = min(len(lines), max(5, len(lines) // 3))
    prefix_lines = lines[:prefix_cutoff]

    issues: list[str] = []
    for idx, line in enumerate(prefix_lines, 1):
        if _TIMESTAMP_PATTERN.search(line):
            issues.append(
                f"Line {idx}: Dynamic timestamp/date in prompt prefix busts prompt cache: '{line.strip()[:60]}'"
            )
        if _UUID_PATTERN.search(line):
            issues.append(
                f"Line {idx}: Volatile UUID in prompt prefix busts prompt cache: '{line.strip()[:60]}'"
            )
        if _DYNAMIC_SESSION_PATTERN.search(line):
            issues.append(
                f"Line {idx}: Session or request ID in prompt prefix busts prompt cache: '{line.strip()[:60]}'"
            )

    score = max(0, 100 - (len(issues) * 30))
    recommendations = []
    if issues:
        recommendations.append(
            "Move dynamic variables (timestamps, IDs) to the prompt suffix to preserve static cacheable prefix."
        )
        recommendations.append(
            "Use 'usagetrim prompt align' to automatically restructure prompt sections for maximum cache hits."
        )

    return {
        "cacheability_score": score,
        "issues": issues,
        "recommendations": recommendations,
        "prefix_lines_checked": prefix_cutoff,
    }


def align_prompt(text: str) -> PromptAlignResult:
    """Restructure prompt: static invariants at the top, volatile variables at the bottom."""
    lines = text.splitlines(keepends=True)
    orig_tokens = count_tokens(text).openai

    lint_res = lint_prompt(text)
    issues = lint_res["issues"]

    if not issues:
        return PromptAlignResult(
            original_tokens=orig_tokens,
            aligned_tokens=orig_tokens,
            cacheability_score=lint_res["cacheability_score"],
            issues_found=[],
            aligned_text=text,
        )

    static_lines: list[str] = []
    volatile_lines: list[str] = []

    for line in lines:
        if (
            _TIMESTAMP_PATTERN.search(line)
            or _UUID_PATTERN.search(line)
            or _DYNAMIC_SESSION_PATTERN.search(line)
        ):
            volatile_lines.append(line)
        else:
            static_lines.append(line)

    # Reconstruct: static prefix followed by separated dynamic context block
    sections: list[str] = ["".join(static_lines).rstrip()]
    if volatile_lines:
        sections.append(
            "\n\n<!-- DYNAMIC RUNTIME CONTEXT (ISOLATED TO PRESERVE PROMPT CACHE) -->\n"
            + "".join(volatile_lines).strip()
        )

    aligned_text = "\n".join(sections).strip() + "\n"
    aligned_tokens = count_tokens(aligned_text).openai

    # Post-check score
    new_lint = lint_prompt(aligned_text)

    return PromptAlignResult(
        original_tokens=orig_tokens,
        aligned_tokens=aligned_tokens,
        cacheability_score=new_lint["cacheability_score"],
        issues_found=issues,
        aligned_text=aligned_text,
    )


_FILLER_PHRASES: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(
            r"^\s*You are a(?:n)?\s+(?:helpful|expert|world-class|autonomous)?\s*(?:AI|coding|software)?\s*assistant\s*(?:specialized\s+in\s+[^.\n]+)?\.\s*",
            re.IGNORECASE | re.MULTILINE,
        ),
        "",
    ),
    (
        re.compile(
            r"\b(?:Please\s+)?make\s+sure\s+to\s+always\s+(?:remember\s+to\s+)?",
            re.IGNORECASE,
        ),
        "Always ",
    ),
    (
        re.compile(
            r"\b(?:Please\s+)?ensure\s+(?:that\s+)?you\s+(?:always\s+)?",
            re.IGNORECASE,
        ),
        "Ensure ",
    ),
    (
        re.compile(
            r"\bIt\s+is\s+(?:critically\s+|extremely\s+|very\s+)?important\s+(?:that\s+you\s+)?",
            re.IGNORECASE,
        ),
        "Important: ",
    ),
    (
        re.compile(
            r"\bUnder\s+no\s+circumstances\s+should\s+you\s+(?:ever\s+)?",
            re.IGNORECASE,
        ),
        "Never ",
    ),
    (
        re.compile(r"\bDo\s+not\s+ever\s+", re.IGNORECASE),
        "Never ",
    ),
]


@dataclass
class PromptMinifyResult:
    original_tokens: int
    minified_tokens: int
    saved_tokens: int
    reduction_pct: float
    minified_text: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "original_tokens": self.original_tokens,
            "minified_tokens": self.minified_tokens,
            "saved_tokens": self.saved_tokens,
            "reduction_pct": self.reduction_pct,
            "minified_text": self.minified_text,
        }


def minify_prompt(text: str) -> PromptMinifyResult:
    """Minify system prompts, CLAUDE.md, and AGENTS.md instructions without semantic loss.

    Removes markdown comments, collapses hyper-verbose phrasing, strips excessive blank lines,
    and normalizes list indentation to save 20-40% prompt tokens.
    """
    orig_tokens = count_tokens(text).openai
    if not text.strip():
        return PromptMinifyResult(0, 0, 0, 0.0, text)

    # 1. Strip HTML comments (<!-- ... -->)
    content = re.sub(r"<!--[\s\S]*?-->", "", text)

    # 2. Compress verbose boilerplate phrasings
    for pattern, replacement in _FILLER_PHRASES:
        content = pattern.sub(replacement, content)

    # 3. Clean line by line
    lines = content.splitlines()
    cleaned_lines: list[str] = []
    prev_blank = False
    prev_line: str | None = None

    for line in lines:
        stripped = line.rstrip()
        if not stripped:
            if not prev_blank and cleaned_lines:
                cleaned_lines.append("")
                prev_blank = True
            continue

        prev_blank = False
        leading_spaces = len(stripped) - len(stripped.lstrip())
        if leading_spaces > 4 and stripped.lstrip().startswith(("-", "*", "•", "1.")):
            stripped = "  " + stripped.lstrip()

        if stripped == prev_line:
            continue

        prev_line = stripped
        cleaned_lines.append(stripped)

    minified_text = "\n".join(cleaned_lines).strip() + "\n"
    minified_tokens = count_tokens(minified_text).openai
    saved = max(0, orig_tokens - minified_tokens)
    pct = round((saved / orig_tokens * 100.0), 1) if orig_tokens > 0 else 0.0

    return PromptMinifyResult(
        original_tokens=orig_tokens,
        minified_tokens=minified_tokens,
        saved_tokens=saved,
        reduction_pct=pct,
        minified_text=minified_text,
    )


_VOLATILE_PATH_PATTERN = re.compile(
    r"(?:/private/var/folders/[^\s:]+|/(?:tmp|var/tmp)/[^\s:]+)",
    re.IGNORECASE,
)


def stabilize_cache_prefix(text: str) -> str:
    """Normalize volatile elements in text prefixes to protect prompt cache hits.

    1. Normalizes CRLF \\r\\n to \\n and strips trailing whitespace.
    2. Isolates volatile prefix variables (timestamps, volatile paths, session UUIDs)
       to dynamic context sections so that Anthropic (1024-token) and OpenAI (128-token)
       prompt caching achieves optimal hit rates.
    """
    if not text.strip():
        return text

    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)

    aligned = align_prompt(normalized).aligned_text
    stabilized = _VOLATILE_PATH_PATTERN.sub("<tmpdir>", aligned)

    return stabilized
