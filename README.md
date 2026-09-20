<div align="center">
  <a href="https://github.com/00200200/tokencut">
    <img src="assets/banner.svg" alt="tokencut — bounded context tools for AI coding assistants" width="100%" />
  </a>

  <br /><br />

  <p align="center">
    <strong>Smaller tool outputs, with omitted context available on demand.</strong><br />
    <em>A local CLI and MCP server for Claude Code, Codex, Antigravity, and other MCP clients.</em>
  </p>

  <p align="center">
    <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-00f5a0?style=flat-square&logo=opensourceinitiative&logoColor=white" alt="MIT license"></a>
    <a href="https://github.com/00200200/tokencut"><img src="https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-00d9f5?style=flat-square&logo=python&logoColor=white" alt="Python versions"></a>
    <a href="https://github.com/00200200/tokencut/actions/workflows/ci.yml"><img src="https://github.com/00200200/tokencut/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
    <a href="https://github.com/astral-sh/ruff"><img src="https://img.shields.io/badge/code%20style-ruff-261230.svg?style=flat-square&labelColor=000000" alt="Ruff"></a>
    <a href="https://github.com/00200200/tokencut/stargazers"><img src="https://img.shields.io/github/stars/00200200/tokencut?style=flat-square&color=7928ca" alt="GitHub stars"></a>
  </p>
</div>

<br />

<div align="center">
  <img src="assets/demo.svg" alt="tokencut Terminal Execution Demo" width="100%" />
  <p><em>Illustrative terminal demo. Run the fixture benchmark below for reproducible measurements.</em></p>
</div>

---

## Where it helps

Verbose tests, builds, files, and lockfile diffs can fill an agent's context with
irrelevant text. TokenCut filters routine command output and caches the redacted
original for selective retrieval. Command execution preserves diagnostics by
default; truncation requires an explicit budget or compact mode. An opt-in Claude
Code hook filters native Bash results. Other clients use TokenCut's MCP tools or
CLI wrapper. TokenCut does not compress model reasoning or change plan limits.

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
| **TokenCut** | Conservative command filtering, bounded reads, local retrieval | Compare on total tokens per successfully completed task. |

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

## Reproducible fixture benchmarks

Run `python scripts/benchmark_suite.py` (or add `--json`) from the source checkout.
The suite uses authored test/build logs, a synthetic lockfile diff, this
repository's CLI source, and a long-line MCP read. It checks selected diagnostics
for compact mode, exact preservation of a complete failure tail in safe mode,
exact cache recovery, and unchanged unfamiliar output. It reports local token
estimates and tool-schema overhead, with an isolated temporary cache. No model is
called and reasoning quality is not evaluated.

The local counter uses `o200k_base` (with a `cl100k_base` fallback). Claude and
Gemini values are uncalibrated heuristics. These are **not exact counts for Astra,
Fable, Opus, or any named model**, and not measurements of subscription limits.
MCP session stats include recovery notices, exit status, and subsequent retrieval
text; they exclude tool schemas, JSON envelopes, conversation input, and reasoning.
CLI dollar figures use fixed example prices, not your actual bill.

---

## Architecture

`tokencut` is designed around six core mechanisms:

### 1. Compress-Cache-Retrieve (CCR)
`tokencut run` and MCP `tokencut_exec` default to conservative filtering: fold
recognized pytest pass records and exact adjacent repeats, retaining their counts.
Once diagnostics begin, keep the remaining output. Short results and content
outside these patterns pass through after redaction. This mode has no fixed output ceiling.

Use CLI `--compact` for the older lossy filtering, or `--budget` for an explicit
token ceiling. In MCP `tokencut_exec`, supplying `max_tokens` or `max_lines` opts
into truncation. MCP read, diff, and retrieve retain their default 2,000-token
budget (`max_tokens`, 64–32,000). Budgets use local estimates and include recovery
references and, for exec, exit status. Cached output is stored **after recognized
secrets are redacted** in SQLite
(`~/.tokencut/cache.db`; override with `TOKENCUT_CACHE_DIR`):
```text
[... 340 lines of routine output omitted by tokencut (-84.1%). Ref: tc_8f2a1b ...]
```

If an agent or developer needs the omitted output, it can be fetched instantly:

```bash
tokencut retrieve tc_8f2a1b --lines 120-160
```
Or call `tokencut_retrieve` with `ref_id` and `lines`. Redacted values cannot be
recovered. Long diagnostics may be omitted from a bounded response: retrieve them
before diagnosing or reviewing a change. Regex redaction is best effort, not a
complete secret scanner. Cache data remains local until removed.


### 2. Repository Token Profiling (`tokencut tree`)
Identifies high-consumption files and directories before context is loaded into an agent session:

```bash
tokencut tree .
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
tokencut cat src/auth.py --skeleton

# Extract a specific class or method
tokencut cat src/auth.py --symbol AuthService.verify_token

# Extract specific line slice with file context
tokencut cat src/auth.py --lines 45-80
```

### 4. Git Diff Slimming (`tokencut diff`)
Package lockfiles (`uv.lock`, `package-lock.json`, `pnpm-lock.yaml`) often generate thousands of lines of machine-generated diffs that crowd out actual application changes. `tokencut diff` collapses lockfile modifications into summary counts while retaining application changes. MCP output is bounded; retrieve omitted context before reviewing.

### 5. Credential & Secret Scrubbing
Best-effort pattern matching redacts recognized API keys, JWTs, and password-bearing database URLs before MCP display and cache storage. It is not a complete secret scanner.

### 6. Prompt Cache Optimization (`tokencut lint`)
Cache behavior and pricing depend on the provider and model. `tokencut lint` analyzes system instruction files (`CLAUDE.md`, `.cursorrules`, system prompts) to identify dynamic timestamps, non-deterministic paths, and volatile headers that invalidate prompt caches.

---

## Quickstart

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

# Explicitly allow truncation when bounded output is more useful
tokencut run --budget 2000 -- pytest -v tests/

# Visualize token distribution across your repository
tokencut tree .

# Inspect code structure without function bodies
tokencut cat src/server.py --skeleton

# Inspect git diff with folded lockfiles
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

## Integrations

### Claude Code
Register `tokencut` as a native MCP server:

```bash
claude mcp add --scope user tokencut -- tokencut mcp
```

This exposes five tools directly to Claude:
- `tokencut_exec`: Runs bash commands with output compaction and CCR caching.
- `tokencut_read`: Reads files with support for AST skeletons, symbol extraction, and line ranges.
- `tokencut_retrieve`: Retrieves omitted slices from cached terminal runs by reference ID.
- `tokencut_diff`: Generates slim git diffs with lockfile folding.
- `tokencut_stats`: Reports estimated net session output reduction, including retrieval overhead.

You can also wrap commands directly:
```bash
tokencut run -- npm test
```

To filter native Bash output automatically, opt in to the Claude Code hook:

```bash
tokencut hook --install --client claude
```

The installer merges a `PostToolUse` hook into `~/.claude/settings.json`, keeps
existing settings and hooks, and backs up changed configuration. Restart Claude
Code to activate. The hook filters `stdout` and `stderr` with safe mode and keeps
the remaining result fields, including exit status. It does not approve commands
or rewrite their inputs. Commands reported through `PostToolUseFailure` keep their
original diagnostics. This is a Claude Code integration, not a Claude Desktop chat hook.

### Claude Desktop

On macOS, merge the `mcpServers` entry shown below into
`~/Library/Application Support/Claude/claude_desktop_config.json`. Use an absolute
binary path from `command -v tokencut`, restart Claude Desktop, and check
**Settings → Developer** or **+ → Connectors** for the connected server.
This exposes tools; it does not filter every conversation or other tool result.

### Cursor & Windsurf
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

Use explicit `tokencut run -- <command>` inside Codex's native shell tool to
retain its sandbox and approval flow. This wrapper is intended for
noninteractive commands. Avoid granting a blanket approval to all wrapped
commands.

An offline protocol check on CLI 0.154.0 and desktop 0.155.0-alpha.9.2 found that
`PostToolUse` with `continue: false` does not replace the value returned by
`tools.exec_command()` inside code mode: JavaScript can still return the raw
output to the model. TokenCut therefore does not install a Codex output hook.
This check used fixed tool calls and a local mock, not a model evaluation.

### Persistent tool preferences

Keep guidance short and conditional on TokenCut being available:

> Prefer TokenCut for large command results and targeted reads. Preserve errors
> and exit status, retrieve omitted details when needed, and retain existing
> permissions. Avoid extra filtering calls for short results.

- Codex: add to `~/.codex/AGENTS.md`, then start a new session.
- Claude Code: add to `~/.claude/CLAUDE.md`; reload through `/memory` or start a new session.
- Claude Desktop: save in **Settings → General → Instructions for Claude**
  (called profile preferences in older versions).

These are tool-selection preferences, not guaranteed interception. Local MCP
configuration does not apply to ChatGPT web. Reducing tool text does not establish
how much longer Astra, Fable, Opus, or another model's usage allowance will last;
that requires task-level measurements including retries, cache and reasoning.

Client references: [Codex MCP](https://learn.chatgpt.com/docs/extend/mcp),
[Codex instructions](https://learn.chatgpt.com/docs/agent-configuration/agents-md),
[Claude Code instructions](https://support.claude.com/en/articles/14553240-give-claude-context-claude-md-and-better-prompts),
[Claude Desktop instructions](https://support.claude.com/en/articles/16761823-claude-cowork-and-chat-are-one-claude).

### Antigravity / Gemini CLI

Use the same `mcpServers` JSON above. In Antigravity, open **MCP Servers → Manage
MCP Servers → View raw config**. Current versions use `~/.gemini/config/mcp_config.json`;
older IDE versions may use `~/.gemini/antigravity/mcp_config.json`. Gemini CLI uses
`~/.gemini/settings.json`. Merge the entry with existing configuration, then refresh.

For exec/diff, pass the target project's absolute `cwd`. Prefer absolute file paths.
Installation exposes tools; it does not automatically rewrite native shell calls.

Optional shell wrapper:
```bash
alias cc="tokencut run --"
```

---

## CLI Reference

| Command | Description |
| :--- | :--- |
| `tokencut run -- <cmd>` | Safely filters command output; `--compact` or `--budget` permits truncation. |
| `tokencut tree [dir]` | Hierarchical directory token consumption profiler. |
| `tokencut cat <file> -s` | AST structural skeleton (classes, signatures, docstrings). |
| `tokencut cat <file> -y <sym>` | Extracts a specific class, method, or function by name. |
| `tokencut cat <file> -l <range>` | Extracts a specific line range with file context. |
| `tokencut retrieve <ref_id>` | Retrieves uncompressed output from the CCR cache. |
| `tokencut pipe` | POSIX stdin filter for shell integration. |
| `tokencut diff [--staged]` | Slims git diffs by folding lockfiles and condensing whitespace. |
| `tokencut lint [file]` | Lints agent instruction files for prompt cache-busting elements. |
| `tokencut mcp` | Starts the stdio JSON-RPC Model Context Protocol server. |
| `tokencut hook --install --client claude` | Opts in to conservative filtering of Claude Code Bash results. |
| `tokencut stats` | Displays lifetime token savings and estimated dollar savings. |
| `tokencut demo` | Interactive visual demo benchmarking token savings on realistic failures. |

---

## Development

Run the regression suite and linter:

```bash
# Run unit, integration, and CLI tests
uv run pytest -v

# Run the linter
uv run ruff check .

# Run authored fixture benchmarks (no model calls)
uv run python scripts/benchmark_suite.py
```

---

## License

Released under the [MIT License](LICENSE).
