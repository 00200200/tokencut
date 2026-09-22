"""TDD: specialize ``gh pr view`` / ``gh api`` JSON with spill + structured slim."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tokencut.cli import app
from tokencut.core.specialized import (
    auto_specialize_command_output,
    filter_gh_command_output,
    filter_json_output,
)
from tokencut.core.spill import DEFAULT_SPILL_BYTES
from tokencut.metrics.tokenizer import count_tokens


def _sample_pr_json(*, body_chars: int = 4000, files: int = 30, commits: int = 12) -> str:
    payload = {
        "number": 42,
        "title": "feat: cut gh JSON noise",
        "state": "OPEN",
        "url": "https://github.com/owner/repo/pull/42",
        "author": {"login": "alice", "id": "U_1", "name": "Alice"},
        "baseRefName": "main",
        "headRefName": "feat/gh-json",
        "body": ("# Summary\n\n" + ("important detail. " * 20) + "\n") * max(1, body_chars // 200),
        "commits": [
            {
                "oid": f"abc{i:04d}",
                "messageHeadline": f"commit {i}",
                "messageBody": ("long body\n" * 15),
                "committedDate": "2026-09-22T12:00:00Z",
            }
            for i in range(commits)
        ],
        "files": [
            {
                "path": f"src/module_{i}.py",
                "additions": i,
                "deletions": i // 2,
                "changeType": "MODIFIED",
            }
            for i in range(files)
        ],
        "reviews": [
            {
                "author": {"login": "reviewer"},
                "state": "APPROVED",
                "body": "Looks good. " * 80,
            }
            for _ in range(4)
        ],
        "comments": [{"author": {"login": "bot"}, "body": "nit: rename. " * 60} for _ in range(6)],
        "labels": [{"name": "enhancement"}, {"name": "tokens"}, {"name": "gh"}],
    }
    return json.dumps(payload, indent=2)


@pytest.mark.parametrize(
    "command",
    [
        "gh api repos/owner/repo/pulls/42",
        "gh pr view 42 --json number,title,body,commits,files,reviews",
        "gh issue view 7 --json body,comments,labels",
        "gh pr list --json number,title,body --limit 20",
    ],
)
def test_filter_gh_json_spills_and_slims(command, tmp_path, monkeypatch):
    monkeypatch.setenv("TOKENCUT_CACHE_DIR", str(tmp_path))
    raw = _sample_pr_json()
    assert len(raw.encode()) > DEFAULT_SPILL_BYTES

    compact = filter_gh_command_output(command, raw)
    assert compact is not None
    assert "Ref: tc_" in compact or "tokencut retrieve" in compact
    assert "spill" in compact.lower()
    assert "feat: cut gh JSON noise" in compact
    assert '"number": 42' in compact or '"number":42' in compact
    # Structured slim — not a crude head/tail dump of mid-JSON noise.
    assert (
        "important detail." not in compact
        or compact.count("important detail.") < raw.count("important detail.") // 4
    )
    assert len(compact) < len(raw) * 0.35
    assert count_tokens(compact).claude < count_tokens(raw).claude * 0.4

    spill_dir = Path(tmp_path) / "spill"
    spilled = list(spill_dir.glob("*.txt")) if spill_dir.exists() else []
    assert spilled, "expected full payload spilled to disk"
    assert spilled[0].read_text(encoding="utf-8") == raw


def test_filter_gh_json_routes_via_auto_specialize(tmp_path, monkeypatch):
    monkeypatch.setenv("TOKENCUT_CACHE_DIR", str(tmp_path))
    raw = _sample_pr_json()
    compact = auto_specialize_command_output(
        "gh pr view 42 --json body,files,commits",
        raw,
    )
    assert compact is not None
    assert "spill" in compact.lower()
    assert "feat: cut gh JSON noise" in compact


def test_filter_json_output_treats_gh_pr_json_as_explicit(tmp_path, monkeypatch):
    monkeypatch.setenv("TOKENCUT_CACHE_DIR", str(tmp_path))
    # Small object — previously skipped unless command contained ``gh api``.
    raw = json.dumps(
        {
            "number": 1,
            "title": "tiny",
            "body": "x" * 400,
            "files": [{"path": f"f{i}"} for i in range(12)],
        },
        indent=2,
    )
    slimmed = filter_json_output(raw, command="gh pr view 1 --json number,title,body,files")
    assert slimmed is not None
    assert "omitted" in slimmed
    assert "tiny" in slimmed


def test_filter_gh_text_pr_view_folds_long_body():
    body = ("## Context\n\n" + ("paragraph text about the change. " * 40) + "\n") * 8
    raw = (
        f"title:\tfeat: something big\nstate:\tOPEN\nauthor:\talice\nlabels:\tenhancement\n\n{body}"
    )
    compact = filter_gh_command_output("gh pr view 99", raw)
    assert compact is not None
    assert "title:\tfeat: something big" in compact
    assert "state:\tOPEN" in compact
    assert "TokenCut" in compact
    assert len(compact) < len(raw) * 0.5
    assert body[:40] in compact  # keep the lead of the body


def test_filter_gh_ignores_unrelated_commands():
    raw = _sample_pr_json(body_chars=500, files=5, commits=3)
    assert filter_gh_command_output("curl https://api.github.com/repos/o/r/pulls/1", raw) is None
    assert filter_gh_command_output("git log --oneline", "commit abc\n") is None


def test_cli_run_prefers_gh_json_slim_over_head_tail_spill(tmp_path, monkeypatch):
    """Safe ``tokencut run`` must not replace structured gh JSON with head/tail spill."""
    monkeypatch.setenv("TOKENCUT_CACHE_DIR", str(tmp_path))
    raw = _sample_pr_json()
    assert len(raw.encode()) > DEFAULT_SPILL_BYTES

    def fake_run(command, **kwargs):
        class Proc:
            returncode = 0
            stdout = raw

        return Proc()

    monkeypatch.setattr("tokencut.cli.subprocess.run", fake_run)
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["run", "--", "gh", "pr", "view", "42", "--json", "number,title,body,files,commits"],
    )
    assert result.exit_code == 0
    out = result.stdout
    assert "feat: cut gh JSON noise" in out
    assert "spill" in out.lower()
    # Head/tail spill keeps first 24 lines — mid-file noise like module_15 paths
    # should not dominate once structured slim is preferred.
    assert out.count("module_15") <= 1
    assert len(out) < len(raw) * 0.4
