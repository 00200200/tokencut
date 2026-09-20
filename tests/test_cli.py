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
    assert "Anthropic Claude" in res.output
    assert "OpenAI GPT-4o" in res.output
    assert "Google Gemini" in res.output


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
