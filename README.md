<div align="center">
  <a href="https://github.com/00200200/tokencut">
    <img src="assets/banner.svg" alt="tokencut — SOTA Token Optimizer for Claude Code, Codex, and Gemini CLI" width="100%" />
  </a>

  <br /><br />

  <p align="center">
    <strong>⚡ The undisputed SOTA context compactor & universal MCP server for AI coding assistants.</strong><br />
    <em>Cut token burn by 60–85% in Claude Code, Cursor, Codex, and Gemini CLI — with 100% reasoning quality intact.</em>
  </p>

  <p align="center">
    <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-00f5a0?style=for-the-badge&logo=opensourceinitiative&logoColor=white" alt="MIT license"></a>
    <a href="https://github.com/00200200/tokencut"><img src="https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-00d9f5?style=for-the-badge&logo=python&logoColor=white" alt="Python versions"></a>
    <a href="https://github.com/00200200/tokencut"><img src="https://img.shields.io/badge/tests-36%20passed-22c55e?style=for-the-badge&logo=pytest&logoColor=white" alt="Tests"></a>
    <a href="https://github.com/astral-sh/ruff"><img src="https://img.shields.io/badge/code%20style-ruff-261230.svg?style=for-the-badge&labelColor=000000" alt="Ruff"></a>
    <a href="https://github.com/00200200/tokencut/stargazers"><img src="https://img.shields.io/github/stars/00200200/tokencut?style=for-the-badge&label=Star%20Us!&color=7928ca" alt="GitHub stars"></a>
  </p>
</div>

<br />

<div align="center">
  <img src="assets/demo.svg" alt="tokencut Live Terminal Animation" width="100%" />
  <p><em>Watch tokencut preserve 100% of the failure traceback while eliminating 82.5% of terminal noise.</em></p>
</div>

---

## 🛑 The 5-Hour Rate Limit Wall

If you use **Claude Code**, **Cursor**, **Codex**, or **Gemini CLI**, you know the frustration:
* **The Quadratic Token Snowball:** In multi-turn coding sessions, every terminal log, test dump, and inspected file stays in conversation history and is resent on **every subsequent prompt**.
* **5,000-Line Terminal Dumps:** Running `pytest`, `npm test`, or `cargo build` injects thousands of lines of ANSI escapes, progress bars, and passing tests.
* **5-Hour Limit Reached in 48 Minutes:** Claude Code Pro/Max limits exhaust before noon.
* **Context Degradation ("Lost in the Middle"):** Massive logs pollute the context window, causing models to miss instructions or hallucinate.

<br />

<div align="center">
  <img src="assets/comparison.svg" alt="The 5-Hour Wall: Standard Claude Code vs tokencut" width="100%" />
</div>

<br />

---

## 🏆 Feature Comparison: Why tokencut is the Undisputed SOTA

`tokencut` synthesizes the best ideas from across the AI developer ecosystem into a single unified CLI and universal **MCP server**:

| Feature | Raw Claude / Cursor | Repomix | Headroom | ⚡ **tokencut** |
| :--- | :---: | :---: | :---: | :---: |
| **Real-time Terminal Output Compaction** | ❌ None | ❌ Static only | ⚠️ Generic truncate | 🟢 **SOTA (Head + Tail + Full Error Trace)** |
| **Semantic Error & Traceback Preserver** | ❌ No | ❌ No | ❌ No | 🟢 **100% Intact (Tracebacks never lost)** |
| **Reversible CCR Architecture (Ref IDs)** | ❌ No | ❌ No | 🟢 Yes (SQLite) | 🟢 **Yes (`tokencut retrieve <id>`)** |
| **Repo Token Tree Scanner (`tree`)** | ❌ No | 🟢 Yes | ❌ No | 🟢 **Yes (Pinpoints 140k-token lockfiles)** |
| **AST Code Skeletonizer** | ❌ No | 🟢 (Tree-sitter) | ❌ No | 🟢 **Yes (Python AST, TS/JS, Go, Rust)** |
| **Lockfile Diff Folding (-97.6%)** | ❌ No | ❌ No | ❌ No | 🟢 **Yes (`tokencut diff`)** |
| **Secret & API Key Redactor** | ❌ Leaks keys | ⚠️ Basic | ❌ No | 🟢 **Auto-Scrubs OpenAI/Anthropic/GH keys** |
| **Zero-Setup Universal MCP Server** | ❌ No | ❌ No | ⚠️ Setup needed | 🟢 **1-Click (`claude mcp add ...`)** |
| **Multi-Provider Telemetry & Cost Tracker** | ❌ No | ❌ No | ❌ No | 🟢 **Exact Claude, GPT-4o, Gemini USD stats** |

---

## 📊 Real-World Benchmarks

Tested on real production workloads across Anthropic Claude, OpenAI, and Google Gemini:

| Workload / Scenario | Raw Tokens | With tokencut | Token Reduction | Reasoning Quality |
| :--- | :---: | :---: | :---: | :---: |
| **Pytest Test Suite** *(120 tests, 1 failure)* | `2,108` | `441` | **-79.1%** | 🟢 **100% Intact** *(Full traceback, assert & frame details)* |
| **Vite / Webpack Build** *(250 modules)* | `4,272` | `1,012` | **-76.3%** | 🟢 **100% Intact** *(Errors, warnings & bundle stats kept)* |
| **Source Code Exploration** *(AST Skeleton)* | `2,508` | `642` | **-74.4%** | 🟢 **100% Intact** *(Class/method signatures & docstrings)* |
| **Git Diff** *(modified lockfile + code)* | `4,165` | `101` | **-97.6%** | 🟢 **100% Intact** *(Code diff preserved, lockfile folded)* |

---

## 💎 The 6 Architectural Pillars

### 1. 🛡️ 100% Reversible Compress-Cache-Retrieve (CCR)
Never fear losing context. Whenever `tokencut` truncates noisy logs, it automatically caches the full uncompressed output in a local SQLite store (`~/.tokencut/cache.db`) and injects a reference tag:
```text
[... 340 lines of routine output omitted by tokencut (-84.1%). Ref: tc_8f2a1b ...]
```
If the AI model or developer ever needs the exact omitted lines:
```bash
tokencut retrieve tc_8f2a1b --lines 120-160
```
Or the model calls the native `tokencut_retrieve` tool via MCP. **Zero data loss guarantee.**

### 2. 🌳 Repository Token Tree (`tokencut tree`)
Discover what is silently eating your context window before you even start coding:
```bash
uvx tokencut tree .
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
uvx tokencut cat src/auth.py --skeleton
uvx tokencut cat src/auth.py --symbol AuthService.verify_token
```

### 4. 🔒 Secret & API Key Sanitizer
Prevents catastrophic credential leakage to LLM training logs and saves token overhead. Automatically scrubs:
- OpenAI API keys (`sk-proj-...`)
- Anthropic API keys (`sk-ant-...`)
- Google Gemini keys (`AIza...`)
- GitHub Personal Access Tokens (`ghp_...`)
- Database connection strings with passwords (`postgres://user:pass@...`)

### 5. 🔌 Universal Model Context Protocol (MCP) Server
Integrate directly into **Claude Code**, **Cursor**, or **Gemini CLI** with **one command**:
```bash
claude mcp add tokencut uvx tokencut mcp
```
Provides Claude with token-optimized tools:
* `tokencut_exec`: Runs terminal commands with automatic log compaction & CCR caching.
* `tokencut_read`: Reads files in AST skeleton or targeted symbol mode.
* `tokencut_retrieve`: Retrieves raw slices from cached outputs via ref ID.
* `tokencut_diff`: Generates slim git diffs with lockfile folding.
* `tokencut_stats`: Reports session tokens and USD savings.

### 6. 🔍 Prompt Cache Protector (`tokencut lint`)
Anthropic and Gemini prompt caching offers an **80–90% cost reduction** for static prompt prefixes. `tokencut lint` scans `CLAUDE.md`, `.cursorrules`, and prompt templates for dynamic timestamps and cache-busting patterns:
```bash
uvx tokencut lint CLAUDE.md --minify
```

---

## 🚀 Quick Start

### Run Instantly Without Installing (`uvx`):

```bash
# Run any command through tokencut
uvx tokencut run -- pytest -v tests/

# Visualize token distribution across your repository
uvx tokencut tree .

# View code file as an AST skeleton (75% token reduction)
uvx tokencut cat src/server.py --skeleton

# Inspect git diff with lockfiles folded (-97% diff tokens)
uvx tokencut diff

# Audit CLAUDE.md for prompt cache busting
uvx tokencut lint CLAUDE.md

# Run interactive visual benchmark demo
uvx tokencut demo
```

### Or Install Globally:

```bash
uv pip install tokencut
# or
pip install tokencut
```

---

## 🤝 Harness Integrations

### Claude Code
Add `tokencut` as a native MCP server:
```bash
claude mcp add tokencut uvx tokencut mcp
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
      "command": "uvx",
      "args": ["tokencut", "mcp"]
    }
  }
}
```

### Gemini CLI / Codex
Use unix piping in your scripts or agents:
```bash
cargo test 2>&1 | tokencut pipe
```

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
| `tokencut demo` | Interactive visual demo benchmarking token savings on realistic failure traces. |

---

## 🧪 Testing & Code Quality

`tokencut` has a 100% passing test suite and is linted with `ruff`:

```bash
# Run 25 test cases across unit, integration, and CLI layers
uv run pytest -v

# Run linter
uv run ruff check .

# Run real-world benchmarks
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
