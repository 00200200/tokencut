from __future__ import annotations

from usagetrim.core.pr_analyzer import (
    FileTokenDelta,
    PRTokenReport,
    _get_category,
    analyze_pr_tokens,
)


def test_get_category():
    assert _get_category("src/main.py") == "code"
    assert _get_category("src/app.tsx") == "code"
    assert _get_category("uv.lock") == "lockfile"
    assert _get_category("package-lock.json") == "lockfile"
    assert _get_category("README.md") == "docs"
    assert _get_category(".gitignore") == "other"


def test_pr_report_format_markdown():
    report = PRTokenReport(
        base_ref="origin/main",
        total_delta=1500,
        code_delta=500,
        docs_delta=200,
        lockfile_delta=800,
        files=[
            FileTokenDelta(
                path="src/new.py",
                category="code",
                tokens_before=0,
                tokens_after=500,
                delta=500,
            )
        ],
    )
    md = report.format_markdown()
    assert "Token Impact Report" in md
    assert "`+500` tokens" in md
    assert "`src/new.py`" in md


def test_analyze_pr_tokens_runs():
    report = analyze_pr_tokens()
    assert isinstance(report, PRTokenReport)
