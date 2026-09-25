# Launch posts

Paste-ready drafts. Every number links back to "Measured on real sessions" in the README
and can be reproduced with `scripts/replay_mcp_transcripts.py`. Do not round them up.

## Show HN

**Title** (80 chars max):

> Show HN: UsageTrim – lossless compaction of MCP tool output for Claude Code

**Text:**

> I replayed 14 days of my Claude Code transcripts to see where tool-output tokens go. Third-party MCP servers were about 30% of it: Supabase `execute_sql` alone returned 5M tokens of JSON rows that repeat every key on every row, wrapped in a `{"result": "..."}` string that escapes every quote.
>
> UsageTrim is a local CLI + MCP server. Its new PostToolUse hook rewrites *other* MCP servers' results without losing anything: uniform rows become TSV with the keys once (a cell that parses as JSON is JSON, so `51`, `"51"` and `null` stay distinct), wrappers are unescaped, and indentation goes. Prompt-injection boundaries such as Supabase's `<untrusted-data-…>` tags stay verbatim.
>
> On those transcripts: 11,058 MCP results, 7.17M → 5.85M tokens (−18.3%). Search Console analytics −38%, Supabase −19%. All 3,144 SQL results rewritten as tables decoded back to the original rows. Counts are local tokenizer estimates, not billing.
>
> What did not help: my Bash output was mostly ad-hoc scripts, where the Bash filters saved under 1%. They pay off on test and build logs. I'd rather publish that than a "90%" headline.
>
> It also ships Haiku subagents for searching and running tests, so the main model gets conclusions instead of files. There is also an opt-in override that moves Claude Code's built-in Explore (which now inherits the main model) back to Haiku.
>
> Install inside Claude Code: `/plugin marketplace add 00200200/usagetrim`. It also works as a Codex plugin and as a Claude Desktop extension. MIT, no model calls, nothing leaves the machine.
>
> You can run the replay script on your own transcripts, and I'd like to hear what numbers you get.

## r/ClaudeAI and r/ClaudeCode

**Title:**

> I measured where my Claude Code tokens go: ~30% was other MCP servers' JSON. Built a lossless fix (−18% on 11k real results)

**Body:** reuse the Show HN text. Add a screenshot of the README results table and the one-line plugin install.

## r/mcp

**Title:**

> PostToolUse hook that losslessly compacts MCP results (JSON rows → TSV, unescaped wrappers), keeps untrusted-data boundaries

**Body:** lead with the format rules and the round-trip check. Ask server authors which output shapes they want covered next.

## X / Bluesky thread

1. Replayed 14 days of my Claude Code sessions: ~30% of tool-output tokens came from other MCP servers' JSON. UsageTrim now compacts those losslessly. 11,058 results: −18.3%. 🧵
2. Supabase returns rows as `[{"id":1,"name":…},…]` inside an escaped `{"result": "…"}` string. As TSV with the keys once, every value and type survives, and the `<untrusted-data>` safety tags stay put.
3. Honest part: my Bash output saved <1%, because it was mostly ad-hoc scripts. Filters shine on test and build logs. Measure your own: `scripts/replay_mcp_transcripts.py`.
4. Also: Haiku subagents for search and test runs, and an opt-in to move Claude Code's Explore back to Haiku.
5. `/plugin marketplace add 00200200/usagetrim` · Codex plugin · Claude Desktop .mcpb · MIT · github.com/00200200/usagetrim

## Where else

- Lists: awesome-claude-code, awesome-mcp-servers (one focused PR each, no bulk submissions).
- Registries: the official MCP registry (`mcp-publisher publish`), Glama and mcp.so pick up GitHub repos.
- Reply where people ask about Claude Code limits or MCP output size, with the measured table and no hype.
