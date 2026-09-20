"""tokencut — Context compression engine and MCP server for Claude Code, Cursor, and Gemini CLI."""

__version__ = "0.1.0"

from tokencut.core.cache import ContextCache
from tokencut.core.cleaner import CleanerOptions, compact_terminal_output, strip_ansi
from tokencut.core.diff_slimmer import slim_git_diff
from tokencut.core.doctor import run_all_diagnostics
from tokencut.core.json_slimmer import slim_json
from tokencut.core.redactor import redact_secrets
from tokencut.core.skeleton import extract_symbol_or_range, skeletonize_python
from tokencut.core.tree_scanner import scan_directory
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
    "ContextCache",
    "TokenCount",
    "TokenReductionMetrics",
    "compact_terminal_output",
    "compute_metrics",
    "count_tokens",
    "estimate_savings",
    "extract_symbol_or_range",
    "redact_secrets",
    "run_all_diagnostics",
    "scan_directory",
    "skeletonize_python",
    "slim_git_diff",
    "slim_json",
    "strip_ansi",
]
