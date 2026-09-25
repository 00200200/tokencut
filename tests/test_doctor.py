from __future__ import annotations

import json
import os
import sqlite3
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from usagetrim.core import doctor
from usagetrim.core.cache import ContextCache
from usagetrim.core.doctor import (
    check_cache_db,
    check_chatgpt_desktop,
    check_claude_desktop_mcp,
    check_codex_mcp,
    check_python,
    check_windsurf_mcp,
    configure_claude_desktop_mcp,
    configure_cursor_mcp,
    configure_shell_alias,
    configure_windsurf_mcp,
    run_all_diagnostics,
)


def test_check_python():
    res = check_python()
    assert res.status in {"ok", "warning"}
    assert "Python" in res.name


def test_check_cache_db():
    res = check_cache_db()
    assert res.status == "ok"


def test_check_cache_counts_actual_entries_without_altering_schema():
    cache = ContextCache()
    cache.store("first distinct output")
    cache.store("second distinct output")
    with sqlite3.connect(cache.db_path) as connection:
        before = connection.execute("SELECT name, sql FROM sqlite_master ORDER BY name").fetchall()
    result = check_cache_db()
    assert result.status == "ok"
    assert "2 cached entries" in result.message
    with sqlite3.connect(cache.db_path) as connection:
        after = connection.execute("SELECT name, sql FROM sqlite_master ORDER BY name").fetchall()
    assert after == before


def test_check_missing_cache_does_not_create_database():
    path = Path(os.environ["USAGETRIM_CACHE_DIR"]) / "cache.db"
    assert not path.exists()
    result = check_cache_db()
    assert result.status == "ok"
    assert "first run" in result.message
    assert not path.exists()


def test_run_all_diagnostics():
    items = run_all_diagnostics()
    assert len(items) >= 4
    names = [i.name for i in items]
    assert "Python Environment" in names
    assert "CCR Cache Store" in names


def test_configure_cursor_mcp(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(doctor.shutil, "which", lambda _: str(tmp_path / "bin" / "usagetrim"))
    ok, path = configure_cursor_mcp()
    assert ok is True
    cursor_file = tmp_path / ".cursor" / "mcp.json"
    assert cursor_file.exists()
    assert "usagetrim" in cursor_file.read_text()


def test_configure_shell_alias(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
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
    assert res.status == "warning"
    assert "does not support local stdio MCP" in res.message
    assert "Codex" in res.remedy


def test_configure_claude_desktop(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(doctor.shutil, "which", lambda _: str(tmp_path / "bin" / "usagetrim"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    ok, path_str = configure_claude_desktop_mcp()
    assert ok is True
    cfg_file = Path(path_str)
    assert cfg_file.exists()
    assert "usagetrim" in cfg_file.read_text()


@pytest.fixture
def local_install(tmp_path, monkeypatch):
    executable = tmp_path / "bin" / "usagetrim"
    monkeypatch.setattr(doctor.shutil, "which", lambda _: str(executable))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    return executable


@pytest.mark.parametrize("client", ["claude", "cursor"])
def test_mcp_install_preserves_settings_and_backs_up_once(tmp_path, local_install, client):
    target = tmp_path / "claude.json" if client == "claude" else tmp_path / ".cursor" / "mcp.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    original = {
        "theme": "dark",
        "mcpServers": {
            "other": {"command": "other", "env": {"SETTING": "kept"}},
            "usagetrim": {
                "command": "uvx",
                "args": ["usagetrim", "mcp"],
                "env": {"LOCAL": "kept"},
                "disabled": False,
            },
        },
    }
    original_bytes = json.dumps(original, separators=(",", ":")).encode()
    target.write_bytes(original_bytes)
    target.chmod(0o640)
    configure = (
        (lambda: configure_claude_desktop_mcp(target))
        if client == "claude"
        else configure_cursor_mcp
    )
    assert configure() == (True, str(target))
    changed = json.loads(target.read_text())
    assert changed["theme"] == "dark"
    assert changed["mcpServers"]["other"] == original["mcpServers"]["other"]
    # Cursor gets the compact coding profile; Claude Desktop keeps the plain server.
    expected_args = ["mcp"] if client == "claude" else ["mcp", "--profile", "coding"]
    assert changed["mcpServers"]["usagetrim"] == {
        "command": str(local_install),
        "args": expected_args,
        "env": {"LOCAL": "kept"},
        "disabled": False,
    }
    assert target.stat().st_mode & 0o777 == 0o640
    backups = list(target.parent.glob(target.name + ".pre-usagetrim-*"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == original_bytes
    installed_bytes, modified_ns = target.read_bytes(), target.stat().st_mtime_ns
    assert configure() == (True, str(target))
    assert target.read_bytes() == installed_bytes
    assert target.stat().st_mtime_ns == modified_ns
    assert list(target.parent.glob(target.name + ".pre-usagetrim-*")) == backups


@pytest.mark.parametrize(
    "raw",
    ["{bad json", "[]", "null", '{"mcpServers": []}', '{"mcpServers": {"usagetrim": "broken"}}'],
)
@pytest.mark.parametrize("client", ["claude", "cursor"])
def test_malformed_config_is_untouched(tmp_path, local_install, raw, client):
    target = tmp_path / "claude.json" if client == "claude" else tmp_path / ".cursor" / "mcp.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(raw)
    configure = (
        (lambda: configure_claude_desktop_mcp(target))
        if client == "claude"
        else configure_cursor_mcp
    )
    ok, message = configure()
    assert not ok
    assert "not overwritten" in message
    assert target.read_text() == raw
    assert list(target.parent.glob(target.name + ".*")) == []


def test_installer_refuses_to_replace_remote_transport(tmp_path, local_install):
    target = tmp_path / "config.json"
    raw = '{"mcpServers": {"usagetrim": {"url": "https://example.invalid/mcp"}}}'
    target.write_text(raw)
    ok, message = configure_claude_desktop_mcp(target)
    assert not ok and "another transport" in message
    assert target.read_text() == raw


def test_installer_uses_verified_current_interpreter_when_entrypoint_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda _: None)
    interpreter = tmp_path / "venv" / "bin" / "python"
    monkeypatch.setattr(doctor.sys, "executable", str(interpreter))
    probes = []

    def probe(args, **kwargs):
        probes.append((args, kwargs))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(doctor.subprocess, "run", probe)
    target = tmp_path / "config.json"
    assert configure_claude_desktop_mcp(target)[0]
    assert json.loads(target.read_text())["mcpServers"]["usagetrim"] == {
        "command": str(interpreter),
        "args": ["-m", "usagetrim.cli", "mcp"],
    }
    assert probes[0][0][:3] == [str(interpreter), "-I", "-c"]
    assert probes[0][1]["timeout"] == 5
    assert not list(tmp_path.glob("*.pre-usagetrim-*"))


@pytest.mark.parametrize("failure", ["unavailable", "timeout", "nonzero"])
def test_no_usable_installation_does_not_write_config(tmp_path, monkeypatch, failure):
    monkeypatch.setattr(doctor.shutil, "which", lambda _: None)

    def probe(*args, **kwargs):
        if failure == "unavailable":
            raise OSError("no interpreter")
        if failure == "timeout":
            raise subprocess.TimeoutExpired("python", 5)
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(doctor.subprocess, "run", probe)
    target = tmp_path / "new" / "config.json"
    ok, message = configure_claude_desktop_mcp(target)
    assert not ok and "No usable local UsageTrim installation" in message
    assert not target.parent.exists()


def test_atomic_replace_failure_leaves_existing_config_and_backup_intact(
    tmp_path, local_install, monkeypatch
):
    target = tmp_path / "config.json"
    original = '{"other_setting": "preserve"}\n'
    target.write_text(original)

    def fail_replace(*args, **kwargs):
        raise OSError("atomic replacement denied")

    monkeypatch.setattr(Path, "replace", fail_replace)
    ok, message = configure_claude_desktop_mcp(target)
    assert not ok and "atomic replacement denied" in message
    assert target.read_text() == original
    assert not list(tmp_path.glob("*.tmp-*"))
    assert next(tmp_path.glob("*.pre-usagetrim-*")).read_text() == original


@pytest.mark.parametrize("installed", [True, False])
def test_codex_registration_is_distinguished_from_runtime_connectivity(
    tmp_path, monkeypatch, installed
):
    monkeypatch.setattr(doctor, "_codex_available", lambda: installed)
    target = tmp_path / "config.toml"
    target.write_text('[mcp_servers.usagetrim]\ncommand = "/local/bin/usagetrim"\nargs = ["mcp"]\n')
    result = check_codex_mcp(target)
    assert result.status == ("ok" if installed else "warning")
    assert "Runtime connectivity is untested" in result.message
    assert "Codex" in result.name
    assert "ChatGPT" not in result.name


@pytest.mark.parametrize(
    "config, status, phrase",
    [
        (None, "missing", "not registered"),
        ("bad = [", "warning", "cannot validate"),
        ('[mcp_servers.usagetrim]\ncommand="local"\nenabled=false', "warning", "disabled"),
        (
            '[mcp_servers.usagetrim]\ncommand="uvx"\nargs=["usagetrim", "mcp"]',
            "warning",
            "needs a PyPI release",
        ),
        ('[mcp_servers.usagetrim]\nurl="https://example.invalid"', "warning", "local server"),
    ],
)
def test_codex_missing_disabled_or_invalid_is_not_marked_working(
    tmp_path, monkeypatch, config, status, phrase
):
    monkeypatch.setattr(doctor, "_codex_available", lambda: True)
    target = tmp_path / "config.toml"
    if config is not None:
        target.write_text(config)
    result = check_codex_mcp(target)
    assert result.status == status
    assert phrase in result.message


def test_check_windsurf_mcp():
    res = check_windsurf_mcp()
    assert res.status in {"ok", "missing", "warning"}
    assert "Windsurf" in res.name


def test_configure_windsurf_mcp(tmp_path, monkeypatch):
    target = tmp_path / "mcp_config.json"
    monkeypatch.setattr(doctor, "get_windsurf_mcp_config_path", lambda: target)
    monkeypatch.setattr(
        doctor,
        "_local_mcp_command",
        lambda profile=None: {
            "command": "/bin/usagetrim",
            "args": ["mcp", "--profile", profile] if profile else ["mcp"],
        },
    )
    ok, path_str = configure_windsurf_mcp(target)
    assert ok is True
    assert target.exists()
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["mcpServers"]["usagetrim"]["args"] == ["mcp", "--profile", "coding"]


def test_configure_codex_mcp(tmp_path, monkeypatch):
    target = tmp_path / "config.toml"
    monkeypatch.setattr(doctor, "get_codex_config_path", lambda: target)
    monkeypatch.setattr(
        doctor,
        "_local_mcp_command",
        lambda profile=None: {
            "command": "/bin/usagetrim",
            "args": ["mcp", "--profile", profile] if profile else ["mcp"],
        },
    )
    ok, path_str = doctor.configure_codex_mcp(target, profile="desktop")
    assert ok is True
    assert target.exists()
    content = target.read_text(encoding="utf-8")
    assert "[mcp_servers.usagetrim]" in content
    assert 'command = "/bin/usagetrim"' in content
    assert '"--profile"' in content
    assert '"desktop"' in content


def test_configure_claude_desktop_mcp_with_profile(tmp_path, monkeypatch):
    target = tmp_path / "claude_desktop_config.json"
    monkeypatch.setattr(doctor, "get_claude_desktop_config_path", lambda: target)
    monkeypatch.setattr(
        doctor,
        "_local_mcp_command",
        lambda profile=None: {
            "command": "/bin/usagetrim",
            "args": ["mcp", "--profile", profile] if profile else ["mcp"],
        },
    )
    ok, path_str = doctor.configure_claude_desktop_mcp(target, profile="desktop")
    assert ok is True
    data = json.loads(target.read_text(encoding="utf-8"))
    assert "usagetrim" in data["mcpServers"]
    assert data["mcpServers"]["usagetrim"]["args"] == ["mcp", "--profile", "desktop"]


def test_configure_shell_alias_fish(tmp_path):
    fish_config = tmp_path / "config.fish"
    ok, path_str = configure_shell_alias(fish_config)
    assert ok is True
    content = fish_config.read_text(encoding="utf-8")
    assert "alias cc 'usagetrim run --'" in content


@pytest.mark.parametrize(
    "shell, content, status",
    [
        ("zsh", 'alias cc="gcc"', "warning"),
        ("fish", "alias cc 'gcc'", "warning"),
        ("fish", "alias ccache 'usagetrim run --'", "missing"),
        ("fish", "# alias cc 'usagetrim run --'", "missing"),
        ("zsh", '# alias cc="usagetrim run --"', "missing"),
        ("zsh", 'alias cc="usagetrim run --"\nalias cc="gcc"', "warning"),
        ("zsh", 'alias cc="usagetrim run --"', "ok"),
        ("fish", "alias cc 'usagetrim run --'", "ok"),
    ],
)
def test_alias_diagnostic_identifies_the_actual_shortcut(
    tmp_path, monkeypatch, shell, content, status
):
    monkeypatch.setenv("SHELL", f"/bin/{shell}")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    config = tmp_path / (".config/fish/config.fish" if shell == "fish" else ".zshrc")
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(content)
    assert doctor.check_shell_alias().status == status


@pytest.mark.parametrize(
    "entry",
    [
        {"command": "usagetrim", "disabled": True},
        {"command": "usagetrim", "enabled": False},
        {"command": ""},
        {"command": "usagetrim", "args": "mcp"},
        None,
    ],
)
def test_windsurf_disabled_or_malformed_entry_is_not_reported_ready(tmp_path, monkeypatch, entry):
    target = tmp_path / "mcp_config.json"
    target.write_text(json.dumps({"mcpServers": {"usagetrim": entry}}))
    monkeypatch.setattr(doctor, "get_windsurf_mcp_config_path", lambda: target)
    assert check_windsurf_mcp().status == "warning"
