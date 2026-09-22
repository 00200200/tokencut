"""Explicit, local preparation before pasting text into a chat. No usage events."""

from tokencut.core.distill import distill_conversation
from tokencut.core.redactor import redact_secrets
from tokencut.core.safe_filter import safe_compact_output
from tokencut.metrics.tokenizer import count_tokens

MAX_INPUT_BYTES = 128 * 1024


def prepare_text(text: str, *, mode: str = "conservative", budget: int = 1500) -> dict:
    if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_INPUT_BYTES:
        raise ValueError("text must be UTF-8 text of at most 128 KiB")
    if mode not in {"conservative", "summary", "optimize", "desktop"}:
        raise ValueError("mode must be conservative, summary, optimize, or desktop")
    if type(budget) is not int or not 128 <= budget <= 8000:
        raise ValueError("budget must be an integer from 128 to 8000")
    redacted = redact_secrets(text)
    if mode == "desktop" and redacted.strip():
        from tokencut.core.optimizer import optimize_context
        from tokencut.core.prompt_optimizer import stabilize_cache_prefix
        from tokencut.core.specialized import filter_dev_server_logs, filter_traceback

        tb_filtered = filter_traceback(redacted)
        dev_filtered = filter_dev_server_logs(tb_filtered)
        stabilized = stabilize_cache_prefix(dev_filtered)
        candidate = optimize_context(stabilized, budget=budget).text
    elif mode == "optimize" and redacted.strip():
        from tokencut.core.optimizer import optimize_context

        candidate = optimize_context(redacted, budget=budget).text
    elif mode == "summary" and redacted.strip():
        candidate = distill_conversation(redacted, budget=budget).text
    else:
        candidate = safe_compact_output(redacted)
    # Never make a draft larger just to advertise a transformation. Redactions
    # remain even when their replacement labels themselves cost more tokens.
    if count_tokens(candidate).openai >= count_tokens(redacted).openai:
        candidate = redacted
    before = count_tokens(text).openai
    after = count_tokens(candidate).openai
    return {
        "text": candidate,
        "before": before,
        "after": after,
        "difference": before - after,
        "changed": candidate != text,
        "redacted": redacted != text,
        "mode": mode,
        "method": "o200k_base",
        "delivery": "preview",
    }
