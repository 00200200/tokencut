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
    assert "Anthropic Claude" in res.output
    assert "OpenAI GPT-4o" in res.output
    assert "Google Gemini" in res.output


def test_cli_run():
    res = runner.invoke(app, ["run", "echo", "testing 1 2 3"])
    assert res.exit_code == 0
    assert "testing 1 2 3" in res.output


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


def test_cli_stats_formats():
    res_table = runner.invoke(app, ["stats", "--format", "table"])
    assert res_table.exit_code == 0
    assert "Telemetry" in res_table.output

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
