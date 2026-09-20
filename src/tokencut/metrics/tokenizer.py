from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

import tiktoken

Provider = Literal["claude", "openai", "gemini"]

# Cache tiktoken encodings
_CL100K_ENC = None
_O200K_ENC = None


def get_cl100k():
    global _CL100K_ENC
    if _CL100K_ENC is None:
        _CL100K_ENC = tiktoken.get_encoding("cl100k_base")
    return _CL100K_ENC


def get_o200k():
    global _O200K_ENC
    if _O200K_ENC is None:
        try:
            _O200K_ENC = tiktoken.get_encoding("o200k_base")
        except Exception:
            _O200K_ENC = get_cl100k()
    return _O200K_ENC


@dataclass(frozen=True)
class TokenCount:
    claude: int
    openai: int
    gemini: int

    @property
    def avg(self) -> int:
        return (self.claude + self.openai + self.gemini) // 3


@dataclass(frozen=True)
class TokenReductionMetrics:
    raw_tokens: TokenCount
    compact_tokens: TokenCount
    raw_chars: int
    compact_chars: int
    raw_lines: int
    compact_lines: int

    @property
    def saved_tokens(self) -> TokenCount:
        return TokenCount(
            claude=max(0, self.raw_tokens.claude - self.compact_tokens.claude),
            openai=max(0, self.raw_tokens.openai - self.compact_tokens.openai),
            gemini=max(0, self.raw_tokens.gemini - self.compact_tokens.gemini),
        )

    @property
    def reduction_pct(self) -> float:
        if self.raw_tokens.avg == 0:
            return 0.0
        saved = self.raw_tokens.avg - self.compact_tokens.avg
        return round((saved / self.raw_tokens.avg) * 100.0, 1)

    @property
    def char_reduction_pct(self) -> float:
        if self.raw_chars == 0:
            return 0.0
        return round(((self.raw_chars - self.compact_chars) / self.raw_chars) * 100.0, 1)


def count_tokens(text: str) -> TokenCount:
    """Accurately count and estimate tokens for Claude, OpenAI, and Gemini.

    - OpenAI: uses o200k_base / cl100k_base exact BPE counts.
    - Claude: Anthropic BPE tokenizer tends to yield slightly more tokens on code/whitespace
      (~1.08x - 1.15x compared to cl100k) due to specific subword segmentation.
    - Gemini: SentencePiece model (256k vocab) yields very close token efficiency
      to cl100k (~0.98x - 1.02x).
    """
    if not text:
        return TokenCount(claude=0, openai=0, gemini=0)

    try:
        openai_count = len(get_o200k().encode(text, disallowed_special=()))
    except Exception:
        openai_count = len(get_cl100k().encode(text, disallowed_special=()))

    # Claude token estimation
    # On typical programming text and logs, Anthropic tokenizer runs ~1.10x tiktoken
    claude_count = int(math.ceil(openai_count * 1.10))

    # Gemini SentencePiece estimation
    gemini_count = int(math.ceil(openai_count * 1.02))

    return TokenCount(
        claude=claude_count,
        openai=openai_count,
        gemini=gemini_count,
    )


def compute_metrics(raw_text: str, compact_text: str) -> TokenReductionMetrics:
    raw_tok = count_tokens(raw_text)
    compact_tok = count_tokens(compact_text)

    raw_lines = len(raw_text.splitlines()) if raw_text else 0
    compact_lines = len(compact_text.splitlines()) if compact_text else 0

    return TokenReductionMetrics(
        raw_tokens=raw_tok,
        compact_tokens=compact_tok,
        raw_chars=len(raw_text),
        compact_chars=len(compact_text),
        raw_lines=raw_lines,
        compact_lines=compact_lines,
    )
