from __future__ import annotations

from tokencut.core.doctor import (
    check_cache_db,
    check_chatgpt_desktop,
    check_claude_desktop_mcp,
    check_python,
    configure_claude_desktop_mcp,
    configure_cursor_mcp,
    configure_shell_alias,
    run_all_diagnostics,
)


def test_check_python():
    res = check_python()
    assert res.status in {"ok", "warning"}
    assert "Python" in res.name


def test_check_cache_db():
    res = check_cache_db()
    assert res.status == "ok"


def test_run_all_diagnostics():
    items = run_all_diagnostics()
    assert len(items) >= 4
    names = [i.name for i in items]
    assert "Python Environment" in names
    assert "CCR Cache Store" in names


def test_configure_cursor_mcp(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    ok, path = configure_cursor_mcp()
    assert ok is True
    cursor_file = tmp_path / ".cursor" / "mcp.json"
    assert cursor_file.exists()
    assert "tokencut" in cursor_file.read_text()


def test_configure_shell_alias(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("SHELL", "/bin/zsh")
    ok, path = configure_shell_alias()
    assert ok is True
    zshrc = tmp_path / ".zshrc"
    assert zshrc.exists()
    assert "alias cc=" in zshrc.read_text()


def test_check_claude_desktop():
    res = check_claude_desktop_mcp()
    assert res.status in {"ok", "missing", "warning"}


def test_check_chatgpt_desktop():
    res = check_chatgpt_desktop()
    assert res.status == "ok"


def test_configure_claude_desktop(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    ok, path = configure_claude_desktop_mcp()
    assert ok is True
    cfg_file = (
        tmp_path / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    )
    assert cfg_file.exists()
    assert "tokencut" in cfg_file.read_text()
