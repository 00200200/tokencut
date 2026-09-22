<p align="center">
  <picture>
    <source media="(prefers-reduced-motion: reduce)" srcset="assets/readme-hero.png">
    <img src="assets/readme-hero.gif" width="100%" alt="TokenCut: keep the signal, cut the noise. Authored fixtures: docker build 18,360→107; cargo test 3,795→185; pytest noisy failure 5,111→348; pytest recovery demo 1,562→174.">
  </picture>
</p>

<p align="center">
  <strong>Smaller tool outputs. Precise code context. Details back when you need them.</strong><br>
  Local CLI + MCP server for Claude Code, Codex, Cursor, and friends — optional macOS desktop pet.
</p>

<p align="center">
  <a href="https://github.com/00200200/tokencut/actions/workflows/ci.yml"><img src="https://github.com/00200200/tokencut/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://github.com/00200200/tokencut/releases"><img src="https://img.shields.io/github/v/release/00200200/tokencut?color=b3f5cd&amp;label=release" alt="Release"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-b3f5cd" alt="MIT license"></a>
  <a href="https://modelcontextprotocol.io"><img src="https://img.shields.io/badge/MCP-compatible-2ec79b" alt="MCP Compatible"></a>
  <img src="https://img.shields.io/badge/runs%20in-Claude%20Code%20·%20Codex%20·%20Cursor-1a3330" alt="Runs in Claude Code, Codex, Cursor">
  <a href="https://github.com/00200200/tokencut/stargazers"><img src="https://img.shields.io/github/stars/00200200/tokencut?style=social" alt="GitHub stars"></a>
</p>

<p align="center">
  <a href="#install">Install</a> ·
  <a href="#see-it-cut">Demo</a> ·
  <a href="#connect-your-agent">Connect</a> ·
  <a href="#desktop-companion">Pet</a> ·
  <a href="docs/guide.md">Guide</a>
</p>

---

## Install

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/getting-started/installation/).

```sh
uv tool install 'git+https://github.com/00200200/tokencut.git'
tokencut demo
```

> **Install from this GitHub repo.** The PyPI package named `tokencut` is a different project.

```
verbose tool text  →  keep the failure  →  recover the rest by reference
```

## See it cut

`tokencut demo` runs offline, makes **no model calls**, and checks that failures are preserved, the original recovers exactly, unknown output stays unchanged, and the specialized cutters for pytest / Docker / cargo / go / nextest / vitest / npm test / tsc / ESLint / mypy / pyright compact as measured below.

```
                  TokenCut: verify your installation
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Authored fixture                          ┃ Result                 ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━┩
│ pytest (incl. recovery notice)            │ 1,562 -> 174 (88.9%)   │
│ pytest noisy failure (xdist + I/O)        │ 5,111 -> 348 (93.2%)   │
│ git diff (lockfile + code hunk)           │ 855 -> 111 (87.0%)     │
│ ruff check (full frames)                  │ 146 -> 82 (43.8%)      │
│ docker build (BuildKit progress)          │ 18,360 -> 107 (99.4%)  │
│ cargo test (pass + backtrace)             │ 3,795 -> 185 (95.1%)   │
│ go test (pass + goroutine dump)           │ 3,281 -> 64 (98.0%)    │
│ cargo nextest (passing run)               │ 464 -> 46 (90.1%)      │
│ vitest (390 passing tests)                │ 3,816 -> 44 (98.8%)    │
│ npm test (console dumps)                  │ 1,588 -> 156 (90.2%)   │
│ tsc (pretty frames)                       │ 369 -> 77 (79.1%)      │
│ eslint (codeframe + stacks)               │ 293 -> 61 (79.2%)      │
│ mypy --pretty (frames)                    │ 522 -> 259 (50.4%)     │
│ pyright (frames across files)             │ 4,244 -> 2,302 (45.8%) │
│ complete failure tail preserved           │ PASS                   │
│ original recovered exactly                │ PASS                   │
│ unknown output unchanged                  │ PASS                   │
│ git diff folds lockfile keeps code        │ PASS                   │
│ ruff keeps codes drops frames             │ PASS                   │
│ docker keeps failure drops layer progress │ PASS                   │
│ tsc keeps codes drops frames              │ PASS                   │
│ eslint keeps rules drops frames           │ PASS                   │
│ mypy keeps codes drops frames             │ PASS                   │
│ npm test keeps failure drops console      │ PASS                   │
│ cargo keeps failure drops passes          │ PASS                   │
│ go keeps failure drops passes             │ PASS                   │
│ nextest collapses passes                  │ PASS                   │
│ pytest noise keeps failure drops io       │ PASS                   │
│ pyright keeps diagnostics drops frames    │ PASS                   │
│ vitest collapses passing runs             │ PASS                   │
│ smaller including recovery notice         │ PASS                   │
└───────────────────────────────────────────┴────────────────────────┘
```

| Authored fixture | Tokens |
| --- | ---: |
| pytest original → TokenCut (incl. recovery) | 1,562 → **174** |
| pytest noisy failure (xdist + captured I/O) | 5,111 → **348** |
| `git diff` with lockfile noise | 855 → **111** |
| `ruff check` full frames | 146 → **82** |
| `docker build` BuildKit progress | 18,360 → **107** |
| `cargo test` passes + backtrace | 3,795 → **185** |
| `go test` passes + goroutine dump | 3,281 → **64** |
| `cargo nextest` passing run | 464 → **46** |
| `vitest` 390 passing tests | 3,816 → **44** |
| `npm test` console dumps | 1,588 → **156** |
| `tsc` pretty frames | 369 → **77** |
| `eslint` codeframe + stacks | 293 → **61** |
| `mypy` --pretty frames | 522 → **259** |
| `pyright` frames across files | 4,244 → **2,302** |

**99.4% on the docker BuildKit fixture; 95.1% / 98.0% on cargo / go test dumps; 93.2% on noisy pytest failures.** Reproduce with `tokencut demo --json`.
Local `o200k_base` estimate — not a billing, quality, or subscription-limit claim.

Try it on a real command:

```sh
tokencut run -- pytest -v
tokencut run -- git diff
tokencut run -- ruff check .
tokencut run -- docker build -t app .
tokencut run -- cargo test
tokencut run -- go test -v ./...
tokencut run -- cargo nextest run
tokencut run -- npx vitest run
tokencut run -- npm test
tokencut run -- npx tsc --noEmit
tokencut run -- npx eslint . --format codeframe
tokencut run -- mypy src
tokencut run -- npx pyright
```

## What you get

- **Useful output, recoverable detail.** Fold recognized noise, keep diagnostics, retrieve omitted text by reference.
- **Session dedup + spill.** Identical output within ~15 minutes collapses to a short cache ref; payloads over ~20 KiB become a file path + preview (override with `TOKENCUT_SPILL_BYTES`).
- **Code without whole-file dumps.** Search symbols, read exact methods, inspect outlines, preview edits guarded by a file hash. Syntax indexing is local — no language-server daemons.
- **Context you choose.** Package selected files, compact pasted logs or tables, optimize mixed prompts, save short task checkpoints. Transcript distillation is explicit and lossy; it does not intercept chat.
- **Visible measurements.** `tokencut gain` shows per-tool-family savings and passthrough candidates (like RTK’s gain/unchopped). Account-limit readings stay separate from estimated text savings.

Default filtering preserves unfamiliar output. Stronger truncation is opt-in.
Reference resolution uses syntax, not full LSP semantics. [Details and tradeoffs →](docs/guide.md)

```sh
tokencut gain              # summary + by tool family + passthrough
tokencut gain --history    # recent events
tokencut gain --json
```

### Before you send a message

**Prepare for chat** (macOS pet / dashboard, or CLI) pastes a log or transcript, compares both versions, and copies a preview into Codex, Claude Desktop, or a CLI chat. No model calls. Conservative filtering by default; conversation summaries are an explicit, lossy option.

```sh
tokencut prepare --file draft.txt
```

## Connect your agent

**Coding profile** for everyday use: 8 core tools instead of 15, with **about 37% smaller tool schemas** in the current local `o200k_base` measurement (2,881 → 1,816 tokens). Tool loading varies by client — not a per-turn usage guarantee.

```sh
# Claude Code
claude mcp add --scope user tokencut -- tokencut mcp --profile coding

# Codex
codex mcp add tokencut -- tokencut mcp --profile coding

# Claude Desktop (config) + optional Extension manifest
tokencut install --claude-desktop
tokencut install --mcpb
```

Already registered? Update the server args, then reconnect. For Claude Desktop, Cursor, Windsurf, and other MCP clients:

```json
{
  "mcpServers": {
    "tokencut": {
      "command": "/absolute/path/to/tokencut",
      "args": ["mcp", "--profile", "coding"]
    }
  }
}
```

Path: `command -v tokencut`. Use `--profile full` for every MCP tool; CLI commands stay available either way. In Codex, run `tokencut run` inside its native terminal when you need its sandbox and approvals.

[Client setup, hooks, task memory →](docs/guide.md#connect-clients)

## Desktop companion

Mint robot on your Mac — draggable pet or quiet menu-bar mode. Tool-output measurements, recovery costs, task memory, and live account-limit readings when connected. English UI. Local storage. No extra AI calls.

<p align="center">
  <img src="assets/macos-pet.png" width="640" alt="TokenCut macOS pet with example five-hour balances: Codex 68% left, Claude 42% left.">
</p>

*Example balances (**Codex 68% left · Claude 42% left**) are remaining allowance in their five-hour windows — not savings caused by TokenCut.*

![Native macOS Prepare for chat window comparing an authored conversation with a locally prepared summary.](assets/macos-conversation.png)

*Actual app UI with an authored transcript fixture. Preview counts are not recorded savings. [Log preparation →](assets/macos-prepare.png)*

**macOS 13+ · local preview · ad-hoc signed, not notarized.** CLI and MCP do not need the pet.
[Build the companion →](docs/guide.md#macos-companion)

## Make it better with us

If TokenCut earns a place in your workflow, **[give it a star](https://github.com/00200200/tokencut/stargazers)** — it helps other developers find it. Lost context or a missed optimization? [Open an issue](https://github.com/00200200/tokencut/issues/new) with a small redacted example.

<p align="center">
  <a href="https://star-history.com/#00200200/tokencut&amp;Date">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=00200200/tokencut&amp;type=Date&amp;theme=dark" />
      <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=00200200/tokencut&amp;type=Date" />
      <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=00200200/tokencut&amp;type=Date" width="600" />
    </picture>
  </a>
</p>

[Guide](docs/guide.md) · [Reproducible benchmarks](docs/guide.md#measurements-and-development) · [MIT](LICENSE)
