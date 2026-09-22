# TokenCut — Claude Desktop extension

1. Install the CLI: `uv tool install 'git+https://github.com/00200200/tokencut.git'`
2. Either:
   - `tokencut install --claude-desktop` (writes `claude_desktop_config.json`), or
   - `tokencut install --mcpb` (writes this manifest under `~/.tokencut/extensions/claude-desktop` for packaging with `mcpb pack`)
3. Restart Claude Desktop and enable the TokenCut connector/tools.

TokenCut does not intercept Desktop chat messages. It saves tokens via MCP tools and optional Prepare-for-chat.
