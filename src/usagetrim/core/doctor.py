from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Literal

from usagetrim.core.cache import DEFAULT_CACHE_DB


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
    cache_dir = os.environ.get("USAGETRIM_CACHE_DIR")
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
            remedy="Run `usagetrim cache clear` to reset the database",
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
            remedy="Run `usagetrim install --cursor` to configure Cursor MCP",
        )

    try:
        data = json.loads(cursor_mcp_path.read_text(encoding="utf-8"))
        servers = data.get("mcpServers", {})
        if "usagetrim" in servers:
            return DiagnosticItem(
                name="Cursor MCP Config",
                status="ok",
                message="usagetrim registered in ~/.cursor/mcp.json",
            )
        return DiagnosticItem(
            name="Cursor MCP Config",
            status="missing",
            message="usagetrim not configured in ~/.cursor/mcp.json",
            remedy="Run `usagetrim install --cursor` to add usagetrim to Cursor",
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
            remedy="Run `usagetrim install --windsurf` to configure Windsurf MCP",
        )

    try:
        data = json.loads(cfg_file.read_text(encoding="utf-8"))
        servers = data.get("mcpServers", {})
        if not isinstance(servers, dict):
            raise ValueError("mcpServers must be an object")
        if "usagetrim" in servers:
            entry = servers["usagetrim"]
            if not isinstance(entry, dict):
                raise ValueError("usagetrim entry must be an object")
            if entry.get("enabled") is False or entry.get("disabled") is True:
                return DiagnosticItem(
                    name="Windsurf MCP Config",
                    status="warning",
                    message="usagetrim is configured but disabled",
                    remedy="Enable usagetrim in Windsurf MCP settings",
                )
            if not any(
                isinstance(entry.get(key), str) and entry[key].strip() for key in ("command", "url")
            ):
                raise ValueError("usagetrim entry requires a command or URL")
            args = entry.get("args", [])
            if not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
                raise ValueError("usagetrim args must be a list of strings")
            return DiagnosticItem(
                name="Windsurf MCP Config",
                status="ok",
                message=f"usagetrim configured in {cfg_file.name}; connection not tested",
            )
        return DiagnosticItem(
            name="Windsurf MCP Config",
            status="missing",
            message="usagetrim not in mcpServers",
            remedy="Run `usagetrim install --windsurf` to register usagetrim",
        )
    except Exception as e:
        return DiagnosticItem(
            name="Windsurf MCP Config",
            status="warning",
            message=f"Invalid JSON in {cfg_file}: {e}",
            remedy="Run `usagetrim install --windsurf` to repair config",
        )


def _cc_alias(content: str) -> str | None:
    """Read literal alias declarations without evaluating shell configuration."""
    result = None
    for line in content.splitlines():
        try:
            words = shlex.split(line, comments=True)
        except ValueError:
            continue
        if not words or words[0] != "alias":
            continue
        for index, word in enumerate(words[1:], 1):
            if word.startswith("cc="):
                result = word.partition("=")[2]
            elif word == "cc" and index + 1 < len(words):
                result = words[index + 1]
    return result


def check_shell_alias() -> DiagnosticItem:
    shell = os.environ.get("SHELL", "")
    if "fish" in shell:
        rc_path = Path.home() / ".config" / "fish" / "config.fish"
        rel_path = "~/.config/fish/config.fish"
    elif "zsh" in shell:
        rc_path = Path.home() / ".zshrc"
        rel_path = "~/.zshrc"
    else:
        rc_path = Path.home() / ".bashrc"
        rel_path = "~/.bashrc"

    if rc_path.exists():
        content = rc_path.read_text(encoding="utf-8", errors="ignore")
        alias = _cc_alias(content)
        try:
            command = shlex.split(alias) if alias else []
        except ValueError:
            command = []
        if command and Path(command[0]).name == "usagetrim":
            return DiagnosticItem(
                name="Shell Alias (`cc`)",
                status="ok",
                message=f"Alias configured in {rel_path}",
            )
        if alias is not None:
            return DiagnosticItem(
                name="Shell Alias (`cc`)",
                status="warning",
                message=f"The existing cc alias in {rel_path} is not a UsageTrim shortcut",
                remedy="Keep your existing alias or choose a different shortcut for UsageTrim",
            )
    return DiagnosticItem(
        name="Shell Alias (`cc`)",
        status="missing",
        message=f"No `cc` alias found in {rel_path}",
        remedy=f"Run `usagetrim install --alias` to add shortcut to {rel_path}",
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
            remedy="Run `usagetrim install --claude-desktop` to configure Claude Desktop",
        )
    try:
        data = json.loads(cfg_file.read_text(encoding="utf-8"))
        if "usagetrim" in data.get("mcpServers", {}):
            return DiagnosticItem(
                name=name,
                status="ok",
                message=f"usagetrim registered in {cfg_file.name}",
            )
        return DiagnosticItem(
            name=name,
            status="missing",
            message="usagetrim not in mcpServers",
            remedy="Run `usagetrim install --claude-desktop` to register usagetrim",
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
        remedy="Use the separate Codex app or CLI for UsageTrim's local MCP server.",
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
        server = servers.get("usagetrim")
        if server is None:
            return DiagnosticItem(
                name="Codex MCP Config",
                status="missing",
                message=f"{prefix}; UsageTrim is not registered in {cfg}.",
                remedy="Run `usagetrim install --codex` to configure Codex Desktop MCP",
            )
        if not isinstance(server, dict) or not isinstance(server.get("command"), str):
            raise ValueError("usagetrim must be a local server table with a command")
        if server.get("enabled") is False:
            return DiagnosticItem(
                name="Codex MCP Config",
                status="warning",
                message=f"{prefix}; UsageTrim is registered but disabled in {cfg}.",
            )
        if PurePath(server["command"]).name == "uvx" and server.get("args", [])[:1] == [
            "usagetrim"
        ]:
            raise ValueError(
                "uvx usagetrim needs a PyPI release, which does not exist yet; use "
                "`uvx --from git+https://github.com/00200200/usagetrim usagetrim` "
                "or your local installation"
            )
        return DiagnosticItem(
            name="Codex MCP Config",
            status="ok" if installed else "warning",
            message=f"{prefix}; UsageTrim is registered in {cfg}. Runtime connectivity is untested.",
        )
    except (OSError, ValueError, TypeError) as exc:
        return DiagnosticItem(
            name="Codex MCP Config",
            status="warning",
            message=f"{prefix}; cannot validate {cfg}: {exc}",
        )


def get_codex_config_path() -> Path:
    return Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "config.toml"


def _local_mcp_command(profile: str | None = None) -> dict[str, object]:
    """Choose an installed runtime, never fetch the colliding PyPI project."""
    base_args = ["mcp", "--profile", profile] if profile else ["mcp"]
    executable = shutil.which("usagetrim")
    if executable:
        return {"command": str(Path(executable).absolute()), "args": base_args}
    # Preserve the venv path: resolving a symlink to the base interpreter can
    # lose the installed package. -I proves this works without cwd/PYTHONPATH.
    interpreter = Path(sys.executable).absolute()
    try:
        probe = subprocess.run(
            [
                str(interpreter),
                "-I",
                "-c",
                "from usagetrim.cli import main; from usagetrim.core.cache import ContextCache",
            ],
            capture_output=True,
            timeout=5,
            check=False,
        )
        if probe.returncode == 0:
            return {"command": str(interpreter), "args": ["-m", "usagetrim.cli", *base_args]}
    except (OSError, subprocess.TimeoutExpired):
        pass
    raise ValueError(
        "No usable local UsageTrim installation found. Install this repository into a persistent "
        "environment and add its usagetrim executable to PATH; do not install the unrelated PyPI package."
    )


def _configure_local_mcp(cfg_file: Path, profile: str | None = None) -> tuple[bool, str]:
    """Preserve settings, reject malformed files, and back up each actual change."""
    staged: Path | None = None
    try:
        # Read and validate before creating directories, backups, or replacements.
        data = json.loads(cfg_file.read_text(encoding="utf-8")) if cfg_file.exists() else {}
        if not isinstance(data, dict) or not isinstance(data.get("mcpServers", {}), dict):
            raise ValueError("configuration and mcpServers must be JSON objects")
        servers = data.setdefault("mcpServers", {})
        previous = servers.get("usagetrim", {})
        if not isinstance(previous, dict):
            raise ValueError("existing usagetrim server must be a JSON object")
        if "url" in previous or previous.get("type", "stdio") != "stdio":
            raise ValueError(
                "existing usagetrim server uses another transport; update it explicitly"
            )
        cmd_info = (
            _local_mcp_command(profile=profile) if profile is not None else _local_mcp_command()
        )
        updated = {**previous, **cmd_info}
        if previous == updated:
            return True, str(cfg_file)
        servers["usagetrim"] = updated
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
                prefix=cfg_file.name + ".pre-usagetrim-",
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


def configure_claude_desktop_mcp(
    target_file: Path | None = None, profile: str | None = None
) -> tuple[bool, str]:
    return _configure_local_mcp(target_file or get_claude_desktop_config_path(), profile=profile)


def configure_codex_mcp(
    target_file: Path | None = None, profile: str | None = None
) -> tuple[bool, str]:
    """Configure UsageTrim MCP in Codex config.toml safely and atomically."""
    cfg_file = target_file or get_codex_config_path()
    staged: Path | None = None
    try:
        raw_text = cfg_file.read_text(encoding="utf-8") if cfg_file.exists() else ""
        data = tomllib.loads(raw_text) if raw_text else {}
        if not isinstance(data, dict):
            raise ValueError("configuration must be a TOML table")
        servers = data.get("mcp_servers", {})
        if not isinstance(servers, dict):
            raise ValueError("mcp_servers must be a table")

        cmd_info = (
            _local_mcp_command(profile=profile) if profile is not None else _local_mcp_command()
        )
        cmd_str = json.dumps(cmd_info["command"])
        args_list = json.dumps(cmd_info["args"])

        previous = servers.get("usagetrim")
        if (
            isinstance(previous, dict)
            and previous.get("command") == cmd_info["command"]
            and previous.get("args") == cmd_info["args"]
        ):
            return True, str(cfg_file)

        table_lines = [
            "[mcp_servers.usagetrim]",
            f"command = {cmd_str}",
            f"args = {args_list}",
        ]
        # Preserve env table if previous server had one
        if isinstance(previous, dict) and isinstance(previous.get("env"), dict) and previous["env"]:
            table_lines.append("")
            table_lines.append("[mcp_servers.usagetrim.env]")
            for k, v in previous["env"].items():
                table_lines.append(f"{k} = {json.dumps(str(v))}")

        usagetrim_block = "\n".join(table_lines) + "\n"

        block_pattern = re.compile(
            r"(^|\n)\[mcp_servers\.usagetrim\]\n(?:(?!\n\[(?!mcp_servers\.usagetrim\b)).)*",
            re.DOTALL,
        )
        if block_pattern.search(raw_text):
            updated_text = block_pattern.sub(r"\1" + usagetrim_block, raw_text)
        else:
            sep = "" if not raw_text else ("\n" if raw_text.endswith("\n") else "\n\n")
            updated_text = raw_text + sep + usagetrim_block

        # Strictly validate that updated_text parses as valid TOML and usagetrim matches
        parsed = tomllib.loads(updated_text)
        if parsed.get("mcp_servers", {}).get("usagetrim", {}).get("command") != cmd_info["command"]:
            raise ValueError("failed to verify updated [mcp_servers.usagetrim] table")

        cfg_file.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix=cfg_file.name + ".tmp-",
            dir=cfg_file.parent,
            delete=False,
        ) as temporary:
            staged = Path(temporary.name)
            temporary.write(updated_text)
            temporary.flush()
            os.fsync(temporary.fileno())

        if cfg_file.exists():
            os.chmod(staged, cfg_file.stat().st_mode & 0o777)
            with tempfile.NamedTemporaryFile(
                prefix=cfg_file.name + ".pre-usagetrim-",
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


EXTENSION_FILES = (
    "manifest.json",
    "pyproject.toml",
    "src/server.py",
    "icon.png",
    "README.md",
    ".mcpbignore",
)


def _resource(wheel_rel: str, repo_rel: str) -> Path | None:
    here = Path(__file__).resolve()
    # Wheel installs carry resources inside the package; a checkout keeps them at the root.
    for candidate in (here.parents[1] / wheel_rel, here.parents[3] / repo_rel):
        if candidate.exists():
            return candidate
    return None


def _extension_source() -> Path | None:
    source = _resource("extensions/claude-desktop", "extensions/claude-desktop")
    return source if source and (source / "manifest.json").is_file() else None


def install_cheap_explore(agents_dir: Path | None = None) -> tuple[bool, str]:
    """Run Claude Code's Explore subagent on Haiku via a user-scope override.

    Since Claude Code v2.1.198 the built-in Explore inherits the main model, so
    exploration on Opus costs Opus usage. A user agent named ``Explore`` takes
    precedence over the built-in; an existing file is never overwritten.
    """
    source = _resource("agents/scout.md", "plugins/usagetrim/agents/scout.md")
    if source is None:
        return False, "The scout agent definition is missing from this install."
    text = source.read_text(encoding="utf-8").replace("name: scout\n", "name: Explore\n", 1)
    dest = (agents_dir or Path.home() / ".claude" / "agents") / "Explore.md"
    try:
        if dest.exists():
            if dest.read_text(encoding="utf-8") == text:
                return True, str(dest)
            return False, f"{dest} already exists; leaving your Explore agent unchanged."
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
        return True, str(dest)
    except OSError as exc:
        return False, f"Could not write {dest}: {exc}"


def write_claude_desktop_extension(target_dir: Path | None = None) -> tuple[bool, str]:
    """Copy the Claude Desktop Extension (MCPB) bundle source for ``mcpb pack``.

    Releases attach a ready ``usagetrim-<version>.mcpb``; this keeps a local path
    for users who want to inspect or rebuild it. The bundle uses the ``uv``
    server type, so Claude Desktop installs the pinned package itself.
    """
    source = _extension_source()
    if source is None:
        return False, (
            "Extension bundle not found in this install. Download usagetrim.mcpb from "
            "https://github.com/00200200/usagetrim/releases instead."
        )
    dest = target_dir or (Path.home() / ".usagetrim" / "extensions" / "claude-desktop")
    try:
        for name in EXTENSION_FILES:
            if (source / name).is_file():
                (dest / name).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source / name, dest / name)
        return True, str(dest)
    except OSError as exc:
        return False, f"Could not write Claude Desktop extension: {exc}"


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


def configure_cursor_mcp(
    target_file: Path | None = None, profile: str = "coding"
) -> tuple[bool, str]:
    return _configure_local_mcp(
        target_file or (Path.home() / ".cursor" / "mcp.json"), profile=profile
    )


def configure_windsurf_mcp(
    target_file: Path | None = None, profile: str = "coding"
) -> tuple[bool, str]:
    return _configure_local_mcp(target_file or get_windsurf_mcp_config_path(), profile=profile)


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
    alias_line = "\nalias cc 'usagetrim run --'\n" if is_fish else '\nalias cc="usagetrim run --"\n'

    if rc_path.exists():
        content = rc_path.read_text(encoding="utf-8", errors="ignore")
        if _cc_alias(content) is not None:
            return False, f"Alias already present in {rc_path}"
        with open(rc_path, "a", encoding="utf-8") as f:
            f.write(alias_line)
    else:
        rc_path.write_text(alias_line, encoding="utf-8")

    return True, str(rc_path)
