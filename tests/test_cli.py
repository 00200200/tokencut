import json
import os
import sys

from typer.testing import CliRunner

from tokencut.cli import app
from tokencut.core.cache import ContextCache

runner = CliRunner()


def test_cli_help():
    res = runner.invoke(app, ["--help"])
    assert res.exit_code == 0
    assert "Context compression engine" in res.output


def test_cli_demo():
    res = runner.invoke(app, ["demo"])
    assert res.exit_code == 0
    assert "verify your installation" in res.output
    assert "PASS" in res.output
    assert "No model calls" in res.output


def test_demo_measures_recovery_and_preserves_user_cache(tmp_path, monkeypatch):
    cache_path = os.environ["TOKENCUT_CACHE_DIR"]
    cache = ContextCache()
    ref = cache.store("existing user output", source="test")
    before = cache.get_stats()["count"]
    empty_directory = tmp_path / "empty-project"
    empty_directory.mkdir()
    monkeypatch.chdir(empty_directory)
    res = runner.invoke(app, ["demo", "--json"])
    assert res.exit_code == 0
    data = json.loads(res.stdout)
    assert data["passed"] and all(data["checks"].values())
    assert data["model_calls"] == 0
    assert 0 < data["output_tokens"] < data["raw_tokens"]
    assert os.environ["TOKENCUT_CACHE_DIR"] == cache_path
    assert cache.get_stats()["count"] == before
    assert cache.retrieve(ref) == "existing user output"


def test_demo_fails_if_compaction_drops_diagnostics(monkeypatch):
    monkeypatch.setattr("tokencut.cli.safe_compact_output", lambda text, **kw: "everything passed")
    res = runner.invoke(app, ["demo", "--json"])
    assert res.exit_code == 1
    data = json.loads(res.stdout)
    assert not data["passed"]
    assert not data["checks"]["complete_failure_tail_preserved"]
    assert not data["checks"]["original_recovered_exactly"]


def test_invalid_run_budget_is_rejected_before_execution(tmp_path):
    marker = tmp_path / "must-not-execute"
    script = f"from pathlib import Path; Path({str(marker)!r}).touch()"
    for budget in ("0", "-1"):
        res = runner.invoke(app, ["run", "--budget", budget, "--", sys.executable, "-c", script])
        assert res.exit_code == 2
        assert not marker.exists()


def test_cli_run():
    res = runner.invoke(app, ["run", "echo", "testing 1 2 3"])
    assert res.exit_code == 0
    assert "testing 1 2 3" in res.output


def test_run_preserves_literal_arguments_and_markup(tmp_path):
    unwanted = tmp_path / "should-not-exist"
    literal = f"[bold]two words[/bold] ; touch {unwanted} $(echo expanded)"
    res = runner.invoke(
        app, ["run", "--", sys.executable, "-c", "import sys; print(sys.argv[1])", literal]
    )
    assert res.exit_code == 0
    assert res.stdout == literal + "\n"
    assert not unwanted.exists()


def test_run_preserves_complete_failed_output_and_exit_status():
    output = (
        "Traceback (most recent call last):\n"
        + "detail\n" * 200
        + "AssertionError: original failure\n"
    )
    script = f"import sys; print({output!r}, end='', file=sys.stderr); sys.exit(7)"
    res = runner.invoke(app, ["run", "--", sys.executable, "-c", script])
    assert res.exit_code == 7
    assert res.stdout == output


def test_retrieve_preserves_original_format_and_charges_readback():
    from tokencut.core.telemetry import TelemetryStore

    raw = "[bold]literal[/bold] " + "long-line " * 40
    ref = ContextCache().store(raw, source="test")
    res = runner.invoke(app, ["retrieve", ref])
    assert res.exit_code == 0
    assert res.stdout == raw + "\n"
    assert TelemetryStore().get_stats().saved_openai < 0


def test_cli_cat(tmp_path):
    f = tmp_path / "hello.py"
    f.write_text("class Foo:\n    def bar(self):\n        pass\n")
    res = runner.invoke(app, ["cat", str(f), "--skeleton"])
    assert res.exit_code == 0
    assert "class Foo:" in res.output


def test_cli_tree(tmp_path):
    f = tmp_path / "test.py"
    f.write_text("def test(): pass\n")
    res = runner.invoke(app, ["tree", str(tmp_path)])
    assert res.exit_code == 0
    assert "test.py" in res.output


def test_cli_retrieve(tmp_path):
    cache = ContextCache(db_path=tmp_path / "c.db")
    ref_id = cache.store("Hello raw world!", source="test")

    # Monkeypatch default cache in cli if needed or invoke
    res = runner.invoke(app, ["retrieve", ref_id])
    assert res.exit_code == 0


def test_cli_pipe():
    res = runner.invoke(app, ["pipe"], input="Line 1\nLine 2\n")
    assert res.exit_code == 0
    assert "Line 1" in res.output


def test_cli_diff():
    res = runner.invoke(app, ["diff"])
    assert res.exit_code == 0


def test_cli_lint(tmp_path):
    f = tmp_path / "CLAUDE.md"
    f.write_text("# Instructions\n- Be concise\n")
    res = runner.invoke(app, ["lint", str(f)])
    assert res.exit_code == 0
    assert "Rule Audit" in res.output


def test_cli_json_string():
    raw = '[{"id": 1}, {"id": 2}, {"id": 3}, {"id": 4}, {"id": 5}]'
    res = runner.invoke(app, ["json", raw])
    assert res.exit_code == 0
    assert "omitted by tokencut" in res.output


def test_cli_json_stdin():
    raw = '{"items": [1, 2, 3, 4, 5, 6, 7]}'
    res = runner.invoke(app, ["json"], input=raw)
    assert res.exit_code == 0
    assert "omitted by tokencut" in res.output


def test_cli_doctor():
    res = runner.invoke(app, ["doctor"])
    assert res.exit_code == 0
    assert "tokencut System & Integration Diagnostics" in res.output


def test_cli_install_desktop_honors_installer_failure(monkeypatch):
    monkeypatch.setattr(
        "tokencut.cli.configure_claude_desktop_mcp",
        lambda: (False, "Malformed existing config; unchanged"),
    )
    result = runner.invoke(app, ["install", "--claude-desktop"])
    assert result.exit_code == 1
    assert "unchanged" in result.output
    assert "configured in" not in result.output


def test_cli_install_desktop_selects_only_desktop(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "tokencut.cli.configure_claude_desktop_mcp",
        lambda: (calls.append("desktop") or True, "/tmp/claude.json"),
    )
    monkeypatch.setattr("tokencut.cli.configure_cursor_mcp", lambda: calls.append("cursor"))
    monkeypatch.setattr("tokencut.cli.configure_shell_alias", lambda: calls.append("alias"))
    result = runner.invoke(app, ["install", "--claude-desktop"])
    assert result.exit_code == 0
    assert calls == ["desktop"]


def test_cli_stats_formats():
    res_table = runner.invoke(app, ["stats", "--format", "table"])
    assert res_table.exit_code == 0
    assert "local output estimates" in res_table.output

    res_json = runner.invoke(app, ["stats", "--format", "json"])
    assert res_json.exit_code == 0
    assert "total_runs" in res_json.output

    res_md = runner.invoke(app, ["stats", "--format", "markdown"])
    assert res_md.exit_code == 0
    assert "| **Total Executions** |" in res_md.output


def test_cli_cat_strip_comments(tmp_path):
    f = tmp_path / "app.py"
    f.write_text(
        "# Copyright header\n# Another comment\ndef run():\n    # Inline comment\n    return 42\n"
    )
    res = runner.invoke(app, ["cat", str(f), "--strip-comments"])
    assert res.exit_code == 0
    assert "# Copyright header" not in res.output
    assert "def run():" in res.output


def test_cli_cache():
    res_stats = runner.invoke(app, ["cache", "stats"])
    assert res_stats.exit_code == 0
    assert "CCR Cache Store" in res_stats.output

    res_clear = runner.invoke(app, ["cache", "clear"])
    assert res_clear.exit_code == 0
    assert "Cleared" in res_clear.output


def test_cli_pr():
    res = runner.invoke(app, ["pr"])
    assert res.exit_code == 0
    assert "Token Delta" in res.output

    res_md = runner.invoke(app, ["pr", "--markdown"])
    assert res_md.exit_code == 0
    assert "Token Impact Report" in res_md.output
