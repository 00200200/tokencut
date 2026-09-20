from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from tokencut.core.cleaner import CleanerOptions, compact_terminal_output
from tokencut.core.diff_slimmer import slim_git_diff
from tokencut.core.skeleton import extract_symbol_or_range
from tokencut.metrics.pricing import estimate_savings
from tokencut.metrics.tokenizer import count_tokens

# Global session metrics accumulator
_SESSION_SAVED_CLAUDE = 0
_SESSION_SAVED_OPENAI = 0
_SESSION_SAVED_GEMINI = 0


TOOLS_DEFINITIONS = [
    {
        "name": "tokencut_exec",
        "description": "Execute a shell command with intelligent token compaction. Strips ANSI colors, deduplicates repetitive logs, preserves full stack traces/errors, and cuts token burn by 70-85%.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute.",
                },
                "max_lines": {
                    "type": "integer",
                    "description": "Maximum number of lines to retain before truncation (default 80).",
                    "default": 80,
                },
            },
            "required": ["command"],
        },
    },
    {
        "name": "tokencut_read",
        "description": "Read file contents with token optimization. Supports skeleton/AST mode (signatures, docstrings, classes) or targeted symbol/line extraction to avoid dumping thousands of unnecessary tokens into context.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file to read.",
                },
                "skeleton": {
                    "type": "boolean",
                    "description": "If true, extracts structural outline/AST (functions, classes, types) eliding method bodies.",
                    "default": False,
                },
                "lines": {
                    "type": "string",
                    "description": "Specific line range to read (e.g. '10-45').",
                },
                "symbol": {
                    "type": "string",
                    "description": "Specific symbol name (function, class, interface) to inspect.",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "tokencut_diff",
        "description": "Get git diff with automatic lockfile suppression and context-line compaction. Prevents lockfiles (package-lock, uv.lock) from exploding context windows.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "staged": {
                    "type": "boolean",
                    "description": "If true, view staged changes (--cached).",
                    "default": False,
                },
            },
        },
    },
    {
        "name": "tokencut_stats",
        "description": "Get session telemetry: total tokens saved across Claude, OpenAI, Gemini and estimated cost savings in USD.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
]


def handle_tokencut_exec(arguments: dict[str, Any]) -> str:
    global _SESSION_SAVED_CLAUDE, _SESSION_SAVED_OPENAI, _SESSION_SAVED_GEMINI
    command = arguments["command"]
    max_lines = arguments.get("max_lines", 80)

    try:
        proc = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
        combined_raw = proc.stdout
        if proc.stderr:
            combined_raw += "\n" + proc.stderr
    except Exception as e:
        return f"Error executing command: {e}"

    opts = CleanerOptions(max_lines=max_lines)
    compacted = compact_terminal_output(combined_raw, opts)

    raw_tokens = count_tokens(combined_raw)
    comp_tokens = count_tokens(compacted)

    saved_claude = max(0, raw_tokens.claude - comp_tokens.claude)
    saved_openai = max(0, raw_tokens.openai - comp_tokens.openai)
    saved_gemini = max(0, raw_tokens.gemini - comp_tokens.gemini)

    _SESSION_SAVED_CLAUDE += saved_claude
    _SESSION_SAVED_OPENAI += saved_openai
    _SESSION_SAVED_GEMINI += saved_gemini

    pct = (
        round(((raw_tokens.avg - comp_tokens.avg) / raw_tokens.avg * 100), 1)
        if raw_tokens.avg > 0
        else 0.0
    )
    footer = f"\n\n[tokencut: saved ~{raw_tokens.avg - comp_tokens.avg} tokens (-{pct}%), exit code: {proc.returncode}]"
    return compacted + footer


def handle_tokencut_read(arguments: dict[str, Any]) -> str:
    global _SESSION_SAVED_CLAUDE, _SESSION_SAVED_OPENAI, _SESSION_SAVED_GEMINI
    path = arguments["path"]
    skeleton = arguments.get("skeleton", False)
    lines = arguments.get("lines")
    symbol = arguments.get("symbol")

    try:
        full_content = Path(path).read_text(encoding="utf-8", errors="replace")
        extracted = extract_symbol_or_range(
            path, symbol=symbol, lines_range=lines, skeleton=skeleton
        )

        raw_tok = count_tokens(full_content)
        comp_tok = count_tokens(extracted)

        _SESSION_SAVED_CLAUDE += max(0, raw_tok.claude - comp_tok.claude)
        _SESSION_SAVED_OPENAI += max(0, raw_tok.openai - comp_tok.openai)
        _SESSION_SAVED_GEMINI += max(0, raw_tok.gemini - comp_tok.gemini)

        return extracted
    except Exception as e:
        return f"Error reading file: {e}"


def handle_tokencut_diff(arguments: dict[str, Any]) -> str:
    global _SESSION_SAVED_CLAUDE, _SESSION_SAVED_OPENAI, _SESSION_SAVED_GEMINI
    staged = arguments.get("staged", False)
    cmd = "git diff --cached" if staged else "git diff"
    try:
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        raw_diff = res.stdout
        slimmed = slim_git_diff(raw_diff)

        raw_tok = count_tokens(raw_diff)
        comp_tok = count_tokens(slimmed)

        _SESSION_SAVED_CLAUDE += max(0, raw_tok.claude - comp_tok.claude)
        _SESSION_SAVED_OPENAI += max(0, raw_tok.openai - comp_tok.openai)
        _SESSION_SAVED_GEMINI += max(0, raw_tok.gemini - comp_tok.gemini)

        return slimmed or "No git changes detected."
    except Exception as e:
        return f"Error generating diff: {e}"


def handle_tokencut_stats() -> str:
    savings = estimate_savings(_SESSION_SAVED_CLAUDE, _SESSION_SAVED_OPENAI, _SESSION_SAVED_GEMINI)
    return (
        f"tokencut Session Savings:\n"
        f"- Claude Tokens Saved: {_SESSION_SAVED_CLAUDE:,}\n"
        f"- OpenAI Tokens Saved: {_SESSION_SAVED_OPENAI:,}\n"
        f"- Gemini Tokens Saved: {_SESSION_SAVED_GEMINI:,}\n"
        f"- Estimated Cost Saved: {savings.format_avg()} USD\n"
    )


def run_mcp_stdio_server():
    """Run JSON-RPC 2.0 stdio loop for Model Context Protocol."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue

        req_id = req.get("id")
        method = req.get("method")
        params = req.get("params", {})

        if method == "initialize":
            resp = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "tokencut", "version": "0.1.0"},
                },
            }
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()

        elif method == "notifications/initialized":
            pass

        elif method == "tools/list":
            resp = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"tools": TOOLS_DEFINITIONS},
            }
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()

        elif method == "tools/call":
            tool_name = params.get("name")
            arguments = params.get("arguments", {})

            if tool_name == "tokencut_exec":
                res_text = handle_tokencut_exec(arguments)
            elif tool_name == "tokencut_read":
                res_text = handle_tokencut_read(arguments)
            elif tool_name == "tokencut_diff":
                res_text = handle_tokencut_diff(arguments)
            elif tool_name == "tokencut_stats":
                res_text = handle_tokencut_stats()
            else:
                res_text = f"Unknown tool: {tool_name}"

            resp = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": res_text}],
                },
            }
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()

        elif method == "ping":
            resp = {"jsonrpc": "2.0", "id": req_id, "result": {}}
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()
