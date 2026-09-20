import json
import subprocess
import sys
import threading
import time

import pytest

from tokencut.core import usage


def test_codex_weekly_primary_null_secondary_and_multi_bucket():
    payload = {
        "rateLimits": {"primary": {"usedPercent": 99}},
        "accountId": "private-account",
        "rateLimitsByLimitId": {
            "codex": {
                "primary": {"usedPercent": 39, "windowDurationMins": 10080, "resetsAt": 2000000000},
                "secondary": None,
            },
            "extra": {
                "limitName": "Extra",
                "primary": {"usedPercent": 0, "windowDurationMins": 300},
            },
        },
    }
    windows = usage.codex_windows(payload)
    assert len(windows) == 2
    assert windows[0]["label"] == "Tydzień"
    assert windows[0]["remaining_percent"] == 61
    assert windows[1]["remaining_percent"] == 100
    assert windows[1]["label"] == "Extra · 5 godzin"
    assert "private-account" not in json.dumps(windows)


@pytest.mark.parametrize("value", [None, True, "39", float("nan"), float("inf")])
def test_missing_or_invalid_usage_is_not_zero(value):
    assert usage.codex_windows({"rateLimits": {"primary": {"usedPercent": value}}}) == []


def test_claude_shape_reset_and_unavailable():
    result = usage.claude_windows(
        [
            {
                "provider": "claude",
                "identity": {"email": "private@example.com"},
                "usage": {
                    "primary": {
                        "usedPercent": 42,
                        "windowMinutes": 300,
                        "resetsAt": "2030-01-01T12:00:00Z",
                    },
                    "secondary": None,
                },
            }
        ]
    )
    assert result[0]["remaining_percent"] == 58
    assert result[0]["resets_at"] == 1893499200
    assert "private@" not in json.dumps(result)
    assert usage.claude_windows({"provider": "claude", "error": {"message": "private"}}) == []
    assert usage.claude_windows({"provider": "claude", "usage": None}) == []
    assert usage.window({"usedPercent": 110}, "primary")["remaining_percent"] == 0
    assert usage.window({"usedPercent": -5}, "primary")["remaining_percent"] == 100


def await_idle(collector):
    end = time.monotonic() + 3
    while collector.running:
        assert time.monotonic() < end
        time.sleep(0.005)


def test_collector_throttles_coalesces_and_clears_failed_refresh():
    now = [0]
    release = threading.Event()
    calls = []

    def fetch():
        calls.append(1)
        if len(calls) > 1:
            raise ValueError("error with private credential context")
        release.wait(2)
        return [
            {
                "id": "primary",
                "label": "Tydzień",
                "remaining_percent": 61,
                "used_percent": 39,
                "resets_at": None,
                "window_minutes": 10080,
            }
        ]

    collector = usage.UsageCollector({"codex": fetch}, clock=lambda: now[0])
    assert collector.snapshot()[0]["status"] == "loading"
    for _ in range(5):
        collector.snapshot(force=True)
    release.set()
    await_idle(collector)
    first = collector.snapshot()
    assert len(calls) == 1 and first[0]["windows"][0]["remaining_percent"] == 61
    first[0]["windows"].clear()
    assert collector.snapshot()[0]["windows"]
    now[0] = 299
    assert collector.snapshot()[0]["status"] == "ok"
    now[0] = 300
    collector.snapshot()
    await_idle(collector)
    failed = collector.snapshot()
    assert failed[0]["status"] == "unavailable" and not failed[0]["windows"]
    assert "private credential" not in json.dumps(failed)
    now[0] = 329
    collector.snapshot(force=True)
    assert len(calls) == 2
    now[0] = 330
    collector.snapshot(force=True)
    await_idle(collector)
    assert len(calls) == 3


def test_passed_reset_is_not_assumed_to_restore_limit():
    collector = usage.UsageCollector(
        {"codex": lambda: [usage.window({"usedPercent": 80, "resetsAt": 1}, "primary")]}
    )
    collector.snapshot()
    await_idle(collector)
    row = collector.snapshot()[0]
    assert row["status"] == "unavailable" and row["windows"] == []


def test_savings_snapshot_does_not_start_quota_probes(tmp_path, monkeypatch):
    from tokencut.core.monitor import Monitor

    def unexpected():
        pytest.fail("Savings must remain local and must not fetch account limits")

    monkeypatch.setattr(usage, "fetch_codex", unexpected)
    monkeypatch.setattr(usage, "fetch_claude", unexpected)
    service = Monitor([], tmp_path)
    assert "providers" not in service.dispatch({"method": "export"})
    assert not service.usage.running


def fake_executable(tmp_path, source):
    path = tmp_path / "helper"
    path.write_text(f"#!{sys.executable}\n" + source)
    path.chmod(0o700)
    return str(path)


def test_codex_adapter_only_initializes_and_reads_quota(tmp_path, monkeypatch):
    log = tmp_path / "methods.json"
    command = fake_executable(
        tmp_path,
        """import json, sys
seen = []
for line in sys.stdin:
    request = json.loads(line)
    seen.append(request["method"])
    if request["method"] == "initialize":
        print(json.dumps({"id": 1, "result": {"userAgent": "fixture"}}), flush=True)
    elif request["method"] == "account/rateLimits/read":
        with open("""
        + repr(str(log))
        + """, "w") as f: json.dump(seen, f)
        print(json.dumps({"method": "unrelated", "params": {}}), flush=True)
        print(json.dumps({"id": 2, "result": {"rateLimits": {"primary": {"usedPercent": 39, "windowDurationMins": 10080}}}}), flush=True)
""",
    )
    monkeypatch.setattr(usage, "executable", lambda name: command)
    windows = usage.fetch_codex()
    assert windows[0]["remaining_percent"] == 61
    assert json.loads(log.read_text()) == ["initialize", "initialized", "account/rateLimits/read"]


def test_claude_adapter_uses_cli_usage_without_cost_scan(tmp_path, monkeypatch):
    log = tmp_path / "arguments.json"
    command = fake_executable(
        tmp_path,
        """import json, sys
with open("""
        + repr(str(log))
        + """, "w") as f: json.dump(sys.argv[1:], f)
print(json.dumps([{"provider": "claude", "usage": {"primary": {"usedPercent": 20}}}]))
""",
    )
    monkeypatch.setattr(usage, "executable", lambda name: command)
    assert usage.fetch_claude()[0]["remaining_percent"] == 80
    assert json.loads(log.read_text()) == [
        "usage",
        "--provider",
        "claude",
        "--source",
        "cli",
        "--format",
        "json",
        "--json-only",
    ]


def test_pipe_timeout_and_response_size_bound(tmp_path, monkeypatch):
    command = fake_executable(tmp_path, "import time\ntime.sleep(10)\n")
    process = subprocess.Popen([command], stdout=subprocess.PIPE, start_new_session=True)
    try:
        with pytest.raises(TimeoutError):
            usage.JsonPipe(process, timeout=0.02).response(2)
    finally:
        usage.stop_process(process)
        process.stdout.close()
    assert process.poll() is not None
    command = fake_executable(tmp_path, "print('x' * 300)\n")
    monkeypatch.setattr(usage, "MAX_RESPONSE", 100)
    process = subprocess.Popen([command], stdout=subprocess.PIPE, start_new_session=True)
    try:
        with pytest.raises(ValueError, match="too large"):
            usage.JsonPipe(process).response(2)
    finally:
        usage.stop_process(process)
        process.stdout.close()
