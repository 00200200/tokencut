from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from tokencut.core.cache import ContextCache


@dataclass
class DiagnosticItem:
    name: str
    status: Literal["ok", "warning", "missing"]
    message: str
    remedy: str | None = None


def check_python() -> DiagnosticItem:
    ver = sys.version_info
    if ver.major == 3 and ver.minor >= 11:
        return DiagnosticItem(
            name="Python Environment",
            status="ok",
            message=f"Python {ver.major}.{ver.minor}.{ver.micro} (>= 3.11 supported)",
        )
    return DiagnosticItem(
        name="Python Environment",
        status="warning",
        message=f"Python {ver.major}.{ver.minor}.{ver.micro} (Recommended >= 3.11)",
        remedy="Install Python 3.11 or higher",
    )


def check_cache_db() -> DiagnosticItem:
    cache = ContextCache()
    db_path = cache.db_path
    if not db_path.exists():
        return DiagnosticItem(
            name="CCR Cache Store",
            status="ok",
            message=f"{db_path} (Ready, initialised on first run)",
        )

    try:
        size_kb = db_path.stat().st_size / 1024
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS context_entries (id TEXT PRIMARY KEY, content TEXT, timestamp REAL, source TEXT)"
            )
            cursor.execute("SELECT COUNT(*) FROM context_entries")
            count = cursor.fetchone()[0]
        return DiagnosticItem(
            name="CCR Cache Store",
            status="ok",
            message=f"{db_path} ({count} cached entries, {size_kb:.1f} KB)",
        )
    except Exception as e:
        return DiagnosticItem(
            name="CCR Cache Store",
            status="warning",
            message=f"Error reading {db_path}: {e}",
            remedy="Run `tokencut cache clear` to reset the database",
        )


def check_claude_cli() -> DiagnosticItem:
    claude_bin = shutil.which("claude")
    if claude_bin:
        return DiagnosticItem(
            name="Claude Code CLI",
            status="ok",
            message=f"Found at {claude_bin}",
        )
    return DiagnosticItem(
        name="Claude Code CLI",
        status="warning",
        message="Not found in PATH",
        remedy="Install via `npm install -g @anthropic-ai/claude-code` if using Claude Code",
    )


def check_cursor_mcp() -> DiagnosticItem:
    cursor_mcp_path = Path.home() / ".cursor" / "mcp.json"
    if not cursor_mcp_path.exists():
        return DiagnosticItem(
            name="Cursor MCP Config",
            status="missing",
            message="No ~/.cursor/mcp.json found",
            remedy="Run `tokencut install --cursor` to configure Cursor MCP",
        )

    try:
        data = json.loads(cursor_mcp_path.read_text(encoding="utf-8"))
        servers = data.get("mcpServers", {})
        if "tokencut" in servers:
            return DiagnosticItem(
                name="Cursor MCP Config",
                status="ok",
                message="tokencut registered in ~/.cursor/mcp.json",
            )
        return DiagnosticItem(
            name="Cursor MCP Config",
            status="missing",
            message="tokencut not configured in ~/.cursor/mcp.json",
            remedy="Run `tokencut install --cursor` to add tokencut to Cursor",
        )
    except Exception as e:
        return DiagnosticItem(
            name="Cursor MCP Config",
            status="warning",
            message=f"Invalid JSON in ~/.cursor/mcp.json: {e}",
            remedy="Fix syntax in ~/.cursor/mcp.json or re-run `tokencut install --cursor`",
        )


def check_shell_alias() -> DiagnosticItem:
    shell = os.environ.get("SHELL", "")
    rc_name = ".zshrc" if "zsh" in shell else ".bashrc"
    rc_path = Path.home() / rc_name

    if rc_path.exists():
        content = rc_path.read_text(encoding="utf-8", errors="ignore")
        if 'alias cc="tokencut' in content or "alias cc='tokencut" in content:
            return DiagnosticItem(
                name="Shell Alias (`cc`)",
                status="ok",
                message=f"Alias configured in ~/{rc_name}",
            )
    return DiagnosticItem(
        name="Shell Alias (`cc`)",
        status="missing",
        message=f"No `cc` alias found in ~/{rc_name}",
        remedy=f"Run `tokencut install --alias` to add shortcut to ~/{rc_name}",
    )


def get_claude_desktop_config_path() -> Path:
    if sys.platform == "darwin":
        return (
            Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
        )
    elif sys.platform == "win32":
        appdata = os.environ.get("APPDATA", "")
        base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
        return base / "Claude" / "claude_desktop_config.json"
    else:
        config_home = os.environ.get("XDG_CONFIG_HOME", "")
        base = Path(config_home) if config_home else Path.home() / ".config"
        return base / "Claude" / "claude_desktop_config.json"


def check_claude_desktop_mcp() -> DiagnosticItem:
    cfg_file = get_claude_desktop_config_path()
    platform_label = "macOS" if sys.platform == "darwin" else ("Windows" if sys.platform == "win32" else "Linux")
    name = f"Claude Desktop ({platform_label})"
    if not cfg_file.exists():
        return DiagnosticItem(
            name=name,
            status="missing",
            message=f"Config file not found in {cfg_file.parent}",
            remedy="Run `tokencut install --claude-desktop` to configure Claude Desktop",
        )
    try:
        data = json.loads(cfg_file.read_text(encoding="utf-8"))
        if "tokencut" in data.get("mcpServers", {}):
            return DiagnosticItem(
                name=name,
                status="ok",
                message=f"tokencut registered in {cfg_file.name}",
            )
        return DiagnosticItem(
            name=name,
            status="missing",
            message="tokencut not in mcpServers",
            remedy="Run `tokencut install --claude-desktop` to register tokencut",
        )
    except Exception as e:
        return DiagnosticItem(
            name=name,
            status="warning",
            message=f"Error reading config: {e}",
        )


def check_chatgpt_desktop() -> DiagnosticItem:
    app_path = Path("/Applications/ChatGPT.app")
    if app_path.exists():
        return DiagnosticItem(
            name="ChatGPT Desktop (macOS)",
            status="ok",
            message="Found at /Applications/ChatGPT.app (Compatible via MCP tools & CLI)",
        )
    return DiagnosticItem(
        name="ChatGPT Desktop",
        status="ok",
        message="Compatible with ChatGPT via MCP tools and CLI pipes",
    )


def configure_claude_desktop_mcp(target_file: Path | None = None) -> tuple[bool, str]:
    cfg_file = target_file or get_claude_desktop_config_path()
    cfg_file.parent.mkdir(parents=True, exist_ok=True)
    data: dict = {"mcpServers": {}}
    if cfg_file.exists():
        try:
            data = json.loads(cfg_file.read_text(encoding="utf-8"))
            if "mcpServers" not in data:
                data["mcpServers"] = {}
        except Exception:
            data = {"mcpServers": {}}

    data["mcpServers"]["tokencut"] = {
        "command": "uvx",
        "args": ["tokencut", "mcp"],
    }
    cfg_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return True, str(cfg_file)


def run_all_diagnostics() -> list[DiagnosticItem]:
    return [
        check_python(),
        check_cache_db(),
        check_claude_cli(),
        check_claude_desktop_mcp(),
        check_chatgpt_desktop(),
        check_cursor_mcp(),
        check_shell_alias(),
    ]


def configure_cursor_mcp() -> tuple[bool, str]:
    cursor_dir = Path.home() / ".cursor"
    cursor_dir.mkdir(parents=True, exist_ok=True)
    mcp_file = cursor_dir / "mcp.json"

    data: dict = {"mcpServers": {}}
    if mcp_file.exists():
        try:
            data = json.loads(mcp_file.read_text(encoding="utf-8"))
            if "mcpServers" not in data:
                data["mcpServers"] = {}
        except Exception:
            data = {"mcpServers": {}}

    data["mcpServers"]["tokencut"] = {
        "command": "uvx",
        "args": ["tokencut", "mcp"],
    }

    mcp_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return True, str(mcp_file)


def configure_shell_alias() -> tuple[bool, str]:
    shell = os.environ.get("SHELL", "")
    rc_name = ".zshrc" if "zsh" in shell else ".bashrc"
    rc_path = Path.home() / rc_name

    alias_line = '\nalias cc="tokencut run --"\n'
    if rc_path.exists():
        content = rc_path.read_text(encoding="utf-8", errors="ignore")
        if "alias cc=" in content:
            return False, f"Alias already present in {rc_path}"
        with open(rc_path, "a", encoding="utf-8") as f:
            f.write(alias_line)
    else:
        rc_path.write_text(alias_line, encoding="utf-8")

    return True, str(rc_path)
