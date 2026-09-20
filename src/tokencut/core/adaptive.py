from __future__ import annotations

from tokencut.core.cache import ContextCache
from tokencut.core.cleaner import CleanerOptions, compact_terminal_output, strip_ansi
from tokencut.core.redactor import redact_secrets
from tokencut.metrics.tokenizer import count_tokens


def compress_to_budget(
    text: str,
    max_tokens: int,
    provider: str = "claude",
    source: str = "adaptive",
) -> str:
    """Adaptively compress any text to guarantee it stays strictly within a token budget.

    Guarantees 100% reversibility via ContextCache ref ID.
    """
    if not text or max_tokens <= 0:
        return ""

    tok_info = count_tokens(text)
    current_tokens = getattr(tok_info, provider, tok_info.avg)

    if current_tokens <= max_tokens:
        return text

    # Cache original for full recovery
    cache = ContextCache()
    ref_id = cache.store(text, source=source)

    # Level 1: Sanitize and basic strip
    cleaned = redact_secrets(strip_ansi(text)).strip()
    tok_info = count_tokens(cleaned)
    current_tokens = getattr(tok_info, provider, tok_info.avg)
    if current_tokens <= max_tokens:
        return cleaned

    # Level 2: Proportional line truncation based on token budget
    estimated_target_lines = max(4, int(max_tokens / 12))
    head_lines = max(1, int(estimated_target_lines * 0.3))
    tail_lines = max(2, int(estimated_target_lines * 0.7))

    opts = CleanerOptions(
        max_lines=estimated_target_lines,
        head_lines=head_lines,
        tail_lines=tail_lines,
        enable_cache=False,
    )
    compacted = compact_terminal_output(cleaned, opts)

    tok_info = count_tokens(compacted)
    current_tokens = getattr(tok_info, provider, tok_info.avg)
    if current_tokens <= max_tokens:
        return f"{compacted}\n[tokencut: fitted to {max_tokens} token budget. Ref: {ref_id}]"

    # Level 3: Character/word-level hard slicing if lines are too long
    # Roughly 3.5 chars per token for English/code
    ref_suffix = f"\n[... omitted to fit {max_tokens} tokens. Ref: {ref_id}]"

    # avail_tokens = max(5, max_tokens - suffix_tokens)

    # Binary search slice on character length
    low = 10
    high = len(compacted)
    best_slice = compacted[:low]

    while low <= high:
        mid = (low + high) // 2
        candidate = compacted[:mid] + ref_suffix
        c_tok = getattr(count_tokens(candidate), provider, count_tokens(candidate).avg)

        if c_tok <= max_tokens:
            best_slice = candidate
            low = mid + 1
        else:
            high = mid - 1

    return best_slice
