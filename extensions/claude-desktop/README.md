# UsageTrim — Claude Desktop extension

1. Install the CLI: `uv tool install usagetrim`
2. Either:
   - `usagetrim install --claude-desktop` (writes `claude_desktop_config.json`), or
   - `usagetrim install --mcpb` (writes this manifest under `~/.usagetrim/extensions/claude-desktop` for packaging with `mcpb pack`)
3. Restart Claude Desktop and enable the UsageTrim connector/tools.

UsageTrim does not intercept Desktop chat messages. It saves tokens via MCP tools and optional Prepare-for-chat.
