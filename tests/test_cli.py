from typer.testing import CliRunner

from tokencut.cli import app

runner = CliRunner()


def test_cli_help():
    res = runner.invoke(app, ["--help"])
    assert res.exit_code == 0
    assert "SOTA Token Optimizer" in res.output


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
