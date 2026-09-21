from __future__ import annotations

import json
import subprocess
import sys
import time
from contextvars import ContextVar
from functools import wraps
from pathlib import Path
from typing import Any

from tokencut.core.adaptive import compress_to_budget
from tokencut.core.cache import ContextCache
from tokencut.core.cleaner import CleanerOptions, compact_terminal_output
from tokencut.core.companion_state import already_wrapped, client_name, paused
from tokencut.core.diff_slimmer import slim_git_diff
from tokencut.core.json_slimmer import slim_json
from tokencut.core.redactor import redact_secrets
from tokencut.core.safe_filter import safe_compact_output
from tokencut.core.skeleton import extract_symbol_or_range
from tokencut.core.telemetry import record_text, recovery_engine
from tokencut.core.tree_scanner import format_tree_as_text, scan_directory
from tokencut.metrics.tokenizer import count_tokens

# Global session metrics accumulator
_SESSION_SAVED_CLAUDE = 0
_SESSION_SAVED_OPENAI = 0
_SESSION_SAVED_GEMINI = 0


TOOLS_DEFINITIONS = [
    {
        "name": "tokencut_context",
        "description": "Save/read/list/forget bounded task checkpoints. Use the root/task from the session hook; save at milestones, not every turn. expected_revision=0 creates, otherwise use the last read revision. Never stores transcripts or calls AI. Notes are fallible data; current user instructions win.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["save", "read", "list", "forget"]},
                "root": {
                    "type": "string",
                    "description": "Absolute directory; tasks are isolated by directory and ID.",
                },
                "task": {
                    "type": "string",
                    "description": "Session-specific task ID from the hook, or an explicit separate task ID.",
                },
                "expected_revision": {"type": "integer"},
                "revision": {
                    "type": "integer",
                    "description": "Read a retained earlier revision; default latest.",
                },
                "checkpoint": {
                    "type": "object",
                    "properties": {
                        "goal": {"type": "string"},
                        **{
                            field: {"type": "array", "items": {"type": "string"}}
                            for field in (
                                "constraints",
                                "decisions",
                                "progress",
                                "next_steps",
                                "references",
                            )
                        },
                    },
                    "required": ["goal"],
                    "additionalProperties": False,
                },
            },
            "required": ["action", "root"],
        },
    },
    {
        "name": "tokencut_code",
        "description": "Search a local syntax index or get a ranked repo map. Use symbols for definitions, occurrences for raw matches, outline for module hierarchy, references or callers to find symbol callers across project (0 LSP daemons), search for text, pattern for ast-grep patterns. Then read with tokencut_read or edit with tokencut_edit_symbol.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "root": {
                    "type": "string",
                    "description": "Absolute project directory; respects Git ignores.",
                },
                "mode": {
                    "type": "string",
                    "enum": [
                        "map",
                        "symbols",
                        "occurrences",
                        "search",
                        "pattern",
                        "outline",
                        "references",
                        "callers",
                    ],
                },
                "query": {"type": "string"},
                "file": {"type": "string", "description": "Optional file relative to root."},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 30},
            },
            "required": ["root"],
        },
    },
    {
        "name": "tokencut_edit_symbol",
        "description": "Precisely replace a class, function, or method declaration in an absolute source file by symbol selector, with diff preview and hash-guarded atomic updates. Replaces heavyweight LSP tools.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute source file path.",
                },
                "selector": {
                    "type": "string",
                    "description": "Qualified symbol name, e.g. 'Class.method' or 'function_name', optionally '@line'.",
                },
                "replacement": {
                    "type": "string",
                    "description": "New source text for the symbol declaration and body.",
                },
                "expected_hash": {
                    "type": "string",
                    "description": "SHA-256 digest of the entire file prior to modification (returned by tokencut_read).",
                },
                "apply": {
                    "type": "boolean",
                    "description": "Set true to write the modification to disk atomically; false (default) returns a unified diff preview.",
                    "default": False,
                },
            },
            "required": ["path", "selector", "replacement", "expected_hash"],
        },
    },
    {
        "name": "tokencut_exec",
        "description": "Run a noninteractive shell command with conservative log filtering and exit status. Set max_tokens only to opt into truncation; shortened output has a recovery ref.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute.",
                },
                "max_lines": {
                    "type": "integer",
                    "description": "Opt into truncation with this line limit. Omit to preserve diagnostics and unknown output.",
                },
                "budget": {
                    "type": "integer",
                    "description": "Compatibility alias for max_tokens; explicitly permits truncation.",
                },
            },
            "required": ["command"],
        },
    },
    {
        "name": "tokencut_read",
        "description": "Read a file, outline, symbol, or line range with bounded output. Prefer targeted reads.",
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
                    "description": "Exact qualified name, e.g. Cache.get, optionally @line for ambiguity. Returns original source and file hash.",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "tokencut_retrieve",
        "description": "Recover redacted cached output by ref. Specify lines or query to return only relevant chunks; every recovery is charged as added context.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search words in this cached output; cannot combine with lines.",
                },
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
        "description": "Summarize git diff, folding lockfiles and generated files. Recover omitted changes by ref before reviewing them.",
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
        "description": "Preview JSON arrays, strings and nested data with bounded output. Omitted values and schema variants must be recovered from the redacted cache before relying on them.",
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
        "name": "tokencut_clip",
        "description": "Compact noisy text, logs, diffs, JSON, or stack traces with secret redaction and CCR recovery caching before pasting or sending in context.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "The raw noisy text to compact.",
                },
                "budget": {
                    "type": "integer",
                    "minimum": 64,
                    "maximum": 32000,
                    "default": 2000,
                    "description": "Target token budget ceiling for compacted output.",
                },
            },
            "required": ["text"],
        },
    },
    {
        "name": "tokencut_pack",
        "description": "Pack multiple source files or directories into an AI-optimized prompt bundle with AST skeletonization, secret scrubbing, and token budget management.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "root": {
                    "type": "string",
                    "description": "Absolute project root directory.",
                },
                "paths": {
                    "type": "array",
                    "description": "List of relative or absolute file/directory paths to bundle.",
                },
                "budget": {
                    "type": "integer",
                    "minimum": 100,
                    "maximum": 64000,
                    "default": 4000,
                    "description": "Token budget ceiling across all packed files.",
                },
                "skeleton": {
                    "type": "boolean",
                    "description": "If true, force AST structural skeletons for all code files.",
                    "default": False,
                },
            },
            "required": ["root"],
        },
    },
    {
        "name": "tokencut_distill",
        "description": "Distill multi-turn chat transcripts or session histories into dense executive context (goals, decisions, modified files, active state) with zero loss CCR recovery.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "transcript": {
                    "type": "string",
                    "description": "Raw multi-turn conversation text or transcript.",
                },
                "budget": {
                    "type": "integer",
                    "minimum": 100,
                    "maximum": 32000,
                    "default": 1500,
                    "description": "Target token budget ceiling for distilled context.",
                },
            },
            "required": ["transcript"],
        },
    },
    {
        "name": "tokencut_table",
        "description": "Compress JSON arrays of objects, CSV, or TSV data into compact TOON (Token-Optimized Object Notation) or Markdown table, eliminating repeated key bloat by 60-75%.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "data": {
                    "type": "string",
                    "description": "Raw JSON object array, CSV, or TSV string.",
                },
                "budget": {
                    "type": "integer",
                    "minimum": 100,
                    "maximum": 32000,
                    "default": 2000,
                    "description": "Target token budget ceiling.",
                },
                "format": {
                    "type": "string",
                    "enum": ["toon", "markdown"],
                    "default": "toon",
                    "description": "Output format: 'toon' (dense delimited) or 'markdown' table.",
                },
            },
            "required": ["data"],
        },
    },
    {
        "name": "tokencut_optimize",
        "description": "Unified autonomous context optimizer. Self-routes prompts, intra-fence code blocks (JSON -> TOON, diffs -> slim), conversation transcripts, and noisy logs with secret redaction and 0-loss CCR guarantee.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The raw prompt, code, log, table, or conversation content to optimize.",
                },
                "budget": {
                    "type": "integer",
                    "minimum": 64,
                    "maximum": 64000,
                    "default": 2000,
                    "description": "Target token budget ceiling for optimized context.",
                },
            },
            "required": ["content"],
        },
    },
    {
        "name": "tokencut_stats",
        "description": "Report estimated net output reduction, including footers and retrievals. Not model billing or subscription quota.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
]

for _tool in TOOLS_DEFINITIONS:
    _tool["annotations"] = {
        "readOnlyHint": _tool["name"]
        not in {"tokencut_exec", "tokencut_context", "tokencut_edit_symbol"},
        "destructiveHint": _tool["name"]
        in {"tokencut_exec", "tokencut_context", "tokencut_edit_symbol"},
    }
    if _tool["name"] not in {
        "tokencut_stats",
        "tokencut_context",
        "tokencut_edit_symbol",
        "tokencut_clip",
        "tokencut_pack",
        "tokencut_distill",
        "tokencut_table",
        "tokencut_optimize",
    }:
        _tool["inputSchema"]["properties"]["max_tokens"] = {
            "type": "integer",
            "minimum": 64,
            "maximum": 32000,
            "default": 2000,
            "description": "Complete text budget using the local Claude estimate, including refs and exit status.",
        }
    if _tool["name"] in {"tokencut_exec", "tokencut_diff"}:
        _tool["inputSchema"]["properties"]["cwd"] = {
            "type": "string",
            "description": "Absolute working directory. Set explicitly for the target project.",
        }
    if _tool["name"] == "tokencut_exec":
        _tool["inputSchema"]["properties"]["max_tokens"].pop("default")
        _tool["inputSchema"]["properties"]["max_tokens"]["description"] = (
            "Opt into truncation with this complete text budget (local estimate). "
            "Omit to preserve diagnostics and unknown output."
        )


CODING_TOOLS = frozenset(
    {
        "tokencut_code",
        "tokencut_edit_symbol",
        "tokencut_exec",
        "tokencut_read",
        "tokencut_retrieve",
        "tokencut_context",
        "tokencut_diff",
        "tokencut_stats",
    }
)


def tool_definitions(profile: str = "full") -> list[dict]:
    """Keep optional transforms out of coding sessions without changing the default API."""
    if profile not in {"full", "coding"}:
        raise ValueError("MCP profile must be full or coding")
    return [tool for tool in TOOLS_DEFINITIONS if profile == "full" or tool["name"] in CODING_TOOLS]


def server_instructions(profile: str) -> str:
    extra = (
        "Use tokencut_optimize for unified autonomous prompt, code block, table, transcript, and log optimization; "
        "tokencut_pack for file bundles, tokencut_clip for pasted logs, "
        "tokencut_distill for supplied transcripts, and tokencut_table for tables. "
        if profile == "full"
        else "Optional text transforms remain available through the CLI. "
    )
    return (
        "Use tokencut_code for syntax searches; tokencut_read for exact symbols or ranges; "
        "tokencut_edit_symbol for hash-guarded edits; tokencut_context for milestone checkpoints. "
        + extra
        + "Use tokencut_exec for verbose noninteractive commands with an absolute cwd. "
        "In Codex prefer tokencut run inside the native shell to retain its sandbox and approvals. "
        "Omit max_tokens/max_lines to preserve command diagnostics; explicit limits permit truncation. "
        "Recover needed details with tokencut_retrieve. Do not rerun successful commands just to compress output. "
        "Keep normal approvals. This server does not intercept chat or change account quotas."
    )


def _budget(arguments: dict[str, Any]) -> int:
    value = arguments.get("max_tokens", arguments.get("budget", 2000))
    if type(value) is not int or not 64 <= value <= 32000:
        raise ValueError("max_tokens must be an integer between 64 and 32000")
    return value


_START: ContextVar[float | None] = ContextVar("tokencut_started", default=None)


def _timed(handler):
    @wraps(handler)
    def wrapped(arguments):
        token = _START.set(time.perf_counter())
        try:
            return handler(arguments)
        finally:
            _START.reset(token)

    return wrapped


def _record(raw: str, output: str, *, operation="exec", project=None, duration_s=None) -> str:
    global _SESSION_SAVED_CLAUDE, _SESSION_SAVED_OPENAI, _SESSION_SAVED_GEMINI
    before, after = count_tokens(raw), count_tokens(output)
    # Signed deltas expose expansion and charge subsequent retrievals in full.
    _SESSION_SAVED_CLAUDE += before.claude - after.claude
    _SESSION_SAVED_OPENAI += before.openai - after.openai
    _SESSION_SAVED_GEMINI += before.gemini - after.gemini
    if duration_s is None and _START.get() is not None:
        duration_s = time.perf_counter() - _START.get()
    record_text(
        raw,
        output,
        operation=operation,
        project=project,
        duration_s=duration_s,
        client=client_name("mcp"),
        engine="none" if paused() else "tokencut",
    )
    return output


def _compress(text, budget, **kwargs):
    if paused():
        return kwargs.get("original_text", text) + kwargs.get("suffix", "")
    return compress_to_budget(text, budget, **kwargs)


def _cwd(arguments: dict[str, Any]) -> str | None:
    cwd = arguments.get("cwd")
    if cwd is not None and (not isinstance(cwd, str) or not Path(cwd).is_absolute()):
        raise ValueError("cwd must be an absolute directory path")
    return cwd


@_timed
def handle_tokencut_code(arguments: dict[str, Any]) -> str:
    from tokencut.core.code_index import CodeIndex

    budget = _budget(arguments)
    index = CodeIndex(arguments["root"])
    result = index.query(
        arguments.get("mode", "map"),
        arguments.get("query", ""),
        arguments.get("file"),
        arguments.get("limit", 30),
    )
    output = _compress(result, budget, source="code-query")
    return _record(result, output, operation="code", project=arguments["root"])


@_timed
def handle_tokencut_exec(arguments: dict[str, Any]) -> str:
    start = time.perf_counter()
    budget = _budget(arguments)
    command = arguments["command"]
    max_lines = arguments.get("max_lines", 80)
    if type(max_lines) is not int or not 1 <= max_lines <= 10000:
        raise ValueError("max_lines must be an integer between 1 and 10000")
    if not isinstance(command, str) or not command.strip():
        raise ValueError("command must be a nonempty string")
    try:
        proc = subprocess.run(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            timeout=120,
            cwd=_cwd(arguments),
        )
        combined_raw = proc.stdout
        footer = f"\n[exit code: {proc.returncode}]"
    except subprocess.TimeoutExpired as exc:
        combined_raw = exc.stdout or ""
        if isinstance(combined_raw, bytes):
            combined_raw = combined_raw.decode("utf-8", errors="replace")
        footer = "\n[command timed out after 120s; output may be partial]"

    if already_wrapped(command):
        return combined_raw + footer
    if paused():
        output = combined_raw + footer
    elif any(key in arguments for key in ("max_tokens", "max_lines", "budget")):
        opts = CleanerOptions(max_lines=max_lines, enable_cache=False)
        compacted = compact_terminal_output(combined_raw, opts)
        output = _compress(
            compacted,
            budget,
            original_text=combined_raw,
            suffix=footer,
            source="exec",
        )
    else:
        output = safe_compact_output(combined_raw, command=command) + footer
    return _record(
        combined_raw, output, project=_cwd(arguments), duration_s=time.perf_counter() - start
    )


@_timed
def handle_tokencut_read(arguments: dict[str, Any]) -> str:
    budget = _budget(arguments)
    path = arguments["path"]
    skeleton = arguments.get("skeleton", False)
    lines = arguments.get("lines")
    symbol = arguments.get("symbol")

    extracted = extract_symbol_or_range(path, symbol=symbol, lines_range=lines, skeleton=skeleton)
    output = _compress(extracted, budget, source="read")
    # Compare with the requested view, not an unrequested full-file read.
    return _record(extracted, output, operation="read", project=path)


@_timed
def handle_tokencut_retrieve(arguments: dict[str, Any]) -> str:
    budget = _budget(arguments)
    ref_id = arguments["ref_id"]
    lines = arguments.get("lines")
    cache = ContextCache()
    query = arguments.get("query")
    if query is not None and lines is not None:
        raise ValueError("Choose query or lines, not both")
    retrieved = (
        cache.search(ref_id, query)
        if query is not None
        else cache.retrieve(ref_id, lines_range=lines)
    )
    if retrieved.startswith("Error:"):
        return retrieved
    output = _compress(retrieved, budget, source="retrieve")
    if recovery_engine(ref_id) == "rtk":
        record_text("", output, operation="retrieve", client=client_name("mcp"), engine="rtk")
        return output
    return _record("", output, operation="retrieve")


@_timed
def handle_tokencut_diff(arguments: dict[str, Any]) -> str:
    budget = _budget(arguments)
    staged = arguments.get("staged", False)
    cmd = ["git", "diff", "--no-ext-diff", "--no-textconv", "--no-color"]
    if staged:
        cmd.append("--cached")
    res = subprocess.run(
        cmd, capture_output=True, text=True, errors="replace", timeout=30, cwd=_cwd(arguments)
    )
    if res.returncode:
        raise ValueError(f"git diff failed ({res.returncode}): {res.stderr[:500]}")
    raw_diff = res.stdout
    output = (
        _compress(
            slim_git_diff(raw_diff),
            budget,
            original_text=raw_diff,
            source="diff",
        )
        if raw_diff
        else "No git changes detected."
    )
    return _record(raw_diff, output, operation="diff", project=_cwd(arguments))


@_timed
def handle_tokencut_tree(arguments: dict[str, Any]) -> str:
    budget = _budget(arguments)
    path_str = arguments.get("path", ".")
    max_depth = arguments.get("max_depth", 3)
    if type(max_depth) is not int or not 0 <= max_depth <= 64:
        raise ValueError("max_depth must be an integer between 0 and 64")
    target = Path(path_str).resolve()
    if not target.exists():
        raise ValueError(f"Path does not exist: {path_str}")

    root_node, _ = scan_directory(target, max_depth=max_depth)
    raw = format_tree_as_text(root_node, root_node.tokens)
    return _record(raw, _compress(raw, budget, source="tree"), operation="tree", project=target)


@_timed
def handle_tokencut_json(arguments: dict[str, Any]) -> str:
    budget = _budget(arguments)
    max_items = arguments.get("max_items", 3)
    if type(max_items) is not int or max_items < 0:
        raise ValueError("max_items must be a nonnegative integer")
    raw_str = arguments.get("json_str")
    path_str = arguments.get("path")
    if path_str:
        raw_str = Path(path_str).read_text(encoding="utf-8", errors="replace")

    if not raw_str:
        return "Error: either json_str or path must be provided."

    preview = slim_json(raw_str, max_array_items=max_items, cache_full=False)
    output = _compress(preview, budget, original_text=raw_str, source="json")
    return _record(raw_str, output, operation="json", project=path_str)


def handle_tokencut_stats() -> str:
    return (
        f"tokencut Session Savings:\n"
        f"Estimated net text reduction (negative means overhead):\n"
        f"- Claude heuristic: {_SESSION_SAVED_CLAUDE:,}\n"
        f"- OpenAI o200k estimate: {_SESSION_SAVED_OPENAI:,}\n"
        f"- Gemini heuristic: {_SESSION_SAVED_GEMINI:,}\n"
        "Includes exit/ref text and retrievals; excludes schemas, JSON envelopes, prompts, and reasoning.\n"
        "Not billing, model-specific token counts, or subscription quota savings.\n"
    )


def _validate_arguments(name: str, arguments: Any) -> None:
    if not isinstance(arguments, dict):
        raise ValueError("arguments must be an object")
    schema = next(tool["inputSchema"] for tool in TOOLS_DEFINITIONS if tool["name"] == name)
    for required in schema.get("required", []):
        if required not in arguments:
            raise ValueError(f"Missing required argument: {required}")
    types = {"string": str, "integer": int, "boolean": bool, "object": dict, "array": list}
    for key, value in arguments.items():
        spec = schema["properties"].get(key)
        if spec and type(value) is not types[spec["type"]]:
            raise ValueError(f"{key} must be {spec['type']}")


@_timed
def handle_tokencut_clip(arguments: dict[str, Any]) -> str:
    from tokencut.core.clip import compact_text

    text = arguments.get("text", "")
    budget = arguments.get("budget", 2000)
    if type(budget) is not int or not 64 <= budget <= 32000:
        raise ValueError("budget must be an integer between 64 and 32000")
    res = compact_text(text, budget=budget)
    return _record(text, res.text, operation="clip")


@_timed
def handle_tokencut_pack(arguments: dict[str, Any]) -> str:
    from tokencut.core.pack import pack_context

    root_str = arguments.get("root")
    if not root_str:
        raise ValueError("root is required")
    root = Path(root_str).resolve()
    if not root.is_dir():
        raise ValueError(f"root must be a valid directory: {root_str}")
    paths = arguments.get("paths")
    budget = arguments.get("budget", 4000)
    if type(budget) is not int or not 100 <= budget <= 64000:
        raise ValueError("budget must be an integer between 100 and 64000")
    force_skeleton = bool(arguments.get("skeleton", False))

    res = pack_context(
        paths=paths,
        root=root,
        budget=budget,
        force_skeleton=force_skeleton,
    )
    return _record("", res.bundle_text, operation="pack", project=root)


@_timed
def handle_tokencut_distill(arguments: dict[str, Any]) -> str:
    from tokencut.core.distill import distill_conversation

    transcript = arguments.get("transcript", "")
    budget = arguments.get("budget", 1500)
    if type(budget) is not int or not 100 <= budget <= 32000:
        raise ValueError("budget must be an integer between 100 and 32000")
    res = distill_conversation(transcript, budget=budget)
    return _record(transcript, res.text, operation="distill")


@_timed
def handle_tokencut_table(arguments: dict[str, Any]) -> str:
    from tokencut.core.table import compact_table

    data = arguments.get("data", "")
    budget = arguments.get("budget", 2000)
    format_type = arguments.get("format", "toon")
    if type(budget) is not int or not 100 <= budget <= 32000:
        raise ValueError("budget must be an integer between 100 and 32000")
    if format_type not in {"toon", "markdown"}:
        raise ValueError("format must be 'toon' or 'markdown'")
    res = compact_table(data, budget=budget, format_type=format_type)
    return _record(data, res.text, operation="table")


@_timed
def handle_tokencut_optimize(arguments: dict[str, Any]) -> str:
    from tokencut.core.optimizer import optimize_context

    content = arguments.get("content", "")
    budget = arguments.get("budget", 2000)
    if type(budget) is not int or not 64 <= budget <= 64000:
        raise ValueError("budget must be an integer between 64 and 64000")
    res = optimize_context(content, budget=budget)
    return _record(content, res.text, operation="optimize")


def handle_tokencut_context(arguments: dict[str, Any]) -> str:
    from tokencut.core.task_context import dispatch_context

    output = json.dumps(dispatch_context(arguments), ensure_ascii=False)
    return _record("", output, operation="context", project=arguments.get("root"))


def handle_tokencut_edit_symbol(arguments: dict[str, Any]) -> str:
    from tokencut.core.symbol_edit import replace_symbol

    path_str = arguments.get("path")
    if not path_str:
        raise ValueError("path is required")
    selector = arguments.get("selector")
    if not selector:
        raise ValueError("selector is required")
    replacement = arguments.get("replacement")
    if replacement is None:
        raise ValueError("replacement is required")
    expected_hash = arguments.get("expected_hash")
    if not expected_hash:
        raise ValueError("expected_hash is required")
    apply = bool(arguments.get("apply", False))

    path = Path(path_str).resolve()
    result = replace_symbol(path, selector, replacement, expected_hash, apply=apply)
    output = redact_secrets(result)
    return _record("", output, operation="edit_symbol", project=path)


def _respond(req: Any, *, profile: str = "full") -> dict[str, Any] | None:
    if (
        not isinstance(req, dict)
        or req.get("jsonrpc") != "2.0"
        or not isinstance(req.get("method"), str)
    ):
        return {
            "jsonrpc": "2.0",
            "id": None,
            "error": {"code": -32600, "message": "Invalid request"},
        }
    # JSON-RPC notifications never receive a response or execute tool calls.
    if "id" not in req:
        return None
    response = {"jsonrpc": "2.0", "id": req["id"]}
    method, params = req["method"], req.get("params", {})
    if not isinstance(params, dict):
        return {**response, "error": {"code": -32602, "message": "params must be an object"}}
    if method == "initialize":
        return {
            **response,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "tokencut", "version": "0.1.0"},
                "instructions": server_instructions(profile),
            },
        }
    if method == "tools/list":
        return {**response, "result": {"tools": tool_definitions(profile)}}
    if method == "ping":
        return {**response, "result": {}}
    if method != "tools/call":
        return {**response, "error": {"code": -32601, "message": "Method not found"}}
    handlers = {
        "tokencut_context": handle_tokencut_context,
        "tokencut_code": handle_tokencut_code,
        "tokencut_edit_symbol": handle_tokencut_edit_symbol,
        "tokencut_exec": handle_tokencut_exec,
        "tokencut_read": handle_tokencut_read,
        "tokencut_retrieve": handle_tokencut_retrieve,
        "tokencut_diff": handle_tokencut_diff,
        "tokencut_tree": handle_tokencut_tree,
        "tokencut_json": handle_tokencut_json,
        "tokencut_clip": handle_tokencut_clip,
        "tokencut_pack": handle_tokencut_pack,
        "tokencut_distill": handle_tokencut_distill,
        "tokencut_table": handle_tokencut_table,
        "tokencut_optimize": handle_tokencut_optimize,
        "tokencut_stats": lambda _: handle_tokencut_stats(),
    }
    name, arguments = params.get("name"), params.get("arguments", {})
    if not isinstance(name, str) or name not in {
        tool["name"] for tool in tool_definitions(profile)
    }:
        return {**response, "error": {"code": -32602, "message": "Unknown tool"}}
    try:
        _validate_arguments(name, arguments)
        output = handlers[name](arguments)
        is_error = output.startswith("Error:")
    except Exception as exc:
        output, is_error = f"Error: {redact_secrets(str(exc))[:500]}", True
    return {
        **response,
        "result": {"content": [{"type": "text", "text": output}], "isError": is_error},
    }


def run_mcp_stdio_server(profile: str = "full"):
    """Run JSON-RPC 2.0 stdio loop for Model Context Protocol."""
    tool_definitions(profile)  # Validate before reading stdin or executing anything.
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            resp = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "Parse error"},
            }
        else:
            resp = _respond(req, profile=profile)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()
