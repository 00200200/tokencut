import io
import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from typer.testing import CliRunner

from usagetrim.cli import app
from usagetrim.core.companion_state import update_settings
from usagetrim.core.context_hooks import context_hook, install_context_hooks, run_context_hook
from usagetrim.core.monitor import Monitor
from usagetrim.core.task_context import TaskContext, context_path, context_summary, dispatch_context
from usagetrim.core.telemetry import TelemetryStore
from usagetrim.mcp.server import _respond
from usagetrim.metrics.tokenizer import count_tokens


def note(goal="Ship the fix", **extra):
    return {
        "goal": goal,
        "constraints": ["Preserve user edits", "No paid API calls"],
        "next_steps": ["Run affected checks"],
        **extra,
    }


def event(tmp_path, name="SessionStart", **extra):
    return {
        "session_id": "session-1",
        "cwd": str(tmp_path),
        "hook_event_name": name,
        "source": "compact",
        **extra,
    }


def test_revision_conflicts_history_and_idempotent_retry(tmp_path):
    store = TaskContext()
    root = str(tmp_path)
    first = store.save(root, "one", note(), 0)
    assert first["revision"] == 1
    assert store.save(root, "one", note(), 0)["saved"] is False
    store.save(root, "one", note("Second goal"), 1)
    with pytest.raises(ValueError, match="Revision conflict"):
        store.save(root, "one", note("Stale update"), 1)
    assert store.read(root, "one", 1)["checkpoint"]["goal"] == "Ship the fix"
    assert store.read(root, "one")["checkpoint"]["goal"] == "Second goal"
    for revision in range(2, 24):
        store.save(root, "one", note(str(revision)), revision)
    assert not store.read(root, "one", 1)["found"]
    with store.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM checkpoints").fetchone()[0] == 20


def test_sessions_and_projects_do_not_restore_each_others_notes(tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    store = TaskContext()
    store.save(str(tmp_path), "codex:session-1", note("PRIVATE_TASK"), 0)
    matching = context_hook(event(tmp_path), "codex")
    assert "PRIVATE_TASK" in json.dumps(matching)
    for payload, client in (
        (event(other), "codex"),
        (event(tmp_path, session_id="session-2"), "codex"),
        (event(tmp_path), "claude-code"),
    ):
        assert "PRIVATE_TASK" not in json.dumps(context_hook(payload, client))
    assert "PRIVATE_TASK" not in json.dumps(store.list(str(tmp_path)))


@pytest.mark.parametrize(
    "checkpoint",
    [
        None,
        {},
        {"goal": ""},
        {"goal": True},
        {"goal": "g", "constraints": "text"},
        {"goal": "g", "unknown": "field"},
        {"goal": "g", "references": [False]},
    ],
)
def test_invalid_checkpoint_never_replaces_saved_constraints(tmp_path, checkpoint):
    store = TaskContext()
    store.save(str(tmp_path), "one", note(), 0)
    with pytest.raises(ValueError):
        store.save(str(tmp_path), "one", checkpoint, 1)
    assert store.read(str(tmp_path), "one")["checkpoint"]["constraints"] == note()["constraints"]


def test_oversized_notes_are_rejected_without_truncating_constraints(tmp_path):
    store = TaskContext()
    with pytest.raises(ValueError, match="Nothing saved"):
        store.save(str(tmp_path), "one", note(constraints=["🦄" * 800] * 3), 0)
    assert not store.read(str(tmp_path), "one")["found"]


def test_parallel_updates_cannot_overwrite_a_newer_revision(tmp_path):
    TaskContext().save(str(tmp_path), "one", note(), 0)

    def update(index):
        try:
            return TaskContext().save(str(tmp_path), "one", note(str(index)), 1)["revision"]
        except ValueError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=4) as pool:
        outcomes = list(pool.map(update, range(4)))
    assert outcomes.count(2) == 1
    assert outcomes.count("conflict") == 3


def test_forget_requires_current_revision_and_removes_all_retained_notes(tmp_path):
    store = TaskContext()
    store.save(str(tmp_path), "one", note("ERASE_ME"), 0)
    store.save(str(tmp_path), "one", note("ERASE_ME_TOO"), 1)
    with pytest.raises(ValueError):
        store.forget(str(tmp_path), "one", 1)
    assert store.forget(str(tmp_path), "one", 2)["forgotten"]
    assert not store.read(str(tmp_path), "one")["found"]
    assert b"ERASE_ME" not in context_path().read_bytes()


def test_hooks_do_not_open_transcripts_or_save_prompts_or_native_summaries(tmp_path):
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text("DO_NOT_READ_TRANSCRIPT")
    payload = event(
        tmp_path,
        "PostCompact",
        transcript_path=str(transcript),
        prompt="DO_NOT_STORE_PROMPT",
        compact_summary="DO_NOT_STORE_SUMMARY",
    )
    assert context_hook(payload, "claude-code") == {}
    assert b"DO_NOT_" not in context_path().read_bytes()
    assert transcript.read_text() == "DO_NOT_READ_TRANSCRIPT"
    summary = context_summary([context_path().parent])
    assert summary["last_compact"] is not None
    assert summary["tasks"] == 0


def test_restoration_is_prepared_overhead_not_savings_and_exports_are_private(tmp_path):
    store = TaskContext()
    store.save(str(tmp_path), "codex:session-1", note("PRIVATE_CONTENT"), 0)
    hook = context_hook(event(tmp_path), "codex")
    text = hook["hookSpecificOutput"]["additionalContext"]
    assert "Newer" in text or "newer" in text
    assert count_tokens(text).openai <= 2200
    snapshot = Monitor([context_path().parent], tmp_path / "monitor").dispatch({"method": "export"})
    assert "PRIVATE_CONTENT" not in json.dumps(snapshot)
    assert "session-1" not in json.dumps(snapshot)
    assert snapshot["today"] is None
    assert snapshot["prepared"]["net"] == -count_tokens(text).openai
    assert snapshot["context"]["last_restore"] is not None
    assert b"PRIVATE_CONTENT" not in TelemetryStore().db_path.read_bytes()


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        {"hook_event_name": "UserPromptSubmit"},
        {"hook_event_name": "SessionStart", "source": "clear"},
    ],
)
def test_unsupported_hooks_are_silent_and_do_not_create_state(payload):
    assert context_hook(payload, "codex") == {}
    assert not context_path().exists()


def test_pause_and_unavailable_cache_never_block_conversation(tmp_path, monkeypatch):
    update_settings(paused=True)
    assert context_hook(event(tmp_path), "codex") == {}
    update_settings(paused=False)
    blocked = tmp_path / "not-a-directory"
    blocked.write_text("x")
    monkeypatch.setenv("USAGETRIM_CACHE_DIR", str(blocked))
    output = io.StringIO()
    run_context_hook("codex", io.StringIO(json.dumps(event(tmp_path))), output)
    assert json.loads(output.getvalue()) == {}
    output = io.StringIO()
    run_context_hook("codex", io.StringIO("{"), output)
    assert json.loads(output.getvalue()) == {}


@pytest.mark.parametrize("client", ["codex", "claude-code"])
def test_install_preserves_hooks_backs_up_and_is_idempotent(tmp_path, client):
    config = tmp_path / "settings.json"
    existing = {
        "permissions": {"deny": ["Bash(rm:*)"]},
        "hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "existing-hook"}]}]},
    }
    config.write_text(json.dumps(existing))
    executable = tmp_path / "tool with spaces"
    executable.touch()
    install_context_hooks(client, executable, tmp_path / "cache", config)
    first = config.read_bytes()
    install_context_hooks(client, executable, tmp_path / "cache", config)
    assert first == config.read_bytes()
    installed = json.loads(first)
    assert installed["permissions"] == existing["permissions"]
    assert installed["hooks"]["SessionStart"][0] == existing["hooks"]["SessionStart"][0]
    backups = list(tmp_path.glob("*.pre-usagetrim-context-*"))
    assert len(backups) == 1
    assert json.loads(backups[0].read_text()) == existing
    assert backups[0].stat().st_mode & 0o777 == 0o600


def test_install_rejects_malformed_hooks_without_modifying_config(tmp_path):
    config = tmp_path / "settings.json"
    original = '{"hooks":{"PostCompact":{}}}'
    config.write_text(original)
    executable = tmp_path / "usagetrim"
    executable.touch()
    with pytest.raises(ValueError):
        install_context_hooks("codex", executable, tmp_path, config)
    assert config.read_text() == original


def test_reconfigure_cache_replaces_owned_handlers_without_duplicate_injection(tmp_path):
    config = tmp_path / "hooks.json"
    executable = tmp_path / "usagetrim"
    executable.touch()
    install_context_hooks("codex", executable, tmp_path / "old", config)
    install_context_hooks("codex", executable, tmp_path / "new", config)
    data = json.loads(config.read_text())
    for entries in data["hooks"].values():
        assert len(entries) == 1
        assert len(entries[0]["hooks"]) == 1
        assert str(tmp_path / "new") in entries[0]["hooks"][0]["command"]


def test_monitor_handles_missing_corrupt_and_duplicate_sources(tmp_path):
    source = context_path().parent
    assert context_summary([source])["available"] is False
    assert not source.exists()
    TaskContext().save(str(tmp_path), "one", note(), 0)
    assert context_summary([source, source])["tasks"] == 1
    context_path().write_bytes(b"corrupt")
    assert context_summary([source])["issues"]


def test_mcp_and_cli_roundtrip_redaction_and_negative_accounting(tmp_path):
    secret = "ghp_" + "a" * 36
    request = {
        "action": "save",
        "root": str(tmp_path),
        "task": "one",
        "expected_revision": 0,
        "checkpoint": note(secret),
    }
    response = _respond(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "usagetrim_context", "arguments": request},
        }
    )
    assert not response["result"]["isError"]
    read = {"action": "read", "root": str(tmp_path), "task": "one"}
    result = CliRunner().invoke(app, ["context"], input=json.dumps(read))
    assert result.exit_code == 0, result.output
    assert secret not in result.output
    assert "REDACTED_GITHUB_TOKEN" in result.output
    assert context_path().stat().st_mode & 0o777 == 0o600
    assert secret.encode() not in context_path().read_bytes()
    with TelemetryStore().connect() as conn:
        assert conn.execute("SELECT SUM(raw_openai - compact_openai) FROM events").fetchone()[0] < 0


@pytest.mark.parametrize(
    "payload",
    [
        {"action": "save", "root": ".", "task": "t"},
        {"action": "read", "root": "/", "task": "../escape"},
        {"action": "oops", "root": "/", "task": "t"},
    ],
)
def test_invalid_requests_do_not_create_a_store(payload):
    with pytest.raises(ValueError):
        dispatch_context(payload)
    assert not context_path().exists()
