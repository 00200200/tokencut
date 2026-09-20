# tokencut — Launch & Promotion Strategy (Star-Magnet Playbook)

Here are the ready-to-post announcements crafted to drive maximum traction, Reddit upvotes, and GitHub stars.

---

## 1. Reddit: `r/ClaudeAI` (Target: Claude Code Rate Limits)

**Title:**
> I got tired of Claude Code hitting the 5-hour rate limit in 45 minutes, so I built an open-source context compactor (and MCP server) that cuts token burn by 80% without losing error tracebacks.

**Post Body:**
```markdown
Hey everyone,

Like many of you using **Claude Code** and Cursor on active dev projects, I kept hitting the dreaded **5-hour wall** within 45–60 minutes of starting work.

The root cause isn’t Claude itself—it’s **tool output bloat**:
1. Running `pytest`, `npm test`, or `cargo build` dumps thousands of lines of ANSI color escapes, progress bars, and routine passes.
2. Because multi-turn agents resend previous tool outputs on **every single prompt**, that 4,000-token test run in turn 2 gets billed 25 times by turn 25 (100,000+ ghost tokens!).
3. A single change to `uv.lock` or `package-lock.json` dumps 10,000 lines into your context window.

I built **tokencut** — an open-source CLI and universal MCP server designed to solve this with **Zero Quality Loss**:

### What it does:
- **Semantic Error & Traceback Preserver:** Scans output for `Traceback`, `FAILURES`, `AssertionError`, `panic:`, and keeps 100% of the error and stack frames while omitting the bloated repetitive build steps.
- **100% Reversible CCR Architecture:** Every omitted log is cached locally in SQLite. The truncated notice includes a `[ref: tc_xxxx]` tag. If Claude ever needs the omitted lines, it can retrieve them on demand via MCP!
- **Repository Token Tree (`tokencut tree`):** Scans your repo and shows exactly which files are hogging tokens (we caught `uv.lock` taking 148,000 tokens / 87% of a repo!).
- **AST Skeletonizer:** Inspects Python, TS/JS, Go, and Rust signatures without dumping thousands of implementation lines.
- **Secret Sanitizer:** Automatically scrubs OpenAI, Anthropic, Gemini, and GitHub API keys from model history.

### Real Benchmark on our suite:
- Pytest (120 tests, 1 fail): 2,108 tokens -> 441 tokens (**-79.1%**)
- Vite / Webpack build: 4,272 tokens -> 1,012 tokens (**-76.3%**)
- Git diff with lockfile: 4,165 tokens -> 101 tokens (**-97.6%**)

### Quickstart (Zero Install via uvx):
```bash
# In Claude Code:
claude mcp add tokencut uvx tokencut mcp

# In terminal:
uvx tokencut run -- pytest -v tests/
uvx tokencut tree .
```

GitHub: https://github.com/00200200/tokencut

It’s 100% open source (MIT), zero telemetry, local-first. Would love your feedback and feature requests!
```

---

## 2. Reddit: `r/Cursor` & `r/LocalLLaMA`

**Title:**
> We built tokencut: An open-source tool + MCP that stops AI coding agents from burning 150k tokens on lockfiles, test logs, and whole-file dumps

**Post Body:**
```markdown
AI coding agents are amazing until they read a lockfile or run a test suite, blowing 30% of your context window and causing the model to get "lost in the middle".

We built **tokencut** to solve this at the root. It acts as both a CLI wrapper and an MCP server that compresses tool outputs and file reads by 60–85%:

Key features:
- **Compress-Cache-Retrieve (CCR):** Never worry about aggressive truncation. Every omitted block gets an ID you or the agent can retrieve on demand.
- **AST Skeletons:** Inspect architecture outlines (`tokencut cat src/core.py -s`) with methods replaced by `...`.
- **Lockfile Slimmer:** Automatically folds `package-lock.json` and `uv.lock` in git diffs (-97% tokens).
- **Prompt Cache Protector:** Lints `CLAUDE.md` and `.cursorrules` for cache-busting dynamic timestamps.

Run without installing:
`uvx tokencut demo`

Repo: https://github.com/00200200/tokencut (⭐ Star if it saves you tokens!)
```

---

## 3. Hacker News: Show HN

**Title:**
> Show HN: Tokencut – Context compression engine and MCP for AI coding agents

**Text:**
```text
Hey HN,

When developing with agentic coding CLI tools (Claude Code, Cursor, Codex, Gemini CLI), context windows burn out quickly due to the quadratic accumulation of tool outputs.

A test suite that outputs 2,000 tokens of passing test names will be resent on every conversation turn, burning tens of thousands of tokens and degrading reasoning performance.

Tokencut (MIT licensed, Python 3.11+, uv) is an open-source tool and stdio MCP server that implements:
1. Reversible Compress-Cache-Retrieve (CCR): Raw outputs are stored in a local SQLite cache. Compressed outputs include reference markers (e.g. `Ref: tc_8f2a1b`) allowing the model or user to retrieve any slice of raw text if needed.
2. Error-Preserving Log Sanitization: Detects tracebacks, assertion errors, and panics; isolates failing frames and compresses routine progress output.
3. Code Skeletonization: Uses Python AST and tree parsers to extract signatures and docstrings, eliding method bodies with `...`.
4. Lockfile & Diff Folding: Suppresses generated files and lockfiles in git diffs (-97.6% tokens).
5. Token Tree Scanner: Visualizes directory-level token weight to pinpoint context hogs.

Benchmarks across real workloads demonstrate 60%–85% token reduction with zero loss of traceback accuracy.

Repo: https://github.com/00200200/tokencut
Quick demo: `uvx tokencut demo`

Happy to answer any technical questions about the architecture!
```

---

## 4. X (Twitter) Thread

**Tweet 1 (Hook):**
> Claude Code and Cursor burning through your 5-hour rate limits in 45 minutes?
> 
> The problem isn’t the AI—it’s tool output bloat. 
> 
> We built tokencut: an open-source context compactor & MCP server that cuts token burn by 60–85% with ZERO quality loss. 🧵👇
> [Attach assets/demo.svg or GIF]

**Tweet 2:**
> Why do tokens burn so fast?
> In multi-turn chat, previous bash outputs are resent on EVERY prompt.
> 
> A single 3,000-token `pytest` or `npm test` run at turn 2 gets resent 25 times = 75,000 tokens wasted on routine logs!

**Tweet 3:**
> tokencut preserves 100% of errors & tracebacks, but squashes the repetitive passing noise into a clean 1-liner.
> 
> Plus: 100% Reversible. Every omitted line is cached in SQLite and can be retrieved by the model anytime using a ref ID (`tc_xxxx`).

**Tweet 4:**
> Real benchmarks:
> 📊 Pytest Suite: 2,108 ➔ 441 tokens (-79%)
> 📊 Webpack Build: 4,272 ➔ 1,012 tokens (-76%)
> 📊 Git Diff with lockfiles: 4,165 ➔ 101 tokens (-97%)

**Tweet 5 (CTA):**
> Add to Claude Code in 5 seconds:
> `claude mcp add tokencut uvx tokencut mcp`
> 
> 🌟 100% Open Source (MIT):
> https://github.com/00200200/tokencut
```
