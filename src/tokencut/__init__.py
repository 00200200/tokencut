"""tokencut — Context compression engine and MCP server for Claude Code, Cursor, and Gemini CLI."""

__version__ = "0.1.0"

from tokencut.core.cache import ContextCache
from tokencut.core.cleaner import CleanerOptions, compact_terminal_output, strip_ansi
from tokencut.core.config import TokencutConfig, load_config
from tokencut.core.diff_slimmer import slim_git_diff
from tokencut.core.doctor import run_all_diagnostics
from tokencut.core.json_slimmer import slim_json
from tokencut.core.optimizer import OptimizeResult, optimize_context
from tokencut.core.pr_analyzer import PRTokenReport, analyze_pr_tokens
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
    "OptimizeResult",
    "PRTokenReport",
    "TokenCount",
    "TokenReductionMetrics",
    "TokencutConfig",
    "analyze_pr_tokens",
    "compact_terminal_output",
    "compute_metrics",
    "count_tokens",
    "estimate_savings",
    "extract_symbol_or_range",
    "load_config",
    "optimize_context",
    "redact_secrets",
    "run_all_diagnostics",
    "scan_directory",
    "skeletonize_python",
    "slim_git_diff",
    "slim_json",
    "strip_ansi",
]
