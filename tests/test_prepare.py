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
