# UsageTrim Launch & Community Sharing Kit 🚀

This document contains ready-to-publish posts, threads, and submission templates designed to showcase **UsageTrim** to developer communities, drive adoption, and earn stars on GitHub.

---

## 1. Hacker News — Show HN

**Title:**
```text
Show HN: UsageTrim – Cut LLM coding context bloat by 40–98% with local MCP and CLI
```

**Link:**
```text
https://github.com/00200200/usagetrim
```

**Post Text / First Comment:**
```markdown
Hey HN,

We built UsageTrim because we kept hitting rate-limit walls and paying for thousands of useless tokens in Claude Code, Cursor, and Codex.

When coding agents run commands like `git diff`, `git log`, `cargo test`, `npm test`, or dump entire files just to read a 10-line function, 70–90% of the context window is burned on boilerplate:
- A `cargo test` in a medium crate prints 400 lines of `test ... ok` (5,300+ tokens) when only the summary or actual panics matter.
- A lockfile diff in `uv.lock` or `package-lock.json` adds 15,000 tokens of dependency hash changes that derail LLM reasoning.
- Reading a 500-line class to see one method signature costs tokens and pollutes the prompt cache.

Existing tools often truncate output blindly (dropping stack traces or diff bodies) or rely on extra LLM summarization calls (which add latency, cost, and hallucination risk).

UsageTrim is a 100% local CLI and standard Model Context Protocol (MCP) server that operates on two strict principles:

1. **Zero Breaking Quality Loss (Strict Safety Guarantee):**
   We never discard diagnostic output. On test suites (`pytest`, `cargo test`, `go test`, `vitest`/`jest`), passing runs collapse into concise records, but the moment an assertion fails, a panic occurs, or a backtrace starts, the rest of the output is reproduced 100% verbatim. On `git log -p`, diffs are compacted via unified context trimming—never omitted.

2. **Compress-Cache-Retrieve (CCR):**
   Every compacted text payload stores its full, unredacted raw original in a local SQLite database (`~/.usagetrim/cache.db`). If an agent ever needs the full unabridged context, it receives a reference ID (e.g. `tc_7f8a12...`) and can retrieve it instantly via `usagetrim retrieve <id>` or the MCP tool `usagetrim_retrieve`.

Key features:
- **Universal MCP Server:** Integrates with Claude Code (`claude mcp add`), Cursor, Windsurf, Codex, and Gemini CLI. Offers a compact `coding` profile (37% smaller tool schemas) to minimize baseline turn overhead.
- **Autonomous Context Optimizer:** `usagetrim optimize` / MCP `usagetrim_optimize` automatically inspects any prompt, detects embedded code blocks (` ```json ` -> TOON table, ` ```diff ` -> slim diff, stack traces -> folded), and aligns prompt cache prefixes for Anthropic / OpenAI / Gemini prompt caching.
- **Multi-Language AST Skeletonization:** Native tree-sitter AST traversal (`ast-grep`) for TypeScript, JavaScript, Go, Rust, Java, and C/C++ to generate outline skeletons (`usagetrim cat --skeleton` / `usagetrim pack`).
- **macOS Desktop Companion:** Lightweight native Swift app (menu bar + HUD) with a "Prepare for chat" clipboard optimizer and live usage allowance monitors.

It's open source (MIT), written in Python (managed via `uv`), and makes zero external API calls.

GitHub: https://github.com/00200200/usagetrim

We'd love to hear your feedback, edge cases you encounter with agent tool outputs, and any test runners/commands you'd like specialized filters for!
```

---

## 2. Reddit

### A. `r/LocalLLaMA`
**Title:**
```text
UsageTrim: Open-source local MCP & CLI context optimizer for Claude Code, Codex & local agents (40-98% token reduction, zero data loss)
```
**Post Body:**
```markdown
Hi r/LocalLLaMA!

If you use Claude Code, Cursor, Codex, or local agents (Aider, OpenCode), you know how fast context windows fill up with redundant garbage:
- `npm test` or `cargo test` printing 500 lines of passing checkmarks
- Huge `package-lock.json` or `uv.lock` diffs in git commits
- Dumping 1,000-line files just to inspect a class structure

We built **UsageTrim** (MIT): https://github.com/00200200/usagetrim

### How it works without breaking agent reasoning:
1. **Verbatim Diagnostics**: We never summarize or lose error traces. When `cargo test`, `pytest`, `go test`, or `vitest` pass, progress lines collapse into a 1-line summary. But the instant an assertion error, panic, or traceback appears, everything from that line onward is emitted verbatim.
2. **Compress-Cache-Retrieve (CCR)**: Everything compacted is stored in a local SQLite store. If an agent needs the original unabridged log, it calls `usagetrim_retrieve(ref_id)` and recovers it immediately.
3. **AST Code Skeletons**: Uses `ast-grep` tree-sitter bindings to extract clean skeletons (functions with collapsed bodies `{ ... }`, preserving types, structs, interfaces) for TS, JS, Go, Rust, Java, and C/C++.
4. **Autonomous Optimizer**: `usagetrim optimize` detects JSON arrays and re-encodes them to TOON / markdown tables, slims unified diffs, and aligns prompt cache boundaries.
5. **No AI Calls**: 100% deterministic, runs locally, zero cloud telemetry.

Works over stdio MCP (`claude mcp add --scope user usagetrim -- usagetrim mcp --profile coding`) or CLI (`usagetrim run -- ...`).

Check it out on GitHub: https://github.com/00200200/usagetrim
```

### B. `r/ClaudeAI` & `r/Cursor`
**Title:**
```text
How to stop hitting the 5-hour Claude Code rate limit: UsageTrim (free, open source MCP context trimmer)
```
**Post Body:**
```markdown
Claude 3.7 / 3.5 Sonnet is amazing for coding, but Claude Code burns tokens crazy fast—mostly due to verbose CLI outputs (`git log`, `git diff`, test runners) and repeated whole-file reads.

We built a local MCP tool and CLI companion called **UsageTrim**:
👉 https://github.com/00200200/usagetrim

### What it does:
- **Slims test outputs**: `pytest -v`, `cargo test`, `vitest`, `go test` get reduced by 85–98% while keeping 100% of failure stack traces and errors.
- **Diff slimming**: Folds lockfiles (`package-lock.json`, `uv.lock`, `Cargo.lock`) and trims diff context lines to save ~95% on git diffs.
- **Lightweight Coding MCP Profile**: Downsizes the MCP schema footprint by 36–38% (3,414 → 2,183 / 2,102 tokens, local o200k_base) so every agent turn starts leaner.
- **Mac Companion App**: A native macOS app with a "Prepare for chat" clipboard tool to optimize messy logs before pasting them into chat.

Install with uv:
```bash
uv tool install usagetrim
claude mcp add --scope user usagetrim -- usagetrim mcp --profile coding
```

Zero telemetry, open source MIT. If you find it useful, leave a ⭐ on GitHub!
```

---

## 3. X / Twitter Launch Thread

**Tweet 1 (Hook):**
```text
Coding agents like Claude Code, Cursor, and Codex waste 40–90% of their context on noise:
- 400 lines of "test ... ok"
- 10,000-line lockfile diffs
- full file dumps for 1 method

Introducing UsageTrim ⚡: a local MCP server & CLI that keeps the signal and cuts the bloat. 🧵👇

🔗 https://github.com/00200200/usagetrim
```

**Tweet 2 (Safety Guarantee):**
```text
2/ Most context compressors break agent reasoning by truncating errors or guessing with another LLM.

UsageTrim is deterministic:
When tests pass, output collapses into dense progress records.
The instant an error, panic, or traceback appears? Emitted 100% verbatim.
```

**Tweet 3 (CCR - Compress-Cache-Retrieve):**
```text
3/ What if the model actually needs the full raw output?

UsageTrim uses Compress-Cache-Retrieve (CCR).
Every compacted log is cached in local SQLite. The model gets a reference hash (`[ref: tc_7f8a...]`) and can retrieve the byte-for-byte original anytime via MCP.
```

**Tweet 4 (AST Skeletons & Prompts):**
```text
4/ Need repo context without dumping 5,000 lines?
`usagetrim pack --skeleton` uses tree-sitter AST parsing for TS, Go, Rust, Java, and C/C++ to collapse function bodies while keeping full type definitions intact.

Plus `usagetrim optimize` for autonomous prompt caching alignment.
```

**Tweet 5 (macOS Pet & HUD):**
```text
5/ On macOS, UsageTrim includes a native companion HUD.
Use "Prepare for chat" to clean up terminal logs before pasting them into web chat, and monitor your Claude / Codex usage windows in real-time.
```

**Tweet 6 (Call to action):**
```text
6/ UsageTrim is 100% open source (MIT), written in Python with @astral_sh uv, and makes zero AI calls.

Install in 10 seconds:
`uv tool install usagetrim`

Star the repo on GitHub:
⭐ https://github.com/00200200/usagetrim
```

---

## 4. Awesome-MCP-Servers PR Entry

Submit a PR to `punkpeye/awesome-mcp-servers` and `modelcontextprotocol/servers`:

```markdown
- [UsageTrim](https://github.com/00200200/usagetrim) - Local context optimization engine and MCP companion for Claude Code, Cursor, and Codex. Compresses test logs, diffs, JSON, and AST code outlines by 40-98% with recoverable SQLite caching and zero data loss.
```

---

## 5. Product Hunt Submission

- **Product Name:** UsageTrim
- **Tagline:** Cut LLM coding context bloat by 40–98% with local MCP & CLI
- **Topics:** Developer Tools, Artificial Intelligence, Open Source, Productivity, Command Line
- **Description:** UsageTrim is an open-source local CLI and MCP server for Claude Code, Cursor, and Codex. It safely compacts test logs, diffs, and AST code outlines with a strict zero-loss guarantee: passing noise collapses, while all failures, stack traces, and diagnostics are preserved verbatim. Includes Compress-Cache-Retrieve SQLite recovery and a native macOS companion.
