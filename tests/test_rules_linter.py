from tokencut.core.rules_linter import lint_rule_content, minify_rules

SAMPLE_RULES_BAD = """
# Project Guidelines

You are a helpful coding assistant expert. Please make sure to always remember to never forget this.

Current Date: 2026-09-20T14:39:40
Session_id: 'abcdef0123456789abcdef'



- Always run tests before committing.
"""


def test_lint_detects_cache_busting():
    res = lint_rule_content(SAMPLE_RULES_BAD)
    assert not res.is_cache_friendly
    assert any(iss.rule_name == "cache-busting" for iss in res.issues)
    assert any(iss.rule_name == "verbose-boilerplate" for iss in res.issues)


def test_minify_rules():
    minified = minify_rules(SAMPLE_RULES_BAD)
    assert "<!--" not in minified
    assert "\n\n\n" not in minified


def test_optimize_rules_strips_boilerplate_and_aligns_cache():
    from tokencut.core.rules_linter import optimize_rules

    res = optimize_rules(SAMPLE_RULES_BAD)
    assert res["optimized_tokens"] < res["original_tokens"]
    assert res["savings_pct"] > 0
    assert res["is_cache_friendly"] is True

    opt_text = res["optimized_content"]
    assert "You are a helpful coding assistant" not in opt_text
    assert "Please make sure to always remember" not in opt_text
    # Dynamic timestamp and session_id should be in the Dynamic Runtime Context footer
    assert "Dynamic Runtime Context" in opt_text
    assert "Current Date: 2026-09-20T14:39:40" in opt_text
    assert "- Always run tests before committing." in opt_text


def test_generate_desktop_rules():
    from tokencut.core.rules_linter import generate_desktop_rules

    claude_rules = generate_desktop_rules("claude")
    assert "TokenCut Claude Rules" in claude_rules
    assert "tokencut_read" in claude_rules
    assert "tokencut_code" in claude_rules

    codex_rules = generate_desktop_rules("codex")
    assert "TokenCut Codex Rules" in codex_rules
    assert "tokencut_exec" in codex_rules
