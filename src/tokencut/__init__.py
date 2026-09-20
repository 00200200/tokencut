"""tokencut — SOTA Token Optimizer for Claude Code, OpenAI/Codex, and Gemini CLI."""

__version__ = "0.1.0"

from tokencut.core.cleaner import CleanerOptions, compact_terminal_output, strip_ansi
from tokencut.core.diff_slimmer import slim_git_diff
from tokencut.core.skeleton import extract_symbol_or_range, skeletonize_python
from tokencut.metrics.pricing import CostSavings, estimate_savings
from tokencut.metrics.tokenizer import (
    TokenCount,
    TokenReductionMetrics,
    compute_metrics,
    count_tokens,
)

__all__ = [
    "CleanerOptions",
    "CostSavings",
    "TokenCount",
    "TokenReductionMetrics",
    "compact_terminal_output",
    "compute_metrics",
    "count_tokens",
    "estimate_savings",
    "extract_symbol_or_range",
    "skeletonize_python",
    "slim_git_diff",
    "strip_ansi",
]
