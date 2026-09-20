import io
import json
import sys

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


def test_handle_tokencut_exec():
    res = handle_tokencut_exec({"command": "echo 'Hello tokencut!'"})
    assert "Hello tokencut!" in res
    assert "tokencut: saved" in res


def test_handle_tokencut_exec_budget():
    res = handle_tokencut_exec({"command": "echo 'Hello budget!'", "budget": 100})
    assert "Hello budget!" in res


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


def test_handle_tokencut_stats():
    stats = handle_tokencut_stats()
    assert "tokencut Session Savings:" in stats
    assert "Tokens Saved:" in stats


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
    assert len(responses[1]["result"]["tools"]) == 7
    assert responses[2]["id"] == 3
    assert "tokencut Session Savings" in responses[2]["result"]["content"][0]["text"]
