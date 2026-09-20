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
