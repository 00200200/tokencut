from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Literal

from tokencut.core.cache import DEFAULT_CACHE_DB


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
    cache_dir = os.environ.get("TOKENCUT_CACHE_DIR")
    db_path = Path(cache_dir) / "cache.db" if cache_dir else DEFAULT_CACHE_DB
    if not db_path.exists():
        return DiagnosticItem(
            name="CCR Cache Store",
            status="ok",
            message=f"{db_path} (Ready, initialised on first run)",
        )

    try:
        size_kb = db_path.stat().st_size / 1024
        with sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True) as conn:
            count = conn.execute("SELECT COUNT(*) FROM output_cache").fetchone()[0]
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
            remedy="Fix syntax in ~/.cursor/mcp.json before retrying installation",
        )


def get_windsurf_mcp_config_path() -> Path:
    return Path.home() / ".codeium" / "windsurf" / "mcp_config.json"


def check_windsurf_mcp() -> DiagnosticItem:
    cfg_file = get_windsurf_mcp_config_path()
    if not cfg_file.exists():
        return DiagnosticItem(
            name="Windsurf MCP Config",
            status="missing",
            message=f"No {cfg_file.name} found in ~/.codeium/windsurf",
            remedy="Run `tokencut install --windsurf` to configure Windsurf MCP",
        )

    try:
        data = json.loads(cfg_file.read_text(encoding="utf-8"))
        servers = data.get("mcpServers", {})
        if "tokencut" in servers:
            return DiagnosticItem(
                name="Windsurf MCP Config",
                status="ok",
                message=f"tokencut registered in {cfg_file.name}",
            )
        return DiagnosticItem(
            name="Windsurf MCP Config",
            status="missing",
            message="tokencut not in mcpServers",
            remedy="Run `tokencut install --windsurf` to register tokencut",
        )
    except Exception as e:
        return DiagnosticItem(
            name="Windsurf MCP Config",
            status="warning",
            message=f"Invalid JSON in {cfg_file}: {e}",
            remedy="Run `tokencut install --windsurf` to repair config",
        )


def check_shell_alias() -> DiagnosticItem:
    shell = os.environ.get("SHELL", "")
    if "fish" in shell:
        rc_path = Path.home() / ".config" / "fish" / "config.fish"
        rel_path = "~/.config/fish/config.fish"
        alias_needle = "alias cc"
    elif "zsh" in shell:
        rc_path = Path.home() / ".zshrc"
        rel_path = "~/.zshrc"
        alias_needle = "alias cc="
    else:
        rc_path = Path.home() / ".bashrc"
        rel_path = "~/.bashrc"
        alias_needle = "alias cc="

    if rc_path.exists():
        content = rc_path.read_text(encoding="utf-8", errors="ignore")
        if (
            'alias cc="tokencut' in content
            or "alias cc='tokencut" in content
            or alias_needle in content
        ):
            return DiagnosticItem(
                name="Shell Alias (`cc`)",
                status="ok",
                message=f"Alias configured in {rel_path}",
            )
    return DiagnosticItem(
        name="Shell Alias (`cc`)",
        status="missing",
        message=f"No `cc` alias found in {rel_path}",
        remedy=f"Run `tokencut install --alias` to add shortcut to {rel_path}",
    )


def get_claude_desktop_config_path() -> Path:
    if sys.platform == "darwin":
        return (
            Path.home()
            / "Library"
            / "Application Support"
            / "Claude"
            / "claude_desktop_config.json"
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
    platform_label = (
        "macOS" if sys.platform == "darwin" else ("Windows" if sys.platform == "win32" else "Linux")
    )
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
    return DiagnosticItem(
        name="ChatGPT Desktop",
        status="warning",
        message="This installer does not support local stdio MCP in the regular ChatGPT app.",
        remedy="Use the separate Codex app or CLI for TokenCut's local MCP server.",
    )


def _codex_available() -> bool:
    return bool(
        shutil.which("codex")
        or Path("/Applications/Codex.app").exists()
        or (Path.home() / "Applications" / "Codex.app").exists()
    )


def check_codex_mcp(config_file: Path | None = None) -> DiagnosticItem:
    """Inspect local registration only; this does not establish MCP connectivity."""
    installed = _codex_available()
    cfg = config_file or Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "config.toml"
    prefix = "Codex detected" if installed else "Codex app/CLI not detected"
    try:
        data = tomllib.loads(cfg.read_text(encoding="utf-8")) if cfg.exists() else {}
        servers = data.get("mcp_servers", {})
        if not isinstance(servers, dict):
            raise ValueError("mcp_servers must be a table")
        server = servers.get("tokencut")
        if server is None:
            return DiagnosticItem(
                name="Codex MCP Config",
                status="missing",
                message=f"{prefix}; TokenCut is not registered in {cfg}.",
            )
        if not isinstance(server, dict) or not isinstance(server.get("command"), str):
            raise ValueError("tokencut must be a local server table with a command")
        if server.get("enabled") is False:
            return DiagnosticItem(
                name="Codex MCP Config",
                status="warning",
                message=f"{prefix}; TokenCut is registered but disabled in {cfg}.",
            )
        if PurePath(server["command"]).name == "uvx" and server.get("args", [])[:1] == ["tokencut"]:
            raise ValueError(
                "uvx tokencut resolves an unrelated PyPI package; use your local installation"
            )
        return DiagnosticItem(
            name="Codex MCP Config",
            status="ok" if installed else "warning",
            message=f"{prefix}; TokenCut is registered in {cfg}. Runtime connectivity is untested.",
        )
    except (OSError, ValueError, TypeError) as exc:
        return DiagnosticItem(
            name="Codex MCP Config",
            status="warning",
            message=f"{prefix}; cannot validate {cfg}: {exc}",
        )


def _local_mcp_command() -> dict[str, object]:
    """Choose an installed runtime, never fetch the colliding PyPI project."""
    executable = shutil.which("tokencut")
    if executable:
        return {"command": str(Path(executable).absolute()), "args": ["mcp"]}
    # Preserve the venv path: resolving a symlink to the base interpreter can
    # lose the installed package. -I proves this works without cwd/PYTHONPATH.
    interpreter = Path(sys.executable).absolute()
    try:
        probe = subprocess.run(
            [
                str(interpreter),
                "-I",
                "-c",
                "from tokencut.cli import main; from tokencut.core.cache import ContextCache",
            ],
            capture_output=True,
            timeout=5,
            check=False,
        )
        if probe.returncode == 0:
            return {"command": str(interpreter), "args": ["-m", "tokencut.cli", "mcp"]}
    except (OSError, subprocess.TimeoutExpired):
        pass
    raise ValueError(
        "No usable local TokenCut installation found. Install this repository into a persistent "
        "environment and add its tokencut executable to PATH; do not install the unrelated PyPI package."
    )


def _configure_local_mcp(cfg_file: Path) -> tuple[bool, str]:
    """Preserve settings, reject malformed files, and back up each actual change."""
    staged: Path | None = None
    try:
        # Read and validate before creating directories, backups, or replacements.
        data = json.loads(cfg_file.read_text(encoding="utf-8")) if cfg_file.exists() else {}
        if not isinstance(data, dict) or not isinstance(data.get("mcpServers", {}), dict):
            raise ValueError("configuration and mcpServers must be JSON objects")
        servers = data.setdefault("mcpServers", {})
        previous = servers.get("tokencut", {})
        if not isinstance(previous, dict):
            raise ValueError("existing tokencut server must be a JSON object")
        if "url" in previous or previous.get("type", "stdio") != "stdio":
            raise ValueError(
                "existing tokencut server uses another transport; update it explicitly"
            )
        updated = {**previous, **_local_mcp_command()}
        if previous == updated:
            return True, str(cfg_file)
        servers["tokencut"] = updated
        cfg_file.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix=cfg_file.name + ".tmp-",
            dir=cfg_file.parent,
            delete=False,
        ) as temporary:
            staged = Path(temporary.name)
            json.dump(data, temporary, indent=2, ensure_ascii=False)
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        if cfg_file.exists():
            os.chmod(staged, cfg_file.stat().st_mode & 0o777)
            with tempfile.NamedTemporaryFile(
                prefix=cfg_file.name + ".pre-tokencut-",
                dir=cfg_file.parent,
                delete=False,
            ) as backup:
                backup_path = Path(backup.name)
            shutil.copy2(cfg_file, backup_path)
        staged.replace(cfg_file)
        return True, str(cfg_file)
    except (OSError, ValueError, TypeError) as exc:
        return (
            False,
            f"Could not configure {cfg_file}: {exc}. Existing configuration was not overwritten.",
        )
    finally:
        if staged is not None:
            staged.unlink(missing_ok=True)


def configure_claude_desktop_mcp(target_file: Path | None = None) -> tuple[bool, str]:
    return _configure_local_mcp(target_file or get_claude_desktop_config_path())


def run_all_diagnostics() -> list[DiagnosticItem]:
    return [
        check_python(),
        check_cache_db(),
        check_claude_cli(),
        check_claude_desktop_mcp(),
        check_chatgpt_desktop(),
        check_codex_mcp(),
        check_cursor_mcp(),
        check_windsurf_mcp(),
        check_shell_alias(),
    ]


def configure_cursor_mcp(target_file: Path | None = None) -> tuple[bool, str]:
    return _configure_local_mcp(target_file or (Path.home() / ".cursor" / "mcp.json"))


def configure_windsurf_mcp(target_file: Path | None = None) -> tuple[bool, str]:
    return _configure_local_mcp(target_file or get_windsurf_mcp_config_path())


def configure_shell_alias(target_file: Path | None = None) -> tuple[bool, str]:
    if target_file:
        rc_path = target_file
        is_fish = "fish" in str(target_file)
    else:
        shell = os.environ.get("SHELL", "")
        if "fish" in shell:
            rc_path = Path.home() / ".config" / "fish" / "config.fish"
            is_fish = True
        elif "zsh" in shell:
            rc_path = Path.home() / ".zshrc"
            is_fish = False
        else:
            rc_path = Path.home() / ".bashrc"
            is_fish = False

    rc_path.parent.mkdir(parents=True, exist_ok=True)
    alias_line = "\nalias cc 'tokencut run --'\n" if is_fish else '\nalias cc="tokencut run --"\n'
    needle = "alias cc " if is_fish else "alias cc="

    if rc_path.exists():
        content = rc_path.read_text(encoding="utf-8", errors="ignore")
        if needle in content:
            return False, f"Alias already present in {rc_path}"
        with open(rc_path, "a", encoding="utf-8") as f:
            f.write(alias_line)
    else:
        rc_path.write_text(alias_line, encoding="utf-8")

    return True, str(rc_path)
