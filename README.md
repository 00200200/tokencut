<div align="center">
  <a href="https://github.com/00200200/tokencut">
    <img src="assets/banner.svg" alt="tokencut — Token Optimization Engine for Claude Code, Cursor, Codex, and Gemini CLI" width="100%" />
  </a>

  <br /><br />

  <p align="center">
    <strong>High-performance context compression engine and universal MCP server.</strong><br />
    Reduces token consumption by 60–85% across Claude Code, Cursor, Codex, and Gemini CLI without degrading reasoning or losing tracebacks.
  </p>

  <p align="center">
    <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-00f5a0?style=flat-square&logo=opensourceinitiative&logoColor=white" alt="MIT license"></a>
    <a href="https://github.com/00200200/tokencut"><img src="https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-00d9f5?style=flat-square&logo=python&logoColor=white" alt="Python versions"></a>
    <a href="https://github.com/00200200/tokencut/actions"><img src="https://img.shields.io/badge/tests-62%20passed-22c55e?style=flat-square&logo=pytest&logoColor=white" alt="Tests"></a>
    <a href="https://github.com/astral-sh/ruff"><img src="https://img.shields.io/badge/code%20style-ruff-261230.svg?style=flat-square&labelColor=000000" alt="Ruff"></a>
    <a href="https://github.com/00200200/tokencut"><img src="https://img.shields.io/github/stars/00200200/tokencut?style=flat-square&color=7928ca" alt="GitHub stars"></a>
  </p>
</div>

<br />

<div align="center">
  <img src="assets/demo.svg" alt="tokencut Terminal Execution Demo" width="100%" />
  <p><em>Failure isolation: assertion failures and full tracebacks are retained while repetitive terminal noise is compacted.</em></p>
</div>

---

## The Context Accumulation Problem

AI coding agents (Claude Code, Cursor, Codex, Gemini CLI) run inside multi-turn conversation sessions. Every executed command, test runner output, and inspected file is appended to the conversation history and resent on every subsequent turn:

- **Quadratic Token Accumulation:** A 2,000-line test run does not consume tokens once—it is transmitted to the model on every subsequent prompt in the session.
- **Low Signal-to-Noise Ratio:** Routine test passes, compiler progress bars, and ANSI escape sequences dominate terminal dumps. The actual failure or error trace is often under 30 lines.
- **Premature Rate Limits:** API quotas and usage limits (such as the Claude Code 5-hour window) are exhausted by repetitive output rather than code generation and reasoning.
- **Context Window Degradation:** Splicing thousands of irrelevant terminal lines into the context window triggers needle-in-a-haystack degradation, increasing the likelihood that the model forgets earlier instructions.

<br />

<div align="center">
  <img src="assets/comparison.svg" alt="Context growth comparison: Raw Claude Code vs tokencut" width="100%" />
</div>

<br />

---

## Comparison

How `tokencut` compares to standard agent execution, static context packagers (such as Repomix), and generic context buffers:

| Capability | Raw Agent / CLI | Repomix | Headroom | tokencut |
| :--- | :---: | :---: | :---: | :--- |
| **Real-time terminal compaction** | None | Static only | Truncation only | **Adaptive (head + tail + full error trace)** |
| **Traceback & error preservation** | No | No | No | **Deterministic extraction (tracebacks never lost)** |
| **Reversible CCR architecture** | No | No | SQLite cache | **SQLite store + Ref IDs (`tokencut retrieve`)** |
| **Repository token profiling** | No | File list | No | **Hierarchical breakdown (`tokencut tree`)** |
| **AST code skeletonization** | No | Tree-sitter | No | **Python AST, TS, JS, Go, Rust (`tokencut cat -s`)** |
| **Lockfile diff folding (-97%)** | No | No | No | **Automated lockfile folding (`tokencut diff`)** |
| **Structured JSON payload compaction** | Raw dump | No | Truncate | **Schema-preserving array folding (`tokencut json`)** |
| **Secret & credential scrubbing** | Leaks in history | Basic | No | **Automatic regex redactor (OpenAI, Anthropic, GH)** |
| **System diagnostics & auto-wiring** | Manual | No | No | **1-click auto-config (`tokencut doctor --fix`)** |
| **Native MCP server** | No | No | Wrapper needed | **7 native stdio tools (`claude mcp add ...`)** |
| **Token & cost telemetry** | No | No | No | **Session & lifetime tracking in USD** |

---

## Empirical Benchmarks

Measured on representative real-world developer workloads across Anthropic Claude, OpenAI, and Google Gemini tokenizers:

| Workload / Scenario | Raw Tokens | With tokencut | Reduction | Signal Quality |
| :--- | :---: | :---: | :---: | :--- |
| **Pytest test suite** *(120 tests, 1 failure)* | 2,108 | 441 | **-79.1%** | Full traceback, assertion, and frame context retained |
| **Vite / Webpack build** *(250 modules)* | 4,272 | 1,012 | **-76.3%** | Errors, warnings, and asset summary retained |
| **Source file inspection** *(AST skeleton)* | 2,508 | 642 | **-74.4%** | Class/method signatures and docstrings retained |
| **Git diff** *(feature code + lockfile)* | 4,165 | 101 | **-97.6%** | Code changes preserved; lockfile diffs collapsed |
| **Git log history** *(50 commits)* | 3,120 | 780 | **-75.0%** | Single-line short hashes and subject lines |
| **REST / GraphQL API JSON** *(50 items, 13KB)* | 2,914 | 240 | **-91.8%** | Complete schema and sample items retained |

---

## Architecture

`tokencut` is designed around six core mechanisms:

### 1. Reversible Compress-Cache-Retrieve (CCR)
Context compaction should never cause irreversible data loss. When `tokencut` truncates repetitive output, it persists the full uncompressed stream to a local SQLite database (`~/.tokencut/cache.db`) and injects a deterministic reference identifier:

```text
[... 340 lines of routine output omitted by tokencut (-84.1%). Ref: tc_8f2a1b ...]
```

If an agent or developer needs the omitted output, it can be fetched instantly:

```bash
tokencut retrieve tc_8f2a1b --lines 120-160
```

Or programmatically through the native `tokencut_retrieve` tool via MCP.

### 2. Repository Token Profiling (`tokencut tree`)
Identifies high-consumption files and directories before context is loaded into an agent session:

```bash
uvx tokencut tree .
```

```text
tokencut/  · 170,499 tok (100.0%)
├── src/ · 15,282 tok (9.0%)
├── tests/ · 2,628 tok (1.5%)
└── uv.lock · 148,640 tok (87.2%) [Top Consumer]
```

### 3. AST Code Skeletonization (`tokencut cat --skeleton`)
During multi-file codebase navigation, feeding complete implementation bodies into the prompt exhausts context rapidly. `tokencut cat` parses Python files via the standard library `ast` module and other languages (TypeScript, JavaScript, Go, Rust) via structural regex to extract classes, method signatures, type annotations, and docstrings:

```bash
# View outline of a module
uvx tokencut cat src/auth.py --skeleton

# Extract a specific class or method
uvx tokencut cat src/auth.py --symbol AuthService.verify_token

# Extract specific line slice with file context
uvx tokencut cat src/auth.py --lines 45-80
```

### 4. Git Diff Slimming (`tokencut diff`)
Package lockfiles (`uv.lock`, `package-lock.json`, `pnpm-lock.yaml`) often generate thousands of lines of machine-generated diffs that crowd out actual application changes. `tokencut diff` collapses lockfile modifications into summary counts while preserving application code diffs in full fidelity.

### 5. Credential & Secret Scrubbing
Intercepts API keys (OpenAI `sk-*`, Anthropic `sk-ant-*`, Google `AIza*`, GitHub `ghp_*`), JWTs, and database URLs containing passwords before they enter agent context or terminal logs.

### 6. Prompt Cache Optimization (`tokencut lint`)
Provider prompt caching (Anthropic, Gemini) offers up to 90% cost savings for invariant prompt prefixes. `tokencut lint` analyzes system instruction files (`CLAUDE.md`, `.cursorrules`, system prompts) to identify dynamic timestamps, non-deterministic paths, and volatile headers that invalidate prompt caches.

### 7. Structured JSON & API Payload Compaction (`tokencut json`)
When coding agents fetch API responses via `curl` or inspect JSON data files, hundreds of repetitive array items quickly burn tens of thousands of tokens. `tokencut json` folds large lists while retaining the first few items and schema annotations, truncates oversized strings (such as base64 images or hashes), and caches the raw JSON in SQLite with a reference ID.

### 8. System Diagnostics & Auto-Configuration (`tokencut doctor`)
Inspects your local environment across Python runtime, SQLite cache health, Claude Code CLI, Cursor MCP configurations, and shell aliases. Running `tokencut doctor --fix` or `tokencut install --all` automatically writes the required configurations with zero manual editing.

### 9. Pull Request Token Impact Analyzer (`tokencut pr`)
Evaluates the net token delta introduced by code changes against `main` or a target base ref. Categorizes token impact into code, documentation, and lockfiles, and emits a clean Markdown summary for GitHub PR review comments. When run with `--max-delta <N>`, it acts as an automated CI gatekeeper preventing accidental lockfile or fixture context bloat.

---

## Quickstart

Run directly without installation via `uvx`:

```bash
# Execute a test suite through tokencut
uvx tokencut run -- pytest -v tests/

# Analyze repository token distribution
uvx tokencut tree .

# Inspect code structure without function bodies
uvx tokencut cat src/server.py --skeleton

# Inspect git diff with folded lockfiles
uvx tokencut diff

# Compact large JSON file or API response
uvx tokencut json api_response.json

# Check environment health & auto-configure Cursor / shell
uvx tokencut doctor --fix

# Audit instructions for prompt cache-busting
uvx tokencut lint CLAUDE.md

# Run the terminal demonstration
uvx tokencut demo
```

Or install globally:

```bash
uv pip install tokencut
# or
pip install tokencut
```

---

## Integrations

### Claude Code
Register `tokencut` as a native MCP server:

```bash
claude mcp add tokencut uvx tokencut mcp
```

This exposes seven tools directly to Claude:
- `tokencut_exec`: Runs bash commands with output compaction, CCR caching, and optional `--budget`.
- `tokencut_read`: Reads files with support for AST skeletons, symbol extraction, and line ranges.
- `tokencut_retrieve`: Retrieves omitted slices from cached terminal runs by reference ID.
- `tokencut_diff`: Generates slim git diffs with lockfile folding.
- `tokencut_tree`: Profiles directory-level token consumption directly inside conversation.
- `tokencut_json`: Compresses large JSON payloads and API responses with schema retention.
- `tokencut_stats`: Reports session and lifetime token savings.

You can also wrap commands directly:
```bash
tokencut run -- npm test
```

### Cursor & Windsurf
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

### Gemini CLI, Codex, and Unix Pipelines
`tokencut` integrates into standard POSIX pipes:

```bash
cargo test 2>&1 | tokencut pipe
```

Add a shell alias for seamless execution:

```bash
alias cc="tokencut run --"
```

### GitHub Actions CI Gatekeeper
Use the official composite action to audit PR token delta or wrap test steps:

```yaml
- name: Check PR Token Impact
  uses: 00200200/tokencut@main
  with:
    pr-check: 'true'
    max-token-delta: '25000'
```

### Pre-Commit Hook
Add to your `.pre-commit-config.yaml` to prevent prompt cache-busting before committing:

```yaml
repos:
  - repo: https://github.com/00200200/tokencut
    rev: main
    hooks:
      - id: tokencut-lint
      - id: tokencut-pr
```

---

## CLI Reference

| Command | Description |
| :--- | :--- |
| `tokencut run <cmd>` | Runs command with real-time log compaction, CCR caching, and telemetry. |
| `tokencut tree [dir]` | Hierarchical directory token consumption profiler. |
| `tokencut cat <file> -s` | AST structural skeleton (classes, signatures, docstrings). |
| `tokencut cat <file> -y <sym>` | Extracts a specific class, method, or function by name. |
| `tokencut cat <file> -l <range>` | Extracts a specific line range with file context. |
| `tokencut retrieve <ref_id>` | Retrieves uncompressed output from the CCR cache. |
| `tokencut json [path]` | Compacts large JSON payloads, folding arrays and caching raw data. |
| `tokencut pipe` | POSIX stdin filter for shell integration. |
| `tokencut diff [--staged]` | Slims git diffs by folding lockfiles and condensing whitespace. |
| `tokencut doctor [--fix]` | Diagnoses environment health and auto-configures Cursor / shell. |
| `tokencut install [--all]` | Automatically configures Cursor MCP and shell aliases. |
| `tokencut pr [--base] [-m]` | Analyzes PR token delta and formats Markdown summaries for CI. |
| `tokencut cache [stats\|clear]` | Manages the local SQLite Compress-Cache-Retrieve store. |
| `tokencut lint [file]` | Lints agent instruction files for prompt cache-busting elements. |
| `tokencut mcp` | Starts the stdio JSON-RPC Model Context Protocol server. |
| `tokencut stats [--format]` | Displays lifetime token savings in table, JSON, or Markdown. |
| `tokencut demo` | Interactive visual demo benchmarking token savings on realistic failures. |

---

## Development

```bash
# Clone the repository
git clone https://github.com/00200200/tokencut.git
cd tokencut

# Install dependencies in a virtual environment
uv sync

# Run the test suite (37 tests)
uv run pytest -v

# Run the linter
uv run ruff check .

# Run the benchmark suite
uv run python scripts/benchmark_suite.py
```

---

## License

Released under the [MIT License](LICENSE).
