# UsageTrim — Claude Desktop extension

This directory is the source of `usagetrim-<version>.mcpb`, attached to every
[release](https://github.com/00200200/usagetrim/releases).

1. Download `usagetrim-<version>.mcpb`.
2. Double-click it, or open Claude Desktop → Settings → Extensions → Install extension.
3. Claude Desktop installs the pinned `usagetrim` package with its bundled uv; no separate
   Python or CLI install is needed.

Rebuild locally with `npx @anthropic-ai/mcpb pack extensions/claude-desktop`.

UsageTrim does not intercept Desktop chat messages. It reduces tool output through MCP
tools and the optional Prepare-for-chat clipboard helper. Counts are local estimates.
