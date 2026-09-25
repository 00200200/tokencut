from usagetrim.metrics.pricing import estimate_savings
from usagetrim.metrics.tokenizer import compute_metrics, count_tokens


def test_count_tokens():
    text = "def hello_world():\n    return 'Hello, World!'"
    tok = count_tokens(text)
    assert tok.claude > 0
    assert tok.openai > 0
    assert tok.gemini > 0
    assert tok.avg > 0


def test_compute_metrics():
    raw = "A very long raw string with lots of repetitive details... " * 100
    compact = "A very long raw string..."
    m = compute_metrics(raw, compact)
    assert m.reduction_pct > 80.0
    assert m.saved_tokens.claude > 0
    assert m.saved_tokens.openai > 0
    assert m.saved_tokens.gemini > 0


def test_estimate_savings():
    savings = estimate_savings(100_000, 100_000, 100_000)
    assert savings.claude_saved_usd > 0
    assert savings.openai_saved_usd > 0
    assert savings.gemini_saved_usd > 0
    assert "$" in savings.format_avg()
