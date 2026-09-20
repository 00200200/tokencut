from tokencut.mcp.server import (
    handle_tokencut_diff,
    handle_tokencut_exec,
    handle_tokencut_read,
    handle_tokencut_stats,
)


def test_handle_tokencut_exec():
    res = handle_tokencut_exec({"command": "echo 'Hello tokencut!'"})
    assert "Hello tokencut!" in res
    assert "tokencut: saved" in res


def test_handle_tokencut_read(tmp_path):
    f = tmp_path / "sample.py"
    f.write_text("def foo():\n    return 42\n")
    res = handle_tokencut_read({"path": str(f), "skeleton": True})
    assert "def foo():" in res
    assert "..." in res


def test_handle_tokencut_diff():
    res = handle_tokencut_diff({})
    assert isinstance(res, str)


def test_handle_tokencut_stats():
    stats = handle_tokencut_stats()
    assert "tokencut Session Savings:" in stats
    assert "Tokens Saved:" in stats
