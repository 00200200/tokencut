from __future__ import annotations

import re

SECRET_PATTERNS = [
    (re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}\b"), "[REDACTED_ANTHROPIC_KEY]"),
    (re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_\-]{20,}\b"), "[REDACTED_OPENAI_KEY]"),
    (re.compile(r"\bAIza[0-9A-Za-z\-_]{35}\b"), "[REDACTED_GEMINI_KEY]"),
    (re.compile(r"\bghp_[a-zA-Z0-9]{36}\b"), "[REDACTED_GITHUB_TOKEN]"),
    (re.compile(r"\bgithub_pat_[a-zA-Z0-9_]{40,}\b"), "[REDACTED_GITHUB_TOKEN]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED_AWS_KEY]"),
    (
        re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b"),
        "[REDACTED_JWT]",
    ),
    (
        re.compile(r"(?:postgres|mysql|mongodb|redis):\/\/[^:\/\s]+:[^@\/\s]+@"),
        "[REDACTED_DB_URL]@",
    ),
]


def redact_secrets(text: str) -> str:
    """Scrub sensitive credentials, tokens, and keys from text before feeding to AI models."""
    if not text:
        return ""
    for pattern, replacement in SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text
