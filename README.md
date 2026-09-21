<div align="center">
  <picture>
    <source media="(prefers-reduced-motion: reduce)" srcset="assets/readme-hero.png">
    <img src="assets/readme-hero.gif" width="1040" alt="TokenCut and its mint robot companion. Keep the signal, cut the noise. Built-in pytest fixture: 1,562 to 174 tokens, with the failure preserved and original recoverable.">
  </picture>

  <p><strong>Smaller tool outputs. Precise code context. Details back when you need them.</strong></p>
  <p>A local CLI and MCP server for AI coding agents, with an optional macOS desktop pet.</p>

  <a href="https://github.com/00200200/tokencut/actions/workflows/ci.yml"><img src="https://github.com/00200200/tokencut/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-b3f5cd" alt="MIT license"></a>
  <a href="https://github.com/00200200/tokencut/stargazers"><img src="https://img.shields.io/github/stars/00200200/tokencut?style=flat&color=b3f5cd" alt="GitHub stars"></a>

  <p><a href="#try-it-in-a-minute">Try it</a> · <a href="#connect-your-agent">Connect your agent</a> · <a href="#meet-your-desktop-companion">Meet the pet</a> · <a href="docs/guide.md">Guide</a></p>
</div>

## Try it in a minute

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/getting-started/installation/).

```sh
uv tool install 'git+https://github.com/00200200/tokencut.git'
tokencut demo
```

**Install from this GitHub repository:** the PyPI package named `tokencut` is a different project.

The demo runs anywhere, makes **no model calls**, and checks that the complete failure
is preserved, the original can be recovered, and unknown output stays unchanged.

| Built-in pytest fixture | Tokens |
| --- | ---: |
| Original output | 1,562 |
| TokenCut output, including recovery notice | **174** |

**88.9% less tool text on this authored fixture.** Reproduce it with `tokencut demo --json`.
This is a local tokenizer estimate, not a claim about billing, task quality, or subscription limits.

Try it on a real command:

```sh
tokencut run -- pytest -v
```

## What you get

- **Useful output, recoverable detail.** Fold recognized noise, keep diagnostics, and retrieve omitted text by reference.
- **Code without whole-file dumps.** Search symbols, read exact methods, inspect outlines, and preview edits guarded by a file hash. Syntax indexing runs locally, without language-server daemons.
- **Context you choose.** Package selected files, compact pasted logs or tables, and save short task checkpoints. Transcript distillation is explicit and lossy; it does not intercept chat.
- **Visible measurements.** Inspect before/after text counts and recovery overhead. Available account-limit readings stay separate from estimated text savings.

Default command filtering preserves unfamiliar output. Stronger truncation is opt-in.
Reference resolution uses syntax, not full LSP semantics. [Details and tradeoffs →](docs/guide.md)

### Before you send a message

Open **Prepare for chat** from the macOS pet or dashboard. Paste a log or a supplied
transcript, compare both versions, and copy the preview into **Codex, Claude Desktop
or a CLI chat**. No model calls. Conservative filtering is the default; conversation
summaries are an explicit, lossy option. The same flow works in the terminal:

```sh
tokencut prepare --file draft.txt
```

## Connect your agent

Use the **coding profile** for everyday development: 8 core tools instead of 14,
with **about 37% smaller tool schemas** in the current local `o200k_base` measurement
(2,881 → 1,816 tokens). Tool loading varies by client; this is not a per-turn usage guarantee.

```sh
# Claude Code
claude mcp add --scope user tokencut -- tokencut mcp --profile coding

# Codex
codex mcp add tokencut -- tokencut mcp --profile coding
```

Already registered? Update the existing server's arguments, then reconnect.
For Claude Desktop, Cursor, Windsurf and other MCP clients, merge this server entry:

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

Get the binary path with `command -v tokencut`. Use `--profile full` for all MCP tools;
all CLI commands remain available in either profile. In Codex, use `tokencut run`
inside its native terminal for commands that need its sandbox and approval flow.

[Client setup, optional hooks and task memory →](docs/guide.md#connect-clients)

## Meet your desktop companion

Our mint robot lives in a draggable macOS pet, or hides in the menu bar when you
want a quiet desktop. Open it for tool-output measurements, recovery costs, task
memory and available account-limit readings. English UI. Local storage. No extra AI calls.

![The actual native macOS Prepare for chat window, comparing an authored conversation with a locally prepared summary.](assets/macos-conversation.png)

*Actual macOS app with an authored transcript fixture. Compare before copying;
preview counts are not recorded savings. [Log preparation screenshot →](assets/macos-prepare.png)*

<p align="center"><img src="assets/macos-pet.png" width="310" alt="The actual draggable TokenCut pet and HUD, shown without account readings."></p>

The animation above features the app's bundled artwork. The app uses subtle hover
motion, not a continuously running 3D renderer. The CLI and MCP do not require the pet.

**macOS 13+ · local preview · ad-hoc signed, not notarized.**
[Build the companion →](docs/guide.md#macos-companion)

## Make it better with us

**If TokenCut earns a place in your workflow, [give it a star](https://github.com/00200200/tokencut/stargazers).**
It helps other developers discover the project. Found lost context or a missed
optimization? [Open an issue](https://github.com/00200200/tokencut/issues/new) with
a small, redacted example and the output you expected.

[Guide](docs/guide.md) · [Reproducible benchmarks](docs/guide.md#measurements-and-development) · [MIT license](LICENSE)
