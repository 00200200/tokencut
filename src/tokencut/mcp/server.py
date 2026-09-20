from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from tokencut.core.adaptive import compress_to_budget
from tokencut.core.cache import ContextCache
from tokencut.core.cleaner import CleanerOptions, compact_terminal_output
from tokencut.core.diff_slimmer import slim_git_diff
from tokencut.core.json_slimmer import slim_json
from tokencut.core.skeleton import extract_symbol_or_range
from tokencut.core.tree_scanner import format_tree_as_text, scan_directory
from tokencut.metrics.pricing import estimate_savings
from tokencut.metrics.tokenizer import count_tokens

# Global session metrics accumulator
_SESSION_SAVED_CLAUDE = 0
_SESSION_SAVED_OPENAI = 0
_SESSION_SAVED_GEMINI = 0


TOOLS_DEFINITIONS = [
    {
        "name": "tokencut_exec",
        "description": "Execute a shell command with intelligent token compaction. Strips ANSI colors, scrubs API keys, deduplicates repetitive logs, preserves full stack traces/errors, and stores full output in local cache for 100% reversible retrieval.",
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
                "budget": {
                    "type": "integer",
                    "description": "Optional strict token ceiling budget (e.g. 500).",
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
        "name": "tokencut_retrieve",
        "description": "Retrieve exact raw lines from a previously compressed log or file using its ref ID (e.g. 'tc_8f2a1b'). Guarantees zero context loss.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ref_id": {
                    "type": "string",
                    "description": "The ref ID returned by tokencut in a truncated log notice.",
                },
                "lines": {
                    "type": "string",
                    "description": "Optional specific line range to retrieve (e.g. '40-100').",
                },
            },
            "required": ["ref_id"],
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
        "name": "tokencut_tree",
        "description": "Analyze directory token distribution and locate oversized files/directories (e.g. lockfiles, test fixtures) that consume disproportionate context.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Root directory to scan (default '.').",
                    "default": ".",
                },
                "max_depth": {
                    "type": "integer",
                    "description": "Maximum folder depth (default 3).",
                    "default": 3,
                },
            },
        },
    },
    {
        "name": "tokencut_json",
        "description": "Compact large JSON strings or files by folding repetitive arrays and truncating long strings. Retains complete schema while eliminating 80-95% of token burn. Full uncompressed data is cached in SQLite and can be retrieved via ref ID.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "json_str": {
                    "type": "string",
                    "description": "Raw JSON string to compact.",
                },
                "path": {
                    "type": "string",
                    "description": "Optional file path containing JSON to compact.",
                },
                "max_items": {
                    "type": "integer",
                    "description": "Maximum array items to keep per list (default 3).",
                    "default": 3,
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
    budget = arguments.get("budget")

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
            combined_raw += ("\n" if combined_raw else "") + proc.stderr
    except Exception as e:
        return f"Error executing command: {e}"

    cache = ContextCache()
    dup_ref = cache.check_duplicate(combined_raw)

    # Check if output is large JSON (> 400 chars)
    trimmed = combined_raw.strip()
    if (trimmed.startswith("{") and trimmed.endswith("}")) or (
        trimmed.startswith("[") and trimmed.endswith("]")
    ):
        if len(trimmed) > 400:
            compacted = slim_json(trimmed, max_array_items=3)
        else:
            compacted = trimmed
    elif budget:
        compacted = compress_to_budget(combined_raw, max_tokens=budget, source=command)
    else:
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
    idempotent_tag = f" [idempotent: match {dup_ref}]" if dup_ref else ""
    footer = f"\n\n[tokencut: saved ~{raw_tokens.avg - comp_tokens.avg} tokens (-{pct}%){idempotent_tag}, exit code: {proc.returncode}]"
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


def handle_tokencut_retrieve(arguments: dict[str, Any]) -> str:
    ref_id = arguments["ref_id"]
    lines = arguments.get("lines")
    cache = ContextCache()
    return cache.retrieve(ref_id, lines_range=lines)


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


def handle_tokencut_tree(arguments: dict[str, Any]) -> str:
    path_str = arguments.get("path", ".")
    max_depth = arguments.get("max_depth", 3)
    target = Path(path_str).resolve()
    if not target.exists():
        return f"Path does not exist: {path_str}"

    root_node, _ = scan_directory(target, max_depth=max_depth)
    return format_tree_as_text(root_node, root_node.tokens)


def handle_tokencut_json(arguments: dict[str, Any]) -> str:
    raw_str = arguments.get("json_str")
    path_str = arguments.get("path")
    if path_str:
        try:
            raw_str = Path(path_str).read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return f"Error reading file {path_str}: {e}"

    if not raw_str:
        return "Error: either json_str or path must be provided."

    max_items = arguments.get("max_items", 3)
    return slim_json(raw_str, max_array_items=max_items)


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
            elif tool_name == "tokencut_retrieve":
                res_text = handle_tokencut_retrieve(arguments)
            elif tool_name == "tokencut_diff":
                res_text = handle_tokencut_diff(arguments)
            elif tool_name == "tokencut_tree":
                res_text = handle_tokencut_tree(arguments)
            elif tool_name == "tokencut_json":
                res_text = handle_tokencut_json(arguments)
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
