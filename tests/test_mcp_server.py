import io
import json
import re
import sys

import pytest

from tokencut.core.cache import ContextCache
from tokencut.mcp import server
from tokencut.mcp.server import (
    handle_tokencut_diff,
    handle_tokencut_exec,
    handle_tokencut_json,
    handle_tokencut_read,
    handle_tokencut_retrieve,
    handle_tokencut_stats,
    handle_tokencut_tree,
    run_mcp_stdio_server,
)
from tokencut.metrics.tokenizer import count_tokens


def test_handle_tokencut_exec():
    res = handle_tokencut_exec({"command": "echo 'Hello tokencut!'"})
    assert "Hello tokencut!" in res
    assert "exit code: 0" in res


def test_handle_tokencut_exec_budget():
    res = handle_tokencut_exec({"command": "printf '%10000s' x; exit 7", "budget": 100})
    assert count_tokens(res).claude <= 100
    assert "exit code: 7" in res
    ref = re.search(r"tc_[a-f0-9]+", res).group()
    assert ContextCache().retrieve(ref).endswith("x")


def test_handle_tokencut_read(tmp_path):
    f = tmp_path / "sample.py"
    f.write_text("def foo():\n    return 42\n")
    res = handle_tokencut_read({"path": str(f), "skeleton": True})
    assert "def foo():" in res
    assert "..." in res


def test_handle_tokencut_retrieve():
    res = handle_tokencut_retrieve({"ref_id": "tc_nonexistent"})
    assert "not found" in res


def test_handle_tokencut_diff():
    res = handle_tokencut_diff({})
    assert isinstance(res, str)


def test_handle_tokencut_tree(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "a.py").write_text("print(1)")
    res = handle_tokencut_tree({"path": str(tmp_path), "max_depth": 2})
    assert "a.py" in res


def test_handle_tokencut_json():
    raw = '[{"id": 1}, {"id": 2}, {"id": 3}, {"id": 4}]'
    res = handle_tokencut_json({"json_str": raw, "max_items": 2})
    assert "omitted by tokencut" in res


def test_json_small_lossy_preview_still_has_recoverable_original():
    raw = '[{"id":1},{"id":2},{"unique_schema":true}]'
    output = handle_tokencut_json({"json_str": raw, "max_items": 2})
    ref = re.search(r"tc_[a-f0-9]+", output).group()
    assert ContextCache().retrieve(ref) == raw


def test_json_protocol_bounds_redacts_and_accounts_for_returned_text(tmp_path, monkeypatch):
    raw = json.dumps(
        {
            "token": "ghp_" + "a" * 36,
            "entries": [{"id": i, "details": "diagnostic " * 50} for i in range(20)],
        }
    )
    path = tmp_path / "response.json"
    path.write_text(raw)
    monkeypatch.setattr(server, "_SESSION_SAVED_OPENAI", 0)
    response = server._respond(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "tokencut_json",
                "arguments": {"path": str(path), "max_tokens": 100},
            },
        }
    )
    assert not response["result"]["isError"]
    output = response["result"]["content"][0]["text"]
    assert count_tokens(output).claude <= 100
    ref = re.search(r"tc_[a-f0-9]+", output).group()
    recovered = ContextCache().retrieve(ref)
    assert "ghp_" + "a" * 36 not in output + recovered
    assert '"id": 19' in recovered
    assert server._SESSION_SAVED_OPENAI == count_tokens(raw).openai - count_tokens(output).openai


def test_tree_protocol_budget_and_recovery_do_not_claim_file_content_savings(tmp_path, monkeypatch):
    for i in range(30):
        (tmp_path / f"source_module_{i:02d}.py").write_text("print('hello')\n")
    root, _ = server.scan_directory(tmp_path, max_depth=2)
    raw = server.format_tree_as_text(root, root.tokens)
    monkeypatch.setattr(server, "_SESSION_SAVED_OPENAI", 0)
    response = server._respond(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "tokencut_tree",
                "arguments": {
                    "path": str(tmp_path),
                    "max_depth": 2,
                    "max_tokens": 100,
                },
            },
        }
    )
    assert not response["result"]["isError"]
    output = response["result"]["content"][0]["text"]
    assert count_tokens(output).claude <= 100
    ref = re.search(r"tc_[a-f0-9]+", output).group()
    assert ContextCache().retrieve(ref) == raw
    assert server._SESSION_SAVED_OPENAI == count_tokens(raw).openai - count_tokens(output).openai


@pytest.mark.parametrize(
    "name,arguments",
    [
        ("tokencut_json", {"json_str": "[1,2,3]", "max_items": -1}),
        ("tokencut_json", {"json_str": "[1,2,3]", "max_tokens": 0}),
        ("tokencut_tree", {"max_depth": -1}),
        ("tokencut_tree", {"max_depth": True}),
        ("tokencut_tree", {"max_tokens": 0}),
    ],
)
def test_new_tools_reject_invalid_limits(name, arguments):
    response = server._respond(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
    )
    assert response["result"]["isError"]


def test_handle_tokencut_stats():
    stats = handle_tokencut_stats()
    assert "tokencut Session Savings:" in stats
    assert "Estimated net text reduction" in stats


def test_mcp_stdio_protocol_loop(monkeypatch):
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "tokencut_stats", "arguments": {}},
        },
        {"jsonrpc": "2.0", "id": 4, "method": "ping", "params": {}},
    ]
    input_stream = io.StringIO("\n".join(json.dumps(r) for r in requests) + "\n")
    output_stream = io.StringIO()

    monkeypatch.setattr(sys, "stdin", input_stream)
    monkeypatch.setattr(sys, "stdout", output_stream)

    run_mcp_stdio_server()

    responses = [json.loads(line) for line in output_stream.getvalue().splitlines() if line.strip()]
    assert len(responses) == 4
    assert responses[0]["id"] == 1
    assert responses[0]["result"]["serverInfo"]["name"] == "tokencut"
    assert responses[1]["id"] == 2
    assert {tool["name"] for tool in responses[1]["result"]["tools"]} == {
        "tokencut_exec",
        "tokencut_read",
        "tokencut_retrieve",
        "tokencut_diff",
        "tokencut_tree",
        "tokencut_json",
        "tokencut_stats",
    }
    assert responses[2]["id"] == 3
    assert "tokencut Session Savings" in responses[2]["result"]["content"][0]["text"]


def test_mcp_read_bounds_single_huge_line_and_recovers(tmp_path):
    path = tmp_path / "huge.txt"
    raw = "payload with details " * 4000
    path.write_text(raw)
    output = handle_tokencut_read({"path": str(path), "max_tokens": 100})
    assert count_tokens(output).claude <= 100
    import re

    ref = re.search(r"tc_[a-f0-9]+", output).group()
    assert ContextCache().retrieve(ref) == raw


def test_exec_budget_includes_exit_status_and_recovers_deduplication():
    output = handle_tokencut_exec(
        {
            "command": "printf 'same line\\nsame line\\nsame line\\nsame line\\n'; exit 7",
            "max_tokens": 64,
        }
    )
    assert count_tokens(output).claude <= 64
    assert "exit code: 7" in output
    assert "Ref: tc_" in output


def test_exec_explicit_cwd(tmp_path):
    (tmp_path / "project.txt").write_text("correct project")
    output = handle_tokencut_exec({"command": "cat project.txt", "cwd": str(tmp_path)})
    assert "correct project" in output


def test_exec_default_preserves_unknown_long_output_and_full_diagnostics(monkeypatch):
    from subprocess import CompletedProcess

    raw = "".join(f"unique record {i}\n" for i in range(600))
    raw += (
        "Traceback (most recent call last):\n" + "stack frame\n" * 300 + "AssertionError: failure\n"
    )
    monkeypatch.setattr(server.subprocess, "run", lambda *a, **kw: CompletedProcess(a, 9, raw))
    output = handle_tokencut_exec({"command": "custom-command"})
    assert output == raw + "\n[exit code: 9]"


def test_exec_timeout_keeps_all_partial_diagnostics(monkeypatch):
    from subprocess import TimeoutExpired

    raw = ("Error: still waiting\n" * 300).encode()

    def timeout(*args, **kwargs):
        raise TimeoutExpired("custom-command", 120, output=raw)

    monkeypatch.setattr(server.subprocess, "run", timeout)
    output = handle_tokencut_exec({"command": "custom-command"})
    assert output.startswith(raw.decode())
    assert "timed out" in output


def test_diff_outside_repository_is_an_error(tmp_path):
    with pytest.raises(ValueError, match="git diff failed"):
        handle_tokencut_diff({"cwd": str(tmp_path)})


def test_short_output_overhead_and_retrieval_are_counted(monkeypatch):
    for name in ("_SESSION_SAVED_CLAUDE", "_SESSION_SAVED_OPENAI", "_SESSION_SAVED_GEMINI"):
        monkeypatch.setattr(server, name, 0)
    output = handle_tokencut_exec({"command": "printf hi"})
    expected = count_tokens("hi").claude - count_tokens(output).claude
    assert server._SESSION_SAVED_CLAUDE == expected < 0
    ref = ContextCache().store("previous output")
    retrieved = handle_tokencut_retrieve({"ref_id": ref})
    assert server._SESSION_SAVED_CLAUDE == expected - count_tokens(retrieved).claude


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"command": 42},
        {"command": "echo hi", "max_tokens": 1},
        {"command": "echo hi", "budget": 1},
        {"command": "echo hi", "budget": True},
        {"command": "echo hi", "max_lines": True},
    ],
)
def test_invalid_call_does_not_run_command(arguments, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("invalid arguments must not execute a command")

    monkeypatch.setattr(server.subprocess, "run", forbidden)
    response = server._respond(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "tokencut_exec", "arguments": arguments},
        }
    )
    assert response["result"]["isError"]
    assert server._respond({"jsonrpc": "2.0", "id": 2, "method": "ping"})["result"] == {}


def test_protocol_survives_bad_messages(monkeypatch):
    messages = [
        "{",
        "[]",
        '{"jsonrpc":"2.0","method":"notifications/initialized"}',
        '{"jsonrpc":"2.0","id":1,"method":"unknown"}',
        '{"jsonrpc":"2.0","id":2,"method":"ping"}',
    ]
    output = io.StringIO()
    monkeypatch.setattr(sys, "stdin", io.StringIO("\n".join(messages)))
    monkeypatch.setattr(sys, "stdout", output)
    run_mcp_stdio_server()
    responses = [json.loads(line) for line in output.getvalue().splitlines()]
    assert [r.get("error", {}).get("code") for r in responses] == [-32700, -32600, -32601, None]
    assert responses[-1]["id"] == 2
