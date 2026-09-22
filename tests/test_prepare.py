import io
import json
import os
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tokencut.cli import app
from tokencut.core.cache import ContextCache
from tokencut.core.monitor import Monitor
from tokencut.core.prepare import MAX_INPUT_BYTES, prepare_text
from tokencut.metrics.tokenizer import count_tokens


@pytest.mark.parametrize(
    "text",
    [
        "",
        "Keep this rule.\n\nDo not change public APIs.\n",
        "```python\nx = '  '\n```\n",
        "Zażółć 🧪\n",
    ],
)
def test_conservative_preserves_unfamiliar_input(text):
    result = prepare_text(text)
    assert result["text"] == text
    assert result["difference"] == 0
    assert result["delivery"] == "preview"


def test_preview_preserves_diagnostics_recovers_original_and_does_not_record_savings(tmp_path):
    original = (
        "Downloading unchanged dependency\n" * 250
        + "ERROR: installation failed\n"
        + "detail\n" * 60
    )
    service = Monitor([Path(os.environ["TOKENCUT_CACHE_DIR"])], tmp_path / "collector")
    before = service.snapshot()["today"]
    result = service.dispatch({"method": "prepare", "text": original})
    assert result["difference"] > 0
    assert "ERROR: installation failed\n" + "detail\n" * 60 in result["text"]
    ref = re.search(r"tokencut retrieve (\S+)", result["text"])[1].rstrip("]")
    assert ContextCache().retrieve(ref) == original
    assert result["after"] == count_tokens(result["text"]).openai
    assert service.snapshot()["today"] == before
    assert "Downloading unchanged" not in json.dumps(service.dispatch({"method": "export"}))


def test_summary_is_opt_in_and_small_input_does_not_grow():
    short = "User: Keep the public API unchanged."
    assert prepare_text(short, mode="summary")["text"] == short
    text = "User: Build a parser.\nAssistant: " + "Exploring possible approaches. " * 500
    default = prepare_text(text)
    summary = prepare_text(text, mode="summary", budget=800)
    assert default["text"] == text
    assert summary["after"] < summary["before"]
    assert summary["after"] <= 800
    assert "Build a parser" in summary["text"]


@pytest.mark.parametrize(
    "kwargs", [{"mode": "invalid"}, {"budget": True}, {"budget": 127}, {"budget": 8001}]
)
def test_invalid_options_fail_before_transform(kwargs):
    with pytest.raises(ValueError):
        prepare_text("draft", **kwargs)


def test_utf8_size_limits_and_monitor_protocol(tmp_path):
    with pytest.raises(ValueError):
        prepare_text("🧪" * (MAX_INPUT_BYTES // 4 + 1))
    service = Monitor([], tmp_path / "collector")
    text = "🧪 audit details\n" * 4000
    request = json.dumps({"id": 1, "method": "prepare", "text": text})
    assert len(request) > 65536
    output = io.StringIO()
    service.serve(io.StringIO("x" * (1024 * 1024 + 1) + "\n" + request + "\n"), output)
    error, response = map(json.loads, output.getvalue().splitlines())
    assert error["error"] == "ValueError"
    assert response["id"] == 1
    assert response["result"]["delivery"] == "preview"


def test_cli_file_and_stdin_prepare_without_usage_events(tmp_path):
    runner = CliRunner()
    text = "Keep every requirement: deterministic, local, and reversible."
    file = tmp_path / "draft.txt"
    file.write_text(text)
    for args, stdin in [(["--file", str(file)], None), ([], text)]:
        result = runner.invoke(app, ["prepare", *args, "--json"], input=stdin)
        assert result.exit_code == 0, result.output
        assert json.loads(result.stdout)["text"] == text
    too_large = runner.invoke(app, ["prepare", "--json"], input="a" * (MAX_INPUT_BYTES + 1))
    assert too_large.exit_code != 0
    assert not (Path(os.environ["TOKENCUT_CACHE_DIR"]) / "telemetry.db").exists()


def test_prepare_optimize_mode():
    prompt = """Analyze the following users table:
```json
[
  {"id": 1, "username": "alice", "role": "admin"},
  {"id": 2, "username": "bob", "role": "engineer"},
  {"id": 3, "username": "charlie", "role": "tester"}
]
```
Please let me know if there are any issues.
"""
    result = prepare_text(prompt, mode="optimize", budget=1000)
    assert result["mode"] == "optimize"
    assert result["after"] < result["before"]
    assert "[id | username | role]" in result["text"]
    assert "Analyze the following users table:" in result["text"]
    assert "Please let me know if there are any issues." in result["text"]


def test_cli_prepare_optimize_mode(tmp_path):
    runner = CliRunner()
    file = tmp_path / "prompt.txt"
    file.write_text("""Review this table:
```json
[{"id": 1, "status": "active"}, {"id": 2, "status": "idle"}]
```
Any observations?
""")
    result = runner.invoke(app, ["prepare", "--file", str(file), "--mode", "optimize", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["mode"] == "optimize"
    assert "[id | status]" in payload["text"]


def test_format_prepare_counts_shows_before_after_delta_and_percent():
    from tokencut.core.prepare import format_prepare_counts

    assert format_prepare_counts(4512, 1203) == "4,512 → 1,203 (−3,309 · −73%)"
    assert format_prepare_counts(100, 100) == "100 → 100 (0 · 0%)"
    assert format_prepare_counts(0, 0) == "0 → 0 (0 · 0%)"
    assert format_prepare_counts(50, 80) == "50 → 80 (+30 · +60%)"


def test_prepare_text_includes_counts_summary_and_percent():
    from tokencut.core.prepare import format_prepare_counts

    text = "Downloading unchanged dependency\n" * 250 + "ERROR: installation failed\n"
    result = prepare_text(text)
    assert result["difference"] > 0
    assert result["percent"] == round(
        (result["after"] - result["before"]) / result["before"] * 100
    )
    assert result["counts"] == format_prepare_counts(result["before"], result["after"])


def test_cli_prepare_stderr_shows_arrow_counts(tmp_path):
    from tokencut.core.prepare import DEFAULT_PREPARE_BUDGET, format_prepare_counts

    runner = CliRunner()
    file = tmp_path / "noisy.txt"
    file.write_text("Downloading unchanged dependency\n" * 250 + "ERROR: keep me\n")
    result = runner.invoke(app, ["prepare", "--file", str(file)])
    assert result.exit_code == 0, result.output
    payload = prepare_text(file.read_text())
    assert format_prepare_counts(payload["before"], payload["after"]) in result.stderr
    assert "o200k" in result.stderr
    assert "usage" in result.stderr.lower()
    assert DEFAULT_PREPARE_BUDGET == 2000


def test_cli_prepare_defaults_use_desktop_budget():
    import inspect

    from tokencut.cli import prepare_command

    params = inspect.signature(prepare_command).parameters
    assert params["budget"].default == 2000
    assert params["mode"].default == "conservative"
