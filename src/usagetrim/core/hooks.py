from __future__ import annotations

from pathlib import Path


def generate_zsh_alias() -> str:
    return """
# usagetrim — Automatic token optimization for AI coding
alias cc-run="usagetrim run"
alias tcut="usagetrim"
"""


def install_zsh_hook() -> Path:
    """Append usagetrim helper alias to user's zshrc."""
    zshrc = Path.home() / ".zshrc"
    snippet = generate_zsh_alias()
    if zshrc.exists():
        content = zshrc.read_text(encoding="utf-8")
        if "usagetrim" not in content:
            zshrc.write_text(content + "\n" + snippet, encoding="utf-8")
    else:
        zshrc.write_text(snippet, encoding="utf-8")
    return zshrc


def setup_claude_code_mcp_config() -> str:
    """Generate the exact command to add usagetrim to Claude Code native MCP configuration."""
    return "claude mcp add --scope user usagetrim -- usagetrim mcp"
