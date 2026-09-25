import copy
import io
import json
import stat
import subprocess

import pytest
from typer.testing import CliRunner

from usagetrim.cli import app
from usagetrim.core import native_hooks


def _event():
    return {
        "hook_event_name": "PostToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "pytest -vv", "timeout": 30000},
        "tool_response": {
            "stdout": "".join(
                f"tests/test_api.py::test_case_{i} PASSED [ 80%]\n" for i in range(80)
            ),
            "stderr": "WARNING: endpoint unavailable\nTraceback:\n  app.py:42\n",
            "exitCode": 1,
            "interrupted": False,
            "isImage": False,
            "durationMs": 1234,
            "futureMetadata": {"nested": [1, "keep me", None]},
        },
    }


def test_claude_compacts_stdout_without_changing_failure_or_metadata():
    event = _event()
    before = copy.deepcopy(event)
    response = native_hooks.claude_post_tool_use(event)

    hook = response["hookSpecificOutput"]
    assert hook["hookEventName"] == "PostToolUse"
    result = hook["updatedToolOutput"]
    assert "80 passing tests" in result["stdout"]
    assert len(result["stdout"]) < len(before["tool_response"]["stdout"])
    assert {k: v for k, v in result.items() if k != "stdout"} == {
        k: v for k, v in before["tool_response"].items() if k != "stdout"
    }
    assert event == before
    assert set(response) == {"hookSpecificOutput"}
    assert set(hook) == {"hookEventName", "updatedToolOutput"}


@pytest.mark.parametrize(
    "field,value",
    [
        ("hook_event_name", "PreToolUse"),
        ("hook_event_name", "PostToolUseFailure"),
        ("tool_name", "Read"),
        ("tool_name", "mcp__usagetrim__exec"),
        ("tool_response", "raw response"),
        ("tool_response", None),
        ("tool_input", []),
        ("tool_input", {"command": ["pytest"]}),
    ],
)
def test_unrecognized_event_fails_open(field, value):
    event = _event()
    event[field] = value
    assert native_hooks.claude_post_tool_use(event) == {}


@pytest.mark.parametrize("value", [None, [], "event", 0, {}])
def test_invalid_payload_fails_open(value):
    assert native_hooks.claude_post_tool_use(value) == {}


@pytest.mark.parametrize(
    "field,value",
    [
        ("interrupted", True),
        ("isImage", True),
        ("stdout", ["not text"]),
        ("stderr", {"error": "not text"}),
    ],
)
def test_unsupported_tool_output_is_not_partially_replaced(field, value):
    event = _event()
    event["tool_response"][field] = value
    assert native_hooks.claude_post_tool_use(event) == {}


def test_unchanged_short_output_does_not_add_context():
    event = _event()
    event["tool_response"]["stdout"] = "done\n"
    assert native_hooks.claude_post_tool_use(event) == {}


@pytest.mark.parametrize(
    "client,raw",
    [
        ("claude", "{bad json"),
        ("claude", ""),
        ("claude", "[]"),
        ("codex", json.dumps(_event())),
        ("claude", " " * (8 * 1024 * 1024 + 1)),
    ],
)
def test_protocol_fail_open_emits_only_empty_json(client, raw, capsys):
    output = io.StringIO()
    native_hooks.run_hook_filter(client, io.StringIO(raw), output)
    assert output.getvalue() == "{}\n"
    assert capsys.readouterr() == ("", "")


def test_filter_failure_does_not_break_hook_or_emit_logs(monkeypatch, capsys):
    def fail(*args, **kwargs):
        raise OSError("unavailable local cache")

    monkeypatch.setattr(native_hooks, "safe_compact_output", fail)
    output = io.StringIO()
    native_hooks.run_hook_filter("claude", io.StringIO(json.dumps(_event())), output)
    assert output.getvalue() == "{}\n"
    assert capsys.readouterr() == ("", "")


def test_cli_hook_filter_outputs_one_valid_protocol_object():
    result = CliRunner().invoke(
        app, ["hook-filter", "--client", "claude"], input=json.dumps(_event())
    )
    assert result.exit_code == 0
    assert result.stderr == ""
    assert len(result.stdout.splitlines()) == 1
    response = json.loads(result.stdout)
    assert response["hookSpecificOutput"]["updatedToolOutput"]["exitCode"] == 1
    assert "80 passing tests" in response["hookSpecificOutput"]["updatedToolOutput"]["stdout"]


@pytest.fixture
def executable(tmp_path):
    path = tmp_path / "bin" / "usagetrim"
    path.parent.mkdir()
    path.write_text("#!/bin/sh\nprintf '%s\\n' \"$@\"\n")
    path.chmod(0o755)
    return path


def test_install_preserves_hooks_permissions_and_original_backup(tmp_path, executable):
    settings = tmp_path / "settings.json"
    original = {
        "permissions": {"allow": ["Bash(git status)"], "deny": ["Read(.env)"]},
        "hooks": {
            "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "audit"}]}],
            "PostToolUse": [
                {"matcher": "Bash|Read", "hooks": [{"type": "command", "command": "existing"}]}
            ],
        },
        "env": {"LANG": "pl_PL.UTF-8"},
    }
    raw = json.dumps(original, ensure_ascii=False, indent=4) + "\n"
    settings.write_text(raw)
    settings.chmod(0o640)

    assert native_hooks.install_claude_hook(executable, settings) == settings
    installed = json.loads(settings.read_text())
    assert installed["permissions"] == original["permissions"]
    assert installed["env"] == original["env"]
    assert installed["hooks"]["PreToolUse"] == original["hooks"]["PreToolUse"]
    added = len(native_hooks.HOOK_MATCHERS)
    assert installed["hooks"]["PostToolUse"][:-added] == original["hooks"]["PostToolUse"]
    assert [e["matcher"] for e in installed["hooks"]["PostToolUse"][-added:]] == [
        "^Bash$",
        "^mcp__",
    ]
    assert stat.S_IMODE(settings.stat().st_mode) == 0o640
    backups = list(tmp_path.glob("settings.json.pre-usagetrim-*"))
    assert len(backups) == 1
    assert backups[0].read_text() == raw
    assert stat.S_IMODE(backups[0].stat().st_mode) == 0o640

    first_bytes, first_mtime = settings.read_bytes(), settings.stat().st_mtime_ns
    native_hooks.install_claude_hook(executable, settings)
    assert settings.read_bytes() == first_bytes
    assert settings.stat().st_mtime_ns == first_mtime
    assert list(tmp_path.glob("settings.json.pre-usagetrim-*")) == backups


@pytest.mark.parametrize(
    "raw",
    [
        "{broken",
        "[]",
        "null",
        '{"hooks": []}',
        '{"hooks": {"PostToolUse": {}}}',
        '{"hooks": {"PostToolUse": [{"matcher": "^Bash$", "hooks": null}]}}',
        '{"hooks": {"PostToolUse": [{"matcher": "^Bash$", "hooks": "bad"}]}}',
        '{"hooks": {"PostToolUse": [{"matcher": "^Bash$", "hooks": {}}]}}',
        '{"hooks": {"PostToolUse": [{"matcher": "^Bash$", "hooks": ["bad"]}]}}',
        '{"hooks": {"PostToolUse": ["bad"]}}',
        '{"hooks": {"PostToolUse": [{"matcher": "^Bash$"}]}}',
    ],
)
def test_malformed_settings_are_never_overwritten(tmp_path, executable, raw):
    settings = tmp_path / "settings.json"
    settings.write_text(raw)
    with pytest.raises((ValueError, TypeError)):
        native_hooks.install_claude_hook(executable, settings)
    assert settings.read_text() == raw
    assert list(tmp_path.glob("settings.json.pre-usagetrim-*")) == []


def test_new_install_is_private_and_shell_quotes_executable(tmp_path):
    executable = tmp_path / "space's $(touch PWNED) bin" / "usagetrim"
    executable.parent.mkdir()
    executable.write_text("#!/bin/sh\nprintf '%s\\n' \"$@\"\n")
    executable.chmod(0o755)
    settings = tmp_path / "new claude home" / "settings.json"
    native_hooks.install_claude_hook(executable, settings)

    data = json.loads(settings.read_text())
    entry = data["hooks"]["PostToolUse"][0]
    assert entry["matcher"] == "^Bash$"
    assert stat.S_IMODE(settings.stat().st_mode) == 0o600
    command = entry["hooks"][0]["command"]
    result = subprocess.run(
        command, shell=True, cwd=tmp_path, text=True, capture_output=True, check=True
    )
    assert result.stdout.splitlines() == ["hook-filter", "--client", "claude"]
    assert result.stderr == ""
    assert not (tmp_path / "PWNED").exists()


def test_missing_executable_does_not_change_settings(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text('{"permissions": {"deny": ["Bash(*)"]}}')
    before = settings.read_bytes()
    with pytest.raises(FileNotFoundError):
        native_hooks.install_claude_hook(tmp_path / "missing", settings)
    assert settings.read_bytes() == before
    assert list(tmp_path.glob("settings.json.pre-usagetrim-*")) == []
