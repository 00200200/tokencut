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

## Try it in one minute

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/getting-started/installation/).
Install this repository: the PyPI name `tokencut` belongs to another project.

```bash
uv tool install 'git+https://github.com/00200200/tokencut.git'
tokencut demo
```

The demo works outside a project and makes **no model calls**. It measures an
authored log, checks the complete diagnostic tail, verifies recovery of the
original, and confirms that unfamiliar output stays unchanged. Checks print
`PASS` or `FAIL`; a failed check returns a nonzero exit code. Use `tokencut demo
--json` for machine-readable results. Demo data uses a disposable cache.

Then try your own command: `tokencut run -- <command> <args>`, or connect
[Claude Code](#claude-code), [Claude Desktop](#claude-desktop-macos),
[Codex](#codex), or [Antigravity](#antigravity--gemini-cli).
Smaller tool output is the measured benefit; subscription limits and task quality
need separate evaluation.

<br />

<div align="center">
  <img src="assets/demo.svg" alt="tokencut Terminal Execution Demo" width="100%" />
  <p><em>Illustrative terminal demo. Run the fixture benchmark below for reproducible measurements.</em></p>
</div>

---

## macOS desktop pet (local preview)

<div align="center">
  <img src="assets/pet-3d.png" alt="TokenCut macOS Desktop Pet Companion" width="220" />
  <p><em>TokenCut Desktop Pet — A draggable macOS companion monitoring real-time tool output reduction and model quota windows.</em></p>
</div>

A small draggable SwiftUI pet lives above other windows, remembers its position,
and keeps working across Spaces. Click it to see quota windows, reset times and
**estimated tool-output reduction**, before/after counts,
recovery costs, seven days of history and breakdowns by client, Git project and tool.
The UI is in English, follows the system appearance, and runs without a Dock icon.
The mint robot uses bundled 3D-rendered artwork on a transparent background, with
a small glass-style quota card. Its subtle hover response respects Reduce Motion;
there is no idle animation, live 3D renderer, or runtime image generation.
Quota percentages are fetched from services, separately from TokenCut savings.
Neither counter measures model reasoning or task quality.

Build with Apple's Swift toolchain (macOS 13+), after installing this checkout:

```bash
uv tool install --force .
bash macos/build.sh
open macos/build/TokenCut.app
```

Preview releases also include a prebuilt macOS ZIP, Python packages and SHA-256
checksums on [GitHub Releases](https://github.com/00200200/tokencut/releases).
Install the matching TokenCut CLI first, extract the app into `~/Applications`,
and launch it. The app resolves `~/.local/bin/tokencut` for the current user.
The ZIP filename states its CPU architecture; it is not a universal binary.

The build is locally ad-hoc signed, not notarized or a public installer. The default
backend is `~/.local/bin/tokencut`; set `TOKENCUT_EXECUTABLE` while building to override
it. Double-click the app to restore the pet. Its menu can open the full panel,
hide the pet, restore its corner position, or enable the optional menu bar item.
The menu item shows
`TC —` when no measurements exist, and `TC Ⅱ` while paused. Refresh is at most every
5 seconds while visible, 30 seconds in the background. The pause is reversible;
it affects new wrapper, MCP and hook transformations, not already running calls.

The app owns a `tokencut monitor --stdio` subprocess; there is no network listener or
AI call. JSON-lines requests support `snapshot`, `pause` (boolean `paused`), `check`,
`export`, `usage`, and `usage-refresh`, with an echoed `id` and `result` or `error`.
Quota reads run in background workers and never block the savings panel. The check exercises a fresh
local MCP connection; it does **not** establish that another running app loaded it.
Existing MCP sessions must reconnect after upgrading the executable.

- `telemetry.db` stores counters and metadata beside each client's `cache.db`.
  Recovery content stays in `cache.db`, never in telemetry or exports.
- The collector discovers the configured Codex sandbox cache without granting it
  additional permissions; aggregates live in `~/.tokencut/metrics.db`. Set
  `TOKENCUT_STATE_DIR` to isolate companion state during development.
- Event IDs make collection and repeated Claude hook delivery idempotent. Legacy
  counts retain unknown client/project, separately from current measurements.
- The main counter uses `o200k_base`, includes retrieval costs and can be negative.
  Claude hook reductions are **prepared**, separately displayed, because there is
  no acceptance acknowledgment. Alternate tokenizer estimates are not added to it.
- Serena remains an independent MCP. Its card shows detected configuration and a
  setup link; the app never activates a project or fabricates Serena savings.
- Add `TOKENCUT_CLIENT=codex|claude-code|claude-desktop|antigravity` to an MCP entry's
  environment for attribution. Without a known client, it is labeled `mcp`/`cli`.
  No conversations or session transcripts are inspected.

### Account limits

- Codex uses the logged-in local CLI's documented
  [`account/rateLimits/read`](https://learn.chatgpt.com/docs/app-server) request.
  It only initializes the connection and reads quota; no thread or model turn is
  created. The CLI account can differ from the one in the Codex desktop app.
- Claude uses the optional [CodexBar CLI](https://github.com/steipete/CodexBar)
  adapter: `brew install --formula steipete/tap/codexbar`. It runs `usage --provider
  claude --source cli --format json --json-only` against the logged-in Claude Code
  CLI. No browser-cookie import or `cost` transcript scan is requested. Logged-out
  or unsupported clients show unavailable data. Logging into Claude Desktop alone
  does not establish a working CLI quota source.
- Service reads happen at most once every five minutes per provider; manual
  refresh has a 30-second minimum interval. Network requests go through the
  providers' existing clients. No prompts or paid model calls are sent.
- The pet shows **remaining** percentage for the most constrained reported
  window; details show every available window and the last successful read time.
  Missing windows, failed reads and elapsed resets never imply 100% remaining.
  Quota data stays in memory and is excluded from savings exports.
- ChatGPT chat quotas and Antigravity quotas are not connected in this version.
  TokenCut filters selected tool results; it does not intercept all chat input,
  generated replies or model reasoning, and it cannot increase subscription limits.

### Conservative RTK adapter

`tokencut run --engine auto|tokencut|rtk|none -- COMMAND` executes COMMAND once.
`auto` considers only literal `git status` and `git diff --stat` with RTK 0.49.0;
other commands and missing/unverified RTK versions use TokenCut. An explicit budget
or compact profile uses TokenCut; combining those with explicit RTK is rejected
before execution. Install optional RTK from its official Homebrew formula: `brew install rtk`.

RTK receives captured output through **`rtk pipe`**, never the user command. Every
nonblank line must survive unchanged and in order; otherwise the adapter returns
the original buffer. Errors and filter failures keep the original without rerunning
the command. Reduced output has a recovery reference, whose overhead is included.
This first adapter is intentionally narrow: ordinary Git output often saves nothing.
RTK's command wrapper for `git status` in 0.49.0 runs Git twice and is not used.
RTK network telemetry is disabled in the adapter; no RTK command-history database
is needed. Its local adapter counter uses **bytes / 4**, including recovery, and is
never added to TokenCut's tokenizer counter. Standalone RTK usage is not imported.

Companion preference changes have unique backups beside `companion.json`. Restore
one of those files to roll back a preference change. Client configuration changes
should preserve other MCP entries and keep a backup before reconnecting a client.

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
| [RTK](https://github.com/rtk-ai/rtk) | Command-specific output filtering | Optional guarded stdin adapter; separately measured. |
| [Repomix](https://github.com/yamadashy/repomix) | Packaging repository context | A relevant baseline for repository exploration. |
| **TokenCut** | Conservative command filtering, bounded reads, local retrieval | Compare on total tokens per successfully completed task. |

No head-to-head task-quality evaluation has established superiority over these tools.

Development priorities:

1. Compare raw tools, Serena, RTK, [Headroom](https://github.com/headroomlabs-ai/headroom),
   TokenCut, and complementary combinations on the same completed coding tasks.
   Record success, retries, latency, total input/output, cache hits, and reasoning
   usage where available. Report model versions and repeated runs, including losses.
2. Extend command-specific parsers and syntax-index coverage; syntax matches
   are not language-server references. Test ambiguous
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

`python scripts/benchmark_code.py` tests locating/reading one method among 100
Python classes, warm-index reuse, and a guarded edit with behavior checks. Add
`--serena /absolute/path/to/serena` for an isolated local Serena comparison
(requires the `mcp` extra and a working Python language server). It does not change
the active Serena project. Tool text and discovery overhead are reported separately.
On the development Mac, a full-file read was 4,000 estimated tokens, TokenCut
lookup + read 130, TokenCut direct read 90, and Serena direct read 87. Tool schemas
were 1,279 vs 6,569 estimated tokens for 8 vs 23 tools with different capabilities.
This fixture establishes neither general superiority nor subscription savings.

The local counter uses `o200k_base` (with a `cl100k_base` fallback). Claude and
Gemini values are uncalibrated heuristics. These are **not exact counts for Astra,
Fable, Opus, or any named model**, and not measurements of subscription limits.
MCP session stats include recovery notices, exit status, and subsequent retrieval
text; they exclude tool schemas, JSON envelopes, conversation input, and reasoning.
The demo and CLI statistics report local text estimates, not dollar savings.

---

## Architecture

`tokencut` provides these local context tools:

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

### Local code navigation and guarded edits

`tokencut code` uses [ast-grep](https://github.com/ast-grep/ast-grep) (MIT)
and SQLite FTS5, without model calls or a background server. It indexes changed
files only, respects Git ignores, skips dependency/build folders and symlinks,
and reports files it could not parse. Python, JS/TS/TSX, Rust, Go, Swift, Java,
and C/C++ have syntax-based declaration lookup; language-specific coverage varies.

```bash
tokencut code "$PWD" --mode map --limit 20
tokencut code "$PWD" --mode symbols --query AuthService.verify_token
tokencut code "$PWD" --mode occurrences --query verify_token
tokencut code "$PWD" --mode search --query 'authentication expired'
tokencut code "$PWD" --mode pattern --query 'print($A)' --file src/auth.py
tokencut retrieve tc_REFERENCE --query 'ConnectionRefusedError'
```

Maps rank declarations by syntactic name occurrence counts; text search uses
BM25. Occurrences can include unrelated symbols with the same name. This does
**not** implement LSP reference resolution or project-wide semantic renaming.
Search snippets identify the chunk's first line, not necessarily the hit's line.
Results default to 2,000 tokens; recover omitted information before relying on it.
The incremental source index lives in `$TOKENCUT_CACHE_DIR/code-index`, separate
from metadata-only telemetry; like the recovery cache, it contains redacted text.

Symbol reads preserve source comments/decorators and include a file SHA-256.
Ambiguous names require a qualified name or `name@line`. Edits run through the
client's **native shell permissions**, with preview as the default:

```bash
tokencut cat "$PWD/src/auth.py" --symbol AuthService.verify_token
# Write the complete replacement declaration, including indentation, to /tmp/replacement.py.
tokencut edit-symbol "$PWD/src/auth.py" AuthService.verify_token \
  --replacement-file /tmp/replacement.py --expected-hash HASH_FROM_READ
# Add --apply to write. A stale hash, ambiguous symbol or syntax error aborts.
```

These checks guard the edit region and file version; they do not prove that the
replacement preserves behavior. Run the project's relevant tests after editing.

### 4. Git Diff Slimming (`tokencut diff`)
Package lockfiles (`uv.lock`, `package-lock.json`, `pnpm-lock.yaml`) often generate thousands of lines of machine-generated diffs that crowd out actual application changes. `tokencut diff` collapses lockfile modifications into summary counts while retaining application changes. MCP output is bounded; retrieve omitted context before reviewing.

### 5. Credential & Secret Scrubbing
Best-effort pattern matching redacts recognized API keys, JWTs, and password-bearing database URLs before MCP display and cache storage. It is not a complete secret scanner.

### 6. Prompt Cache Optimization (`tokencut lint`)
Cache behavior and pricing depend on the provider and model. `tokencut lint` analyzes system instruction files (`CLAUDE.md`, `.cursorrules`, system prompts) to identify dynamic timestamps, non-deterministic paths, and volatile headers that invalidate prompt caches.

### 7. Structured JSON & API Payload Compaction (`tokencut json`)
Folds arrays, long strings, and deeply nested values into a preview with sample
items. The redacted original is cached for recovery. Omitted items may contain
different fields or important values; retrieve them before drawing conclusions.

### 8. System Diagnostics & Auto-Configuration (`tokencut doctor`)
Checks the Python runtime, cache, client configuration, and shell aliases.
`tokencut doctor --fix` and `tokencut install` configure supported integrations.
A successful configuration check does not establish that a live agent used the tools.

### 9. Pull Request Token Impact Analyzer (`tokencut pr`)
Estimates token changes against a Git base ref, grouped into code, documentation,
and lockfiles. `--markdown` emits a review summary; `--max-delta <N>` sets a CI
threshold. This measures repository text, not model usage during a task.

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

# Preview a large JSON response with recovery references
tokencut json api_response.json

# Check local integration configuration
tokencut doctor

# Estimate the token impact of a change
tokencut pr --base main --markdown

# Audit CLAUDE.md for prompt cache busting
tokencut lint CLAUDE.md

# Verify filtering and recovery with a built-in fixture
tokencut demo
```

### Develop locally

```bash
git clone https://github.com/00200200/tokencut.git
cd tokencut
uv sync --all-extras
```

---

## Integrations & Supported Platforms

`tokencut` operates across desktop applications, AI-enabled IDEs, coding agents, and terminal command-line pipelines.

### Configuration helpers

After installing this repository, configure supported targets or inspect their status:

```bash
tokencut install --all
tokencut doctor
```

Use individual install flags for specific clients. These commands expose tools;
they do not make every client route all output through TokenCut.

### Claude Code CLI

Register the MCP server:

```bash
claude mcp add --scope user tokencut -- tokencut mcp
```

This exposes eight tools:
- `tokencut_code`: Incremental repository map, qualified symbols, name occurrences, text and structural search.
- `tokencut_exec`: Runs bash commands with output compaction and CCR caching.
- `tokencut_read`: Reads files with support for AST skeletons, symbol extraction, and line ranges.
- `tokencut_retrieve`: Retrieves omitted slices or matching chunks from one cached result by reference ID.
- `tokencut_diff`: Generates slim git diffs with lockfile folding.
- `tokencut_tree`: Profiles repository token distribution.
- `tokencut_json`: Previews JSON with folded arrays and recoverable omitted values.
- `tokencut_stats`: Reports estimated net session output reduction, including retrieval overhead.

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

### Claude Desktop (macOS)

```bash
tokencut install --claude-desktop
```

Or merge the `mcpServers` entry shown below into
`~/Library/Application Support/Claude/claude_desktop_config.json`. Use an absolute
binary path from `command -v tokencut`, restart Claude Desktop, and check
**Settings → Developer** or **+ → Connectors** for the connected server.
This exposes tools; it does not filter every conversation or other tool result.

### Cursor & Windsurf

Use `tokencut install --cursor` for `~/.cursor/mcp.json`, `tokencut install --windsurf` for `~/.codeium/windsurf/mcp_config.json`, or merge this entry
into the client's MCP configuration:

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

### Codex / local ChatGPT desktop

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
- Claude Desktop: save in **Settings → Account → Instructions for Claude**
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

### Terminal CLI & POSIX Pipelines (Gemini CLI, Codex, bash, zsh)
`tokencut` integrates into standard terminal workflows:
```bash
# Add 'cc' shortcut to ~/.zshrc or ~/.bashrc
tokencut install --alias

# Run commands with automatic token compaction
cc pytest -v tests/
cc npm test

# Pipe stdout/stderr through tokencut
cargo test 2>&1 | tokencut pipe
curl https://api.github.com/repos/00200200/tokencut/commits | tokencut json
```

### GitHub Actions CI Gatekeeper
The composite action can audit PR token delta or wrap test steps:

```yaml
- name: Check PR Token Impact
  uses: 00200200/tokencut@main
  with:
    pr-check: 'true'
    max-token-delta: '25000'
```

### Pre-Commit Hook
Add audits to your `.pre-commit-config.yaml`:

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
| `tokencut run -- <cmd>` | Safely filters command output; `--compact` or `--budget` permits truncation. |
| `tokencut tree [dir]` | Hierarchical directory token consumption profiler. |
| `tokencut cat <file> -s` | AST structural skeleton (classes, signatures, docstrings). |
| `tokencut cat <file> -y <sym>` | Extracts a specific class, method, or function by name. |
| `tokencut cat <file> -l <range>` | Extracts a specific line range with file context. |
| `tokencut retrieve <ref_id>` | Retrieves uncompressed output from the CCR cache. |
| `tokencut json [path]` | Compacts large JSON payloads, folding arrays and caching raw data. |
| `tokencut pipe` | POSIX stdin filter for shell integration. |
| `tokencut diff [--staged]` | Slims git diffs by folding lockfiles and condensing whitespace. |
| `tokencut doctor [--fix]` | Checks local integration configuration and optionally applies fixes. |
| `tokencut install [--all]` | Configures supported MCP clients and shell aliases. |
| `tokencut pr [--base] [-m]` | Analyzes PR token delta and formats Markdown summaries for CI. |
| `tokencut cache [stats\|clear]` | Manages the local SQLite Compress-Cache-Retrieve store. |
| `tokencut lint [file]` | Lints agent instruction files for prompt cache-busting elements. |
| `tokencut mcp` | Starts the stdio JSON-RPC Model Context Protocol server. |
| `tokencut hook --install --client claude` | Opts in to conservative filtering of Claude Code Bash results. |
| `tokencut stats [--format]` | Displays estimated lifetime savings in table, JSON, or Markdown. |
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
