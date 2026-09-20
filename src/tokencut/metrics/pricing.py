from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple


class ModelPricing(NamedTuple):
    name: str
    input_per_million: float   # USD per 1M input tokens
    output_per_million: float  # USD per 1M output tokens
    cache_read_per_million: float | None = None  # USD if prompt cached


# Baseline pricing reference (as of 2025/2026)
PRICING_TABLE: dict[str, ModelPricing] = {
    # Anthropic Claude
    "claude-3-7-sonnet": ModelPricing("Claude 3.7 Sonnet", 3.00, 15.00, 0.30),
    "claude-3-5-sonnet": ModelPricing("Claude 3.5 Sonnet", 3.00, 15.00, 0.30),
    "claude-3-5-haiku": ModelPricing("Claude 3.5 Haiku", 0.80, 4.00, 0.08),
    "claude-3-opus": ModelPricing("Claude 3 Opus", 15.00, 75.00, 1.50),
    # OpenAI
    "gpt-4o": ModelPricing("GPT-4o", 2.50, 10.00, 1.25),
    "gpt-4o-mini": ModelPricing("GPT-4o mini", 0.15, 0.60, 0.075),
    "o1": ModelPricing("o1 (reasoning)", 15.00, 60.00, 7.50),
    "o3-mini": ModelPricing("o3-mini", 1.10, 4.40, 0.55),
    # Google Gemini
    "gemini-2.0-flash": ModelPricing("Gemini 2.0 Flash", 0.10, 0.40, 0.025),
    "gemini-1.5-pro": ModelPricing("Gemini 1.5 Pro", 1.25, 5.00, 0.31),
    "gemini-1.5-flash": ModelPricing("Gemini 1.5 Flash", 0.075, 0.30, 0.018),
}


@dataclass(frozen=True)
class CostSavings:
    claude_saved_usd: float
    openai_saved_usd: float
    gemini_saved_usd: float

    @property
    def avg_saved_usd(self) -> float:
        return (self.claude_saved_usd + self.openai_saved_usd + self.gemini_saved_usd) / 3.0

    def format_claude(self) -> str:
        return f"${self.claude_saved_usd:.4f}"

    def format_avg(self) -> str:
        return f"${self.avg_saved_usd:.4f}"


def estimate_savings(saved_claude_tokens: int, saved_openai_tokens: int, saved_gemini_tokens: int) -> CostSavings:
    # Baseline comparison: Claude 3.5/3.7 Sonnet ($3.00/1M input), GPT-4o ($2.50/1M input), Gemini 1.5 Pro ($1.25/1M input)
    claude_usd = (saved_claude_tokens / 1_000_000.0) * PRICING_TABLE["claude-3-7-sonnet"].input_per_million
    openai_usd = (saved_openai_tokens / 1_000_000.0) * PRICING_TABLE["gpt-4o"].input_per_million
    gemini_usd = (saved_gemini_tokens / 1_000_000.0) * PRICING_TABLE["gemini-1.5-pro"].input_per_million

    return CostSavings(
        claude_saved_usd=claude_usd,
        openai_saved_usd=openai_usd,
        gemini_saved_usd=gemini_usd,
    )
