"""Prompt cache aligner and cacheability optimizer for Anthropic, OpenAI, and Gemini prompt caching."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from tokencut.metrics.tokenizer import count_tokens

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
            "Use 'tokencut prompt align' to automatically restructure prompt sections for maximum cache hits."
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
