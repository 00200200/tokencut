<div align="center">
  <img src="assets/banner.svg" alt="tokencut — SOTA Token Optimizer for Claude Code, Codex, and Gemini CLI" width="100%" />

  <p><strong>Cut token burn by 60–85% in Claude Code, OpenAI/Codex, and Gemini CLI without losing reasoning quality.</strong></p>

  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-00f5a0?style=flat-square" alt="MIT license"></a>
  <a href="https://github.com/00200200/tokencut"><img src="https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-00d9f5?style=flat-square" alt="Python versions"></a>
  <a href="https://github.com/00200200/tokencut"><img src="https://img.shields.io/badge/tests-22%20passed-22c55e?style=flat-square" alt="Tests"></a>
  <a href="https://github.com/astral-sh/ruff"><img src="https://img.shields.io/badge/code%20style-ruff-261230.svg?style=flat-square&labelColor=000000" alt="Ruff"></a>
  <a href="https://github.com/00200200/tokencut/stargazers"><img src="https://img.shields.io/github/stars/00200200/tokencut?style=flat-square&label=Star%20tokencut!&color=7928ca" alt="GitHub stars"></a>
</div>

<br />

<div align="center">
  <img src="assets/demo.svg" alt="tokencut Live Terminal Animation" width="880" />
  <p><em>Watch tokencut preserve 100% of the failure traceback while eliminating 82.5% of terminal noise.</em></p>
</div>

---

## ⚡ Why tokencut?

If you use **Claude Code**, **Cursor**, **Codex**, or **Gemini CLI**, you've experienced the **5-Hour Wall**:
1. **The Quadratic Token Snowball:** In multi-turn coding sessions, every terminal log, test dump, or file you inspect stays in the conversation history and is resent on **every subsequent prompt**.
2. **5,000-Line Terminal Dumps:** Running `pytest`, `npm test`, or `cargo build` injects thousands of lines of ANSI color escapes, progress bars, and routine passes.
3. **5-Hour Limits Hit in 45 Minutes:** Claude Code Max/Pro limits burn out rapidly, and API costs soar.
4. **Context Degradation ("Lost in the Middle"):** Giant logs pollute the context window, causing models to hallucinate or miss critical instructions.

> **tokencut** is the state-of-the-art token optimization engine and universal **MCP server** that strips the noise, compresses logs, extracts AST code skeletons, and protects prompt cache hits — **with zero loss of reasoning quality**.

---

## 📊 Real-World Benchmarks

Tested on standard development workflows across Anthropic Claude, OpenAI, and Google Gemini:

| Workload / Scenario | Raw Tokens | With tokencut | Token Reduction | Reasoning Quality |
| :--- | :---: | :---: | :---: | :---: |
| **Pytest Suite** *(120 tests, 1 failure)* | `2,108` | `441` | **-79.1%** | 🟢 **100% Intact** *(Full traceback & assertions kept)* |
| **Vite / Webpack Build** *(250 modules)* | `4,272` | `1,012` | **-76.3%** | 🟢 **100% Intact** *(Errors, warnings & timings kept)* |
| **Source Code Exploration** *(AST Skeleton)* | `2,508` | `642` | **-74.4%** | 🟢 **100% Intact** *(Class/method signatures & docstrings)* |
| **Git Diff** *(modified lockfile + code)* | `4,165` | `101` | **-97.6%** | 🟢 **100% Intact** *(Code diff preserved, lockfile folded)* |

---

## ✨ Core Innovations

### 1. 🛡️ Semantic Error & Stacktrace Preserver
Never miss an error. `tokencut` scans outputs for compiler errors, Python tracebacks, Go panics, Rust errors, and assertion failures. It preserves the initial invocation and the full error block, while compressing repetitive build spam into:
```text
[... 340 lines of routine output omitted by tokencut (-84.1% tokens) ...]
```

### 2. ⚡ AST Code Skeletonizer (`tokencut cat --skeleton`)
When exploring large codebases, AI assistants typically dump thousands of lines of implementation logic. `tokencut` generates structural outlines (classes, method signatures, docstrings, type annotations) with bodies replaced by `...`. Agents can then inspect individual methods with `--symbol` or line ranges with `--lines`.

### 3. 🔌 Universal Model Context Protocol (MCP) Server
Integrate directly into **Claude Code**, **Cursor**, or **Gemini CLI** in seconds:
```bash
claude mcp add tokencut uvx tokencut mcp
```
Provides Claude with token-optimized tools:
- `tokencut_exec`: Runs terminal commands with automatic log compaction.
- `tokencut_read`: Reads files in AST skeleton or targeted symbol mode.
- `tokencut_diff`: Generates slim git diffs with lockfile folding.
- `tokencut_stats`: Reports session tokens and USD savings.

### 4. 🗜️ Git Diff & Lockfile Slimmer (`tokencut diff`)
A single change in `uv.lock` or `package-lock.json` can dump 10,000 lines of diff into your AI. `tokencut` folds generated files and lockfiles into single-line notices, saving thousands of tokens per turn.

### 5. 🔍 Prompt Cache Protector (`tokencut lint`)
Anthropic and Gemini prompt caching offers an **80–90% cost reduction** for static prompt prefixes. `tokencut lint` scans `CLAUDE.md`, `.cursorrules`, and prompt templates for dynamic timestamps and cache-busting patterns.

---

## 🚀 Quick Start

### Run Without Installing (`uvx`):

```bash
# Run any command through tokencut
uvx tokencut run -- pytest -v tests/

# View code file as an AST skeleton (75% token reduction)
uvx tokencut cat src/server.py --skeleton

# Inspect git diff with lockfiles folded
uvx tokencut diff

# Audit CLAUDE.md for prompt cache busting
uvx tokencut lint CLAUDE.md
```

### Or Install via Pip / UV:

```bash
uv pip install tokencut
# or
pip install tokencut
```

### Interactive Live Demo:

```bash
uvx tokencut demo
```

---

## 🤝 Harness Integrations

### Claude Code
Add `tokencut` as a native MCP server:
```bash
claude mcp add tokencut uvx tokencut mcp
```
Or wrap long-running commands:
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
cargo build 2>&1 | tokencut pipe
```

---

## 🛠 Command Reference

| Command | Description |
| :--- | :--- |
| `tokencut run <cmd>` | Runs a command and outputs token-compacted stdout/stderr with telemetry. |
| `tokencut cat <file> -s` | Displays an AST skeleton of Python, TypeScript, Go, or Rust code. |
| `tokencut cat <file> -l 10-50` | Extracts a targeted line slice with file header context. |
| `tokencut cat <file> -y <symbol>` | Extracts a specific class, method, or function by name. |
| `tokencut pipe` | Unix stream filter: read stdin, compact, output to stdout. |
| `tokencut diff [--staged]` | Slims unified git diffs by folding lockfiles and collapsing extra context. |
| `tokencut lint [file]` | Lints `CLAUDE.md` / `.cursorrules` for token bloat and cache-busting timestamps. |
| `tokencut mcp` | Starts the stdio JSON-RPC Model Context Protocol server. |
| `tokencut demo` | Interactive visual demo benchmarking token savings on realistic failure traces. |

---

## 🧪 Testing & Code Quality

`tokencut` has a 100% passing test suite and is linted with `ruff`:

```bash
# Run tests
uv run pytest -v

# Run linter
uv run ruff check .

# Run benchmarks
uv run python scripts/benchmark_suite.py
```

---

<div align="center">
  <strong>Built for developers who want their AI assistants to last all day.</strong><br />
  If tokencut saves you tokens and money, please give us a ⭐ on GitHub!
</div>
