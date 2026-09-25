from __future__ import annotations

from usagetrim.core.prompt_optimizer import align_prompt, lint_prompt, minify_prompt


def test_lint_clean_prompt():
    prompt = (
        "You are an expert Python assistant.\n"
        "Follow clean code standards and write unit tests.\n"
        "Always use typer for CLI tools.\n"
    )
    res = lint_prompt(prompt)
    assert res["cacheability_score"] == 100
    assert len(res["issues"]) == 0


def test_lint_volatile_prompt():
    prompt = (
        "Current time: 2026-09-21T08:52:10Z\n"
        "session_id: 12345-abcde\n"
        "You are a coding assistant.\n"
        "Here are the rules to follow.\n"
    )
    res = lint_prompt(prompt)
    assert res["cacheability_score"] < 100
    assert any("timestamp" in i.lower() for i in res["issues"])
    assert any("session" in i.lower() for i in res["issues"])


def test_align_prompt_restructures_volatile_prefix():
    prompt = (
        "Today's date is September 21, 2026\n"
        "request_id: req_987654321\n"
        "You are an AI assistant specialized in context optimization.\n"
        "Rule 1: Always preserve comments.\n"
        "Rule 2: Minimize token waste.\n"
    )
    res = align_prompt(prompt)
    assert res.cacheability_score >= 80
    assert "DYNAMIC RUNTIME CONTEXT" in res.aligned_text
    # Static rules should come first
    assert res.aligned_text.startswith("You are an AI assistant")
    # Date and request ID should be isolated at the end
    assert "Today's date is September 21, 2026" in res.aligned_text


def test_minify_prompt_collapses_fluff_and_comments():
    raw_prompt = """<!-- Global Guidelines -->
You are a helpful and expert AI coding assistant.
Please make sure to always remember to run tests before committing.
It is extremely important that you never commit secrets.

<!-- Environment Notes -->
Under no circumstances should you ever delete production databases.

- Follow Clean Code
- Follow Clean Code
"""
    res = minify_prompt(raw_prompt)
    assert res.reduction_pct > 0
    assert res.saved_tokens > 0
    assert "Global Guidelines" not in res.minified_text
    assert "Always run tests before committing." in res.minified_text
    assert "never commit secrets." in res.minified_text
    assert "Never delete production databases." in res.minified_text
    assert res.minified_text.count("- Follow Clean Code") == 1
