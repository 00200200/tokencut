"""In-chat conversation and transcript distillation for AI coding assistants."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from tokencut.core.cache import ContextCache
from tokencut.core.redactor import redact_secrets
from tokencut.metrics.tokenizer import count_tokens

_COLOR = re.compile(r"\x1b\[[0-9;]*m")
_THOUGHT_BLOCK = re.compile(
    r"<(?:thinking|thought)>.*?</(?:thinking|thought)>", re.DOTALL | re.IGNORECASE
)
_FILE_PATH = re.compile(r"(?:[\w\-.]+/)+[\w\-.]+\.[a-zA-Z0-9]+")
_DECISION_PATTERNS = re.compile(
    r"\b(?:decided to|agree(?:d)? on|choose|chose|switch(?:ed)? to|implement(?:ed)?|"
    r"will use|must use|standardize on|configured)\b[^\n.!?]+[.!?]",
    re.IGNORECASE,
)
_FAILED_PATTERNS = re.compile(
    r"\b(?:failed|error|rejected|reverted|cannot|could not|broken|bug|exception)\b[^\n.!?]+[.!?]",
    re.IGNORECASE,
)


@dataclass
class DistillResult:
    original_tokens: int
    distilled_tokens: int
    saved_tokens: int
    reduction_pct: float
    ref_id: str
    text: str
    message_count: int
    files_referenced: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "original_tokens": self.original_tokens,
            "distilled_tokens": self.distilled_tokens,
            "saved_tokens": self.saved_tokens,
            "reduction_pct": self.reduction_pct,
            "ref_id": self.ref_id,
            "text": self.text,
            "message_count": self.message_count,
            "files_referenced": self.files_referenced,
        }


def _parse_messages(text: str) -> list[tuple[str, str]]:
    """Parse dialogue turns from markdown, XML, or JSON lines."""
    messages: list[tuple[str, str]] = []

    # Check if text is JSON-lines
    stripped = text.strip()
    if stripped.startswith("{") and "\n" in stripped:
        parsed_json_lines = True
        for line in stripped.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                role = obj.get("role", obj.get("source", "unknown"))
                content = obj.get("content", obj.get("text", ""))
                if isinstance(content, str) and content.strip():
                    messages.append((str(role).capitalize(), content.strip()))
            except Exception:
                parsed_json_lines = False
                break
        if parsed_json_lines and messages:
            return messages

    # Parse role-based markdown dialogue
    role_pattern = re.compile(
        r"^(?:#{1,4}\s*)?(User|Assistant|Human|System|Claude|GPT|Antigravity|Agent):\s*",
        re.MULTILINE | re.IGNORECASE,
    )
    splits = list(role_pattern.finditer(text))
    if splits:
        for idx, match in enumerate(splits):
            role = match.group(1).capitalize()
            start = match.end()
            end = splits[idx + 1].start() if idx + 1 < len(splits) else len(text)
            chunk = text[start:end].strip()
            if chunk:
                messages.append((role, chunk))
        return messages

    # Fallback: treat paragraphs or whole text as single message
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    return [("User", p) for p in paragraphs] or [("User", text)]


def distill_conversation(text: str, budget: int = 1500) -> DistillResult:
    """Distill raw multi-turn conversation into dense executive context with zero loss CCR recovery."""
    cleaned = _COLOR.sub("", text)
    cleaned = _THOUGHT_BLOCK.sub("", cleaned)
    redacted = redact_secrets(cleaned)
    original_tokens = count_tokens(redacted).openai

    cache = ContextCache()
    ref_id = cache.store(redacted, source="conversation-distill")

    messages = _parse_messages(redacted)
    message_count = len(messages)

    # 1. Identify User Goal & Initial Prompts
    user_requests: list[str] = []
    assistant_responses: list[str] = []
    files_seen: set[str] = set()

    for role, content in messages:
        # Extract files
        for match in _FILE_PATH.finditer(content):
            path = match.group()
            if not path.startswith("http") and not path.endswith((".com", ".org", ".net", ".io")):
                files_seen.add(path)

        if role in {"User", "Human"}:
            first_sentence = content.splitlines()[0][:200].strip()
            if first_sentence and first_sentence not in user_requests:
                user_requests.append(first_sentence)
        else:
            assistant_responses.append(content)

    # 2. Extract Key Decisions
    decisions: list[str] = []
    for resp in assistant_responses:
        for match in _DECISION_PATTERNS.finditer(resp):
            item = match.group().strip()
            if item not in decisions and len(item) > 15:
                decisions.append(item)
            if len(decisions) >= 8:
                break

    # 3. Extract Discarded Attempts & Failures
    failures: list[str] = []
    for resp in assistant_responses:
        for match in _FAILED_PATTERNS.finditer(resp):
            item = match.group().strip()
            if item not in failures and len(item) > 15:
                failures.append(item)
            if len(failures) >= 5:
                break

    # 4. Extract Last Assistant Action / State
    last_action = ""
    if assistant_responses:
        last_resp_lines = [
            line.strip() for line in assistant_responses[-1].splitlines() if line.strip()
        ]
        last_action = "\n".join(last_resp_lines[-4:]) if last_resp_lines else ""

    # Build dense executive context block
    sections: list[str] = [
        "# Distilled Conversation Context",
        f"Messages: {message_count} turns · Full Original Cached: tokencut retrieve {ref_id}",
        "",
        "## Goals & User Inquiries",
    ]
    for req in user_requests[:6]:
        sections.append(f"- {req}")
    if not user_requests:
        sections.append("- (Continued task session)")

    if decisions:
        sections.append("\n## Key Decisions & Agreed Architecture")
        for dec in decisions:
            sections.append(f"- {dec}")

    if failures:
        sections.append("\n## Resolved Issues & Discarded Attempts")
        for fail in failures:
            sections.append(f"- {fail}")

    if files_seen:
        sections.append("\n## Referenced Files")
        sorted_files = sorted(list(files_seen))[:20]
        sections.append(", ".join(f"`{f}`" for f in sorted_files))

    if last_action:
        sections.append(f"\n## Active Working State\n{last_action}")

    distilled_text = "\n".join(sections).strip() + f"\n\n[Full transcript reference: {ref_id}]\n"
    distilled_tokens = count_tokens(distilled_text).openai

    # Enforce budget ceiling
    if distilled_tokens > budget:
        notice = f"\n\n[Summary truncated to fit {budget} tokens. Full transcript: tokencut retrieve {ref_id}]\n"
        # A single long assistant line can exceed the entire budget. Bound the
        # complete emitted text, including recovery, without splitting Unicode.
        low, high = 0, len(distilled_text)
        while low < high:
            middle = (low + high + 1) // 2
            if count_tokens(distilled_text[:middle] + notice).openai <= budget:
                low = middle
            else:
                high = middle - 1
        distilled_text = distilled_text[:low] + notice
        distilled_tokens = count_tokens(distilled_text).openai

    saved = max(0, original_tokens - distilled_tokens)
    pct = round((saved / original_tokens) * 100, 1) if original_tokens else 0.0

    return DistillResult(
        original_tokens=original_tokens,
        distilled_tokens=distilled_tokens,
        saved_tokens=saved,
        reduction_pct=pct,
        ref_id=ref_id,
        text=distilled_text,
        message_count=message_count,
        files_referenced=sorted(list(files_seen)),
    )
