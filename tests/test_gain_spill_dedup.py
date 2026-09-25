"""TDD for gain analytics, session dedup, and large-output spill."""

from __future__ import annotations

from typer.testing import CliRunner

from usagetrim.cli import app
from usagetrim.core.cache import ContextCache
from usagetrim.core.command_family import command_family
from usagetrim.core.gain import GainReport, build_gain_report
from usagetrim.core.spill import DEFAULT_SPILL_BYTES, spill_large_output
from usagetrim.core.telemetry import TelemetryStore


def test_command_family_normalizes_common_invocations():
    assert command_family(["pytest", "-q"]) == "pytest"
    assert command_family(["/usr/bin/git", "diff"]) == "git"
    assert command_family(["uv", "run", "pytest", "tests"]) == "pytest"
    assert command_family(["python", "-m", "mypy", "."]) == "mypy"
    assert command_family(["npx", "eslint", "."]) == "eslint"
    assert command_family([]) == "unknown"


def test_gain_report_groups_by_operation_and_flags_passthrough(tmp_path, monkeypatch):
    monkeypatch.setenv("USAGETRIM_CACHE_DIR", str(tmp_path))
    store = TelemetryStore(db_path=tmp_path / "telemetry.db")
    store.record(
        1000,
        200,
        1000,
        200,
        1000,
        200,
        operation="exec:pytest",
        delivery="returned",
    )
    store.record(
        500,
        500,
        500,
        500,
        500,
        500,
        operation="exec:echo",
        delivery="returned",
    )
    store.record(
        800,
        100,
        800,
        100,
        800,
        100,
        operation="exec:docker",
        delivery="returned",
    )

    report = build_gain_report(store)
    assert isinstance(report, GainReport)
    assert report.total_events == 3
    assert report.saved_openai == (800 + 0 + 700)
    by_op = {row.operation: row for row in report.by_operation}
    assert by_op["exec:pytest"].saved_openai == 800
    assert by_op["exec:echo"].passthrough is True
    assert by_op["exec:docker"].reduction_pct > 80
    assert any(row.operation == "exec:echo" for row in report.passthrough)


def test_session_dedup_returns_short_ref_for_identical_content(tmp_path, monkeypatch):
    monkeypatch.setenv("USAGETRIM_CACHE_DIR", str(tmp_path))
    cache = ContextCache(db_path=tmp_path / "cache.db")
    blob = "error: boom\n" + ("line\n" * 200)
    first = cache.store(blob, source="run")
    again = cache.check_duplicate(blob)
    assert again == first
    notice = cache.dedup_notice(blob)
    assert notice is not None
    assert first in notice
    assert "identical" in notice.lower() or "cached" in notice.lower()
    assert len(notice) < len(blob) // 4


def test_spill_writes_file_and_preview(tmp_path, monkeypatch):
    monkeypatch.setenv("USAGETRIM_CACHE_DIR", str(tmp_path))
    huge = ("LAYER progress " + ("x" * 80) + "\n") * 400
    assert len(huge.encode()) > DEFAULT_SPILL_BYTES
    result = spill_large_output(huge, spill_dir=tmp_path / "spill")
    assert result is not None
    assert result.path.is_file()
    assert result.path.read_text() == huge
    assert result.ref_id.startswith("tc_")
    assert "spill" in result.preview.lower() or "retrieve" in result.preview.lower()
    assert len(result.preview.encode()) < len(huge.encode()) // 5
    assert result.bytes_written == len(huge.encode())


def test_cli_gain_json(tmp_path, monkeypatch):
    monkeypatch.setenv("USAGETRIM_CACHE_DIR", str(tmp_path))
    store = TelemetryStore(db_path=tmp_path / "telemetry.db")
    store.record(200, 40, 200, 40, 200, 40, operation="exec:ruff")
    runner = CliRunner()
    result = runner.invoke(app, ["gain", "--json"])
    assert result.exit_code == 0
    assert "exec:ruff" in result.stdout
    assert "saved_openai" in result.stdout


def _seed_gain_events(tmp_path):
    store = TelemetryStore(db_path=tmp_path / "telemetry.db")
    store.record(1000, 200, 1000, 200, 1000, 200, operation="exec:pytest")
    store.record(400, 400, 400, 400, 400, 400, operation="exec:echo")
    return store


def test_cli_gain_default_shows_by_op_and_passthrough(tmp_path, monkeypatch):
    monkeypatch.setenv("USAGETRIM_CACHE_DIR", str(tmp_path))
    _seed_gain_events(tmp_path)
    result = CliRunner().invoke(app, ["gain"])
    assert result.exit_code == 0
    out = result.stdout
    assert "1000→200" in out or "1,000→200" in out
    assert "By tool family" in out
    assert "exec:pytest" in out
    assert "exec:echo" in out
    assert "passthrough" in out.lower()
    assert "Passthrough / near-zero cut" in out
    assert "usagetrim gain --history" in out


def test_cli_gain_history_keeps_by_op_and_shows_saved(tmp_path, monkeypatch):
    monkeypatch.setenv("USAGETRIM_CACHE_DIR", str(tmp_path))
    _seed_gain_events(tmp_path)
    result = CliRunner().invoke(app, ["gain", "--history"])
    assert result.exit_code == 0
    out = result.stdout
    assert "By tool family" in out
    assert "Recent history" in out
    assert "exec:pytest" in out
    assert "Saved" in out
    # History view stays focused — no passthrough dump, no "also --history" hint.
    assert "Passthrough / near-zero cut" not in out
    assert "usagetrim gain --history" not in out


def test_cli_gain_passthrough_alone_skips_by_op_table(tmp_path, monkeypatch):
    monkeypatch.setenv("USAGETRIM_CACHE_DIR", str(tmp_path))
    _seed_gain_events(tmp_path)
    result = CliRunner().invoke(app, ["gain", "--passthrough"])
    assert result.exit_code == 0
    out = result.stdout
    assert "By tool family" not in out
    assert "exec:echo" in out
    assert "usagetrim gain --by-op" in out


def test_cli_gain_empty_state(tmp_path, monkeypatch):
    monkeypatch.setenv("USAGETRIM_CACHE_DIR", str(tmp_path))
    TelemetryStore(db_path=tmp_path / "telemetry.db")
    result = CliRunner().invoke(app, ["gain"])
    assert result.exit_code == 0
    assert "No events yet" in result.stdout


def test_cli_run_records_operation_family(tmp_path, monkeypatch):
    monkeypatch.setenv("USAGETRIM_CACHE_DIR", str(tmp_path))
    runner = CliRunner()
    result = runner.invoke(app, ["run", "--", "python", "-c", "print('hi')"])
    assert result.exit_code == 0
    store = TelemetryStore(db_path=tmp_path / "telemetry.db")
    with store.connect() as conn:
        ops = [row[0] for row in conn.execute("SELECT operation FROM events").fetchall()]
    assert any(op.startswith("exec:") for op in ops)


def test_session_view_remembers_then_returns_short_ref(tmp_path, monkeypatch):
    monkeypatch.setenv("USAGETRIM_CACHE_DIR", str(tmp_path))
    cache = ContextCache(db_path=tmp_path / "cache.db")
    blob = "module payload\n" + ("line with detail\n" * 80)
    first = cache.session_view(blob, source="read")
    assert first == blob
    second = cache.session_view(blob, source="read")
    assert second != blob
    assert "retrieve" in second.lower()
    assert "tc_" in second
    assert len(second) < len(blob) // 10
    # Small payloads stay inline — no forced retrieve round-trip.
    tiny = "short\n"
    assert cache.session_view(tiny, source="read") == tiny


def test_cli_cat_session_dedups_identical_file_content(tmp_path, monkeypatch):
    monkeypatch.setenv("USAGETRIM_CACHE_DIR", str(tmp_path))
    path = tmp_path / "big.py"
    body = "def heavy():\n" + ("    x = 1  # detail\n" * 120)
    path.write_text(body)
    runner = CliRunner()
    first = runner.invoke(app, ["cat", str(path)])
    second = runner.invoke(app, ["cat", str(path)])
    assert first.exit_code == 0
    assert second.exit_code == 0
    assert "def heavy():" in first.stdout
    assert "def heavy():" not in second.stdout
    assert "retrieve" in second.stdout.lower() or "identical" in second.stdout.lower()
    assert "tc_" in second.stdout
    from usagetrim.metrics.tokenizer import count_tokens

    saved = count_tokens(first.stdout).openai - count_tokens(second.stdout).openai
    assert saved > 200
    # Ref still recovers the original extract.
    import re

    ref = re.search(r"tc_[a-f0-9]+", second.stdout).group()
    assert ContextCache().retrieve(ref) == body
