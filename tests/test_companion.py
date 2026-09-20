import io
import json
import os
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tokencut.cli import app
from tokencut.core import engines
from tokencut.core.cache import ContextCache
from tokencut.core.companion_state import already_wrapped, settings, update_settings
from tokencut.core.monitor import Monitor
from tokencut.core.native_hooks import claude_post_tool_use
from tokencut.core.telemetry import TelemetryStore
from tokencut.mcp.server import handle_tokencut_read

runner = CliRunner()


def monitor(tmp_path):
    return Monitor([Path(os.environ["TOKENCUT_CACHE_DIR"])], tmp_path / "collector")


def test_metadata_only_signed_recovery_dedup_and_restart(tmp_path):
    secret_command = "echo DO_NOT_PERSIST_COMMAND"
    store = TelemetryStore()
    store.record(
        100,
        10,
        100,
        10,
        command=secret_command,
        event_id="stable",
        project="/project",
        client="codex",
    )
    store.record(100, 10, 100, 10, command=secret_command, event_id="stable")
    store.record(0, 150, 0, 150, operation="retrieve")
    ContextCache().store("DO_NOT_PERSIST_OUTPUT", source="exec")
    service = monitor(tmp_path)
    first = service.snapshot()
    assert first["today"] == {"before": 100, "after": 160, "net": -60, "recovery": 150, "events": 2}
    assert monitor(tmp_path).snapshot()["today"] == first["today"]
    assert service.snapshot()["today"] == first["today"]
    for db in (store.db_path, service.store.db_path):
        data = db.read_bytes()
        assert b"DO_NOT_PERSIST" not in data
    assert "DO_NOT_PERSIST" not in json.dumps(service.dispatch({"method": "export"}))


def test_legacy_is_unattributed_and_separate(tmp_path):
    path = Path(os.environ["TOKENCUT_CACHE_DIR"]) / "cache.db"
    path.parent.mkdir()
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE telemetry_events(id INTEGER, timestamp REAL, raw_claude INT, compact_claude INT, raw_openai INT, compact_openai INT, raw_gemini INT, compact_gemini INT)"
        )
        conn.execute("INSERT INTO telemetry_events VALUES (1,1,100,10,100,10,100,10)")
    TelemetryStore()  # Can migrate before the collector sees the original file.
    service = monitor(tmp_path)
    snapshot = service.snapshot()
    assert snapshot["today"] is None
    assert snapshot["legacy"] == {"events": 1, "net": 90}
    with service.store.connect() as conn:
        assert conn.execute("SELECT client,project FROM events").fetchone() == (None, None)


def test_parallel_sessions_import_only_once(tmp_path):
    def record(index):
        TelemetryStore().record(10, 2, 10, 2, event_id=str(index))

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(record, range(60)))
    snap = monitor(tmp_path).snapshot()
    assert snap["today"]["events"] == 60
    assert snap["today"]["net"] == 480


def test_missing_corrupt_cache_and_no_measurements(tmp_path):
    service = Monitor([tmp_path / "missing", tmp_path / "corrupt"], tmp_path / "collector")
    (tmp_path / "corrupt").mkdir()
    (tmp_path / "corrupt/telemetry.db").write_text("broken")
    result = service.snapshot()
    assert result["today"] is None
    assert all(day["net"] is None for day in result["days"])
    assert len(result["issues"]) >= 1


def test_pause_roundtrip_preserves_backup_and_mcp_view(tmp_path):
    update_settings(paused=False, custom="keep")
    update_settings(paused=True)
    assert settings()["custom"] == "keep"
    backups = list(Path(os.environ["TOKENCUT_STATE_DIR"]).glob("companion.json.backup-*"))
    assert len(backups) == 1
    assert json.loads(backups[0].read_text())["paused"] is False
    path = tmp_path / "large.txt"
    original = "Unicode zażółć 你好 🐍\n" * 500
    path.write_text(original)
    assert handle_tokencut_read({"path": str(path), "max_tokens": 64}) == original
    result = runner.invoke(
        app, ["run", "--budget", "10", "--", sys.executable, "-c", "print('marker ' * 1000)"]
    )
    assert result.exit_code == 0
    assert result.stdout == "marker " * 1000 + "\n"
    assert monitor(tmp_path).snapshot()["today"] is None


def test_hook_prepared_idempotent_and_wrapper_skip(tmp_path):
    raw = "same progress message\n" * 300 + "ERROR: complete diagnostic\n"
    payload = {
        "hook_event_name": "PostToolUse",
        "tool_name": "Bash",
        "session_id": "session",
        "tool_use_id": "call",
        "tool_input": {"command": "pytest"},
        "tool_response": {"stdout": raw, "stderr": "", "interrupted": False},
    }
    assert claude_post_tool_use(payload)
    assert claude_post_tool_use(payload)
    data = monitor(tmp_path).snapshot()
    assert data["prepared"]["events"] == 1
    assert data["today"] is None
    payload["tool_input"]["command"] = "TOKENCUT_CACHE_DIR=/tmp/cache /bin/tokencut run -- pytest"
    assert claude_post_tool_use(payload) == {}
    assert already_wrapped(payload["tool_input"]["command"])


@pytest.mark.parametrize("engine", ["none", "tokencut", "auto"])
@pytest.mark.parametrize("case", ["empty", "unicode", "failure", "traceback", "large"])
def test_modes_execute_once_preserve_diagnostics(tmp_path, engine, case):
    marker = tmp_path / "executions"
    output = {
        "empty": "",
        "unicode": "Zażółć 你好 🐍\n",
        "failure": "ERROR: failed\n",
        "traceback": "Traceback (most recent call last):\n"
        + "  File important.py:23\n" * 500
        + "ValueError: original cause\n",
        "large": "".join(f"item {i}\n" for i in range(1000)),
    }[case]
    script = f"from pathlib import Path; import sys; p=Path({str(marker)!r}); p.write_text(p.read_text()+'x' if p.exists() else 'x'); sys.stdout.write({output!r}); sys.exit({7 if case in ('failure', 'traceback') else 0})"
    result = runner.invoke(app, ["run", "--engine", engine, "--", sys.executable, "-c", script])
    assert result.exit_code == (7 if case in ("failure", "traceback") else 0)
    assert marker.read_text() == "x"
    assert result.stdout == output


def test_external_or_invalid_engine_rejected_before_command(tmp_path):
    assert engines.select_engine("auto") == "tokencut"
    for selected in ("unknown", "rtk", "serena"):
        marker = tmp_path / "bad"
        result = runner.invoke(
            app,
            [
                "run",
                "--engine",
                selected,
                "--",
                sys.executable,
                "-c",
                f"open({str(marker)!r},'w').close()",
            ],
        )
        assert result.exit_code == 2
        assert not marker.exists()


def test_auto_filter_and_monitor_do_not_launch_external_engines(tmp_path, monkeypatch):
    marker = tmp_path / "external-invoked"
    for name in ("rtk", "serena"):
        program = tmp_path / name
        program.write_text(
            f"#!{sys.executable}\nfrom pathlib import Path\nPath({str(marker)!r}).touch()\n"
        )
        program.chmod(0o700)
    git = tmp_path / "git"
    git.write_text(f"#!{sys.executable}\nprint('ERROR: preserve this diagnostic')\n")
    git.chmod(0o700)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    result = runner.invoke(app, ["run", "--engine", "auto", "--", "git", "status"])
    assert result.exit_code == 0
    assert "ERROR: preserve this diagnostic" in result.stdout
    data = monitor(tmp_path).snapshot()
    assert [item["name"] for item in data["integrations"]] == ["TokenCut", "TokenCut Code"]
    assert not marker.exists()


def test_historical_external_engine_counts_stay_separate(tmp_path):
    store = TelemetryStore()
    store.record(0, raw_openai=300, compact_openai=100, engine="rtk", method="bytes/4")
    store.record(0, raw_openai=400, compact_openai=100, method="cl100k_base")
    data = monitor(tmp_path).snapshot()
    assert data["today"] is None
    assert data["rtk"]["net"] == 200
    assert data["other_method_events"] == 1


def test_monitor_protocol_recovers_after_malformed_request(tmp_path):
    service = monitor(tmp_path)
    output = io.StringIO()
    service.serve(
        io.StringIO(
            "broken\n[]\n"
            + json.dumps({"id": 1, "method": "pause", "paused": True})
            + "\n"
            + json.dumps({"id": 2, "method": "snapshot"})
            + "\n"
        ),
        output,
    )
    messages = [json.loads(line) for line in output.getvalue().splitlines()]
    assert len(messages) == 4
    assert "error" in messages[0]
    assert "error" in messages[1]
    assert messages[-1]["result"]["paused"] is True


def test_local_stdio_check_does_not_pollute_history(tmp_path):
    service = monitor(tmp_path)
    assert service.check()["ok"]
    assert service.snapshot()["today"] is None


def test_rtk_recovery_is_charged_to_rtk_not_tokenizer(tmp_path):
    original = "RTK retained original\n" * 30
    ref = ContextCache().store(original, source="rtk")
    result = runner.invoke(app, ["retrieve", ref])
    assert result.exit_code == 0 and result.stdout == original
    data = monitor(tmp_path).snapshot()
    assert data["today"] is None
    assert data["rtk"]["net"] == -((len(original.encode()) + 3) // 4)
    assert data["rtk"]["recovery"] == -data["rtk"]["net"]


@pytest.mark.parametrize("engine", ["none", "tokencut", "auto"])
@pytest.mark.parametrize("code", [0, 7])
def test_actual_adapter_invokes_command_once(tmp_path, monkeypatch, engine, code):
    marker = tmp_path / "calls"
    fake_git = tmp_path / "git"
    raw = "ERROR: diagnostic żółć 你好\n" + "  frame preserved\n" * 400
    fake_git.write_text(
        f"#!{sys.executable}\nfrom pathlib import Path\nimport sys\np=Path({str(marker)!r})\np.write_text(p.read_text()+'x' if p.exists() else 'x')\nsys.stdout.write({raw!r})\nsys.exit({code})\n"
    )
    fake_git.chmod(0o700)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    result = runner.invoke(app, ["run", "--engine", engine, "--", "git", "status"])
    assert result.exit_code == code
    assert result.stdout == raw
    assert marker.read_text() == "x"


def test_clear_does_not_restore_legacy_on_next_invocation(tmp_path):
    path = Path(os.environ["TOKENCUT_CACHE_DIR"]) / "cache.db"
    path.parent.mkdir()
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE telemetry_events(id INTEGER, timestamp REAL, raw_claude INT, compact_claude INT, raw_openai INT, compact_openai INT, raw_gemini INT, compact_gemini INT)"
        )
        conn.execute("INSERT INTO telemetry_events VALUES (1,1,100,10,100,10,100,10)")
    store = TelemetryStore()
    assert store.get_stats().total_runs == 1
    store.clear()
    assert TelemetryStore().get_stats().total_runs == 0


def test_recovery_ref_keeps_measurement_owner_for_identical_output():
    from tokencut.core.telemetry import recovery_engine

    raw = "same original output"
    cache = ContextCache()
    rtk = cache.store(raw, source="rtk", namespace="rtk")
    native = cache.store(raw, source="exec")
    assert native != rtk
    assert cache.retrieve(native) == cache.retrieve(rtk) == raw
    assert recovery_engine(rtk) == "rtk"
    assert recovery_engine(native) == "tokencut"
