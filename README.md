<div align="center">
  <a href="https://github.com/00200200/tokencut">
    <img src="assets/banner.svg" alt="tokencut — bounded context tools for AI coding assistants" width="100%" />
  </a>

  <br /><br />

  <p align="center">
    <strong>⚡ Smaller tool outputs, with omitted context available on demand.</strong><br />
    <em>A local CLI and MCP server for Claude Code, Codex, Antigravity, and other MCP clients.</em>
  </p>

  <p align="center">
    <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-00f5a0?style=for-the-badge&logo=opensourceinitiative&logoColor=white" alt="MIT license"></a>
    <a href="https://github.com/00200200/tokencut"><img src="https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-00d9f5?style=for-the-badge&logo=python&logoColor=white" alt="Python versions"></a>
    <a href="https://github.com/00200200/tokencut/actions/workflows/ci.yml"><img src="https://github.com/00200200/tokencut/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
    <a href="https://github.com/astral-sh/ruff"><img src="https://img.shields.io/badge/code%20style-ruff-261230.svg?style=for-the-badge&labelColor=000000" alt="Ruff"></a>
    <a href="https://github.com/00200200/tokencut/stargazers"><img src="https://img.shields.io/github/stars/00200200/tokencut?style=for-the-badge&label=Star%20Us!&color=7928ca" alt="GitHub stars"></a>
  </p>
</div>

<br />

<div align="center">
  <img src="assets/demo.svg" alt="tokencut Live Terminal Animation" width="100%" />
  <p><em>Illustrative terminal demo. Run the fixture benchmark below for reproducible measurements.</em></p>
</div>

---

## Where it helps

Verbose tests, builds, files, and lockfile diffs can fill an agent's context with
irrelevant text. TokenCut bounds the text returned by its MCP tools and caches
omitted output locally for selective retrieval. It does **not** intercept other
tools, compress model reasoning, or change subscription limits. The agent must
choose TokenCut tools or explicitly wrap commands with the CLI.

<br />

Smaller output is not proof of better answers or longer subscription access.
Task success, follow-up reads, prompt caching, and model reasoning all matter.

<br />

---

## How it fits with other tools

| Tool | Main use | Relationship to TokenCut |
| :--- | :--- | :--- |
| [Serena](https://github.com/oraios/serena) | Semantic navigation and editing through language servers | Complementary; TokenCut does not implement reference-aware refactoring. |
| [RTK](https://github.com/rtk-ai/rtk) | Command-specific output filtering | A relevant baseline for terminal workloads. |
| [Repomix](https://github.com/yamadashy/repomix) | Packaging repository context | A relevant baseline for repository exploration. |
| **TokenCut** | Bounded MCP text, targeted reads, local retrieval | Compare on total tokens per successfully completed task. |

No head-to-head task-quality evaluation has established superiority over these tools.

Development priorities:

1. Compare raw tools, Serena, RTK, [Headroom](https://github.com/headroomlabs-ai/headroom),
   TokenCut, and complementary combinations on the same completed coding tasks.
   Record success, retries, latency, total input/output, cache hits, and reasoning
   usage where available. Report model versions and repeated runs, including losses.
2. Add command-specific parsers for test/build diagnostics and precise symbol
   lookup; regex outlines are not language-server navigation. Test ambiguous
   symbol names, long tracebacks, Unicode, malformed output, and retrieval paths.
3. Keep tool schemas small, measure discovery overhead, and add opt-in client
   hooks only with real client tests. Measure net session savings before enabling
   duplicate suppression or automatic routing by default.

---

## 📊 Reproducible fixture benchmarks

Run `python scripts/benchmark_suite.py` (or add `--json`) from the source checkout.
The suite uses authored test/build logs, a synthetic lockfile diff, this
repository's CLI source, and a long-line MCP read. It checks selected diagnostic strings and reports
local text-token estimates; it does not call a model or measure reasoning quality.

The local counter uses `o200k_base` (with a `cl100k_base` fallback). Claude and
Gemini values are uncalibrated heuristics. These are **not exact counts for Astra,
Fable, Opus, or any named model**, and not measurements of subscription limits.
MCP session stats include recovery notices, exit status, and subsequent retrieval
text; they exclude tool schemas, JSON envelopes, conversation input, and reasoning.
CLI dollar figures use fixed example prices, not your actual bill.

---

## 💎 The 6 Architectural Pillars

### 1. 🛡️ Compress-Cache-Retrieve (CCR)
MCP outputs default to a budget of 2,000 locally estimated tokens (`max_tokens`,
64–32,000). The budget includes the recovery reference and exit status. Omitted
output is stored **after recognized secrets are redacted** in SQLite
(`~/.tokencut/cache.db`; override with `TOKENCUT_CACHE_DIR`):
```text
[... 340 lines of routine output omitted by tokencut (-84.1%). Ref: tc_8f2a1b ...]
```
If the AI model or developer ever needs the exact omitted lines:
```bash
tokencut retrieve tc_8f2a1b --lines 120-160
```
Or call `tokencut_retrieve` with `ref_id` and `lines`. Redacted values cannot be
recovered. Long diagnostics may be omitted from a bounded response: retrieve them
before diagnosing or reviewing a change. Regex redaction is best effort, not a
complete secret scanner. Cache data remains local until removed.

### 2. 🌳 Repository Token Tree (`tokencut tree`)
Discover what is silently eating your context window before you even start coding:
```bash
tokencut tree .
```
```text
tokencut/  · 170,499 tok (100.0%)
├── src/ · 15,282 tok (9.0%)
├── tests/ · 2,628 tok (1.5%)
└── uv.lock · 148,640 tok (87.2%) ⚠️ Top Token Consumer!
```
*Identifies in 1 second that a lockfile or test fixture is taking 87% of your tokens!*

### 3. ⚡ AST Code Skeletonizer (`tokencut cat --skeleton`)
When exploring large codebases, AI assistants typically dump thousands of lines of implementation logic. `tokencut` generates structural outlines (classes, method signatures, docstrings, type annotations) with bodies replaced by `...`. Agents can inspect individual methods with `--symbol` or line ranges with `--lines`:
```bash
tokencut cat src/auth.py --skeleton
tokencut cat src/auth.py --symbol AuthService.verify_token
```

### 4. 🔒 Secret & API Key Sanitizer
Best-effort pattern matching scrubs recognized credentials before MCP display and cache storage:
- OpenAI API keys (`sk-proj-...`)
- Anthropic API keys (`sk-ant-...`)
- Google Gemini keys (`AIza...`)
- GitHub Personal Access Tokens (`ghp_...`)
- Database connection strings with passwords (`postgres://user:pass@...`)

### 5. 🔌 Universal Model Context Protocol (MCP) Server
Integrate directly into **Claude Code**, **Cursor**, or **Gemini CLI** with **one command**:
```bash
claude mcp add --scope user tokencut -- tokencut mcp
```
Provides Claude with token-optimized tools:
* `tokencut_exec`: Runs terminal commands with automatic log compaction & CCR caching.
* `tokencut_read`: Reads files in AST skeleton or targeted symbol mode.
* `tokencut_retrieve`: Retrieves raw slices from cached outputs via ref ID.
* `tokencut_diff`: Generates slim git diffs with lockfile folding.
* `tokencut_stats`: Reports estimated net output reduction, including retrieval overhead.

### 6. 🔍 Prompt Cache Protector (`tokencut lint`)
`tokencut lint` scans `CLAUDE.md`, `.cursorrules`, and prompt templates for dynamic timestamps and potential cache-busting patterns. Cache behavior and pricing depend on the provider and model:
```bash
tokencut lint CLAUDE.md --minify
```

---

## 🚀 Quick Start

### Install this repository with uv

The PyPI name `tokencut` belongs to another project. Use this Git source, not
`pip install tokencut` or bare `uvx tokencut`:

```bash
uv tool install 'git+https://github.com/00200200/tokencut.git'
```

For reproducibility, append `@<commit-sha>` to the Git URL. Then:

```bash
# Run any command through tokencut
tokencut run -- pytest -v tests/

# Visualize token distribution across your repository
tokencut tree .

# View code file as an AST skeleton (75% token reduction)
tokencut cat src/server.py --skeleton

# Inspect git diff with lockfiles folded (-97% diff tokens)
tokencut diff

# Audit CLAUDE.md for prompt cache busting
tokencut lint CLAUDE.md

# Run interactive visual benchmark demo
tokencut demo
```

### Develop locally

```bash
git clone https://github.com/00200200/tokencut.git
cd tokencut
uv sync --all-extras
```

---

## 🤝 Harness Integrations

### Claude Code
Add `tokencut` as a native MCP server:
```bash
claude mcp add --scope user tokencut -- tokencut mcp
```
Or wrap long-running commands directly:
```bash
tokencut run -- npm test
```

### Cursor / Windsurf
Add to your `mcp.json` (`~/.cursor/mcp.json` or `.cursor/mcp.json`):
```json
{
  "mcpServers": {
    "tokencut": {
      "command": "/absolute/path/to/tokencut",
      "args": ["mcp"]
    }
  }
}
```

### Codex

```bash
codex mcp add tokencut -- tokencut mcp
```

Codex CLI and desktop share `~/.codex/config.toml`. Restart/reconnect MCP after
installation. For desktop clients, use the absolute binary path from
`command -v tokencut` if their PATH differs from your terminal.

### Antigravity / Gemini CLI

Use the same `mcpServers` JSON above. In Antigravity, open **MCP Servers → Manage
MCP Servers → View raw config**. Current versions use `~/.gemini/config/mcp_config.json`;
older IDE versions may use `~/.gemini/antigravity/mcp_config.json`. Gemini CLI uses
`~/.gemini/settings.json`. Merge the entry with existing configuration, then refresh.

For exec/diff, pass the target project's absolute `cwd`. Prefer absolute file paths.
Installation exposes tools; it does not automatically rewrite native shell calls.

---

## 🛠 Command Reference

| Command | Description |
| :--- | :--- |
| `tokencut run <cmd>` | Runs a command and outputs token-compacted stdout/stderr with telemetry. |
| `tokencut tree [dir]` | Visualizes directory token breakdown & identifies top token hogs. |
| `tokencut cat <file> -s` | Displays an AST skeleton of Python, TypeScript, Go, or Rust code. |
| `tokencut cat <file> -l 10-50` | Extracts a targeted line slice with file header context. |
| `tokencut cat <file> -y <sym>` | Extracts a specific class, method, or function by name. |
| `tokencut retrieve <ref_id>` | Retrieves full uncompressed raw output from the CCR cache. |
| `tokencut pipe` | Unix stream filter: read stdin, compact, output to stdout. |
| `tokencut diff [--staged]` | Slims unified git diffs by folding lockfiles and collapsing extra context. |
| `tokencut lint [file]` | Lints `CLAUDE.md` / `.cursorrules` for token bloat and cache-busting timestamps. |
| `tokencut mcp` | Starts the stdio JSON-RPC Model Context Protocol server. |
| `tokencut stats` | Displays lifetime token savings and estimated dollars saved in USD. |
| `tokencut demo` | Interactive visual demo benchmarking token savings on realistic failure traces. |

---

## 🧪 Testing & Code Quality

Run the regression suite and linter:

```bash
# Run unit, integration, and CLI tests
uv run pytest -v

# Run linter
uv run ruff check .

# Run authored fixture benchmarks (no model calls)
uv run python scripts/benchmark_suite.py
```

---

<br />

<div align="center">
  <h3>🌟 Star tokencut on GitHub!</h3>
  <p>If tokencut saved your Claude Code session from hitting the 5-hour limit, please consider giving us a star!</p>
  <a href="https://github.com/00200200/tokencut">
    <img src="https://img.shields.io/github/stars/00200200/tokencut?style=social&label=Star%20us%20on%20GitHub!" alt="GitHub Stars" />
  </a>
</div>
