from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from tokencut.core.adaptive import compress_to_budget
from tokencut.core.cache import ContextCache
from tokencut.core.cleaner import CleanerOptions, compact_terminal_output
from tokencut.core.companion_state import already_wrapped, paused
from tokencut.core.config import load_config
from tokencut.core.diff_slimmer import slim_git_diff
from tokencut.core.doctor import (
    configure_claude_desktop_mcp,
    configure_cursor_mcp,
    configure_shell_alias,
    configure_windsurf_mcp,
    run_all_diagnostics,
)
from tokencut.core.engines import select_engine
from tokencut.core.hooks import install_zsh_hook, setup_claude_code_mcp_config
from tokencut.core.json_slimmer import slim_json
from tokencut.core.native_hooks import install_claude_hook, run_hook_filter
from tokencut.core.pr_analyzer import analyze_pr_tokens
from tokencut.core.rules_linter import lint_rule_content, minify_rules
from tokencut.core.safe_filter import safe_compact_output
from tokencut.core.skeleton import extract_symbol_or_range
from tokencut.core.specialized import auto_specialize_command_output
from tokencut.core.telemetry import TelemetryStore, record_text, recovery_engine
from tokencut.core.tree_scanner import render_tree, scan_directory
from tokencut.mcp.server import run_mcp_stdio_server
from tokencut.metrics.tokenizer import compute_metrics, count_tokens

app = typer.Typer(
    name="tokencut",
    help="Context compression engine and MCP server for Claude Code, Cursor, and Gemini CLI.",
    no_args_is_help=True,
    add_completion=False,
)

console = Console()
err_console = Console(stderr=True)


def _emit(text: str) -> str:
    emitted = text + ("\n" if text and not text.endswith("\n") else "")
    sys.stdout.write(emitted)
    return emitted


@app.command("context")
def task_context(request_file: Annotated[Path | None, typer.Option("--request-file")] = None):
    """Save/read/list/forget task checkpoints using a JSON request on stdin or from a file."""
    from tokencut.core.redactor import redact_secrets
    from tokencut.core.task_context import dispatch_context

    try:
        if request_file is None:
            raw = sys.stdin.read(65537)
        else:
            with request_file.open() as stream:
                raw = stream.read(65537)
        if len(raw) > 65536:
            raise ValueError("Context request exceeds 64 KiB")
        output = json.dumps(dispatch_context(json.loads(raw)), ensure_ascii=False)
        record_text("", _emit(output), operation="context", client="cli")
    except (ValueError, OSError) as exc:
        raise typer.BadParameter(redact_secrets(str(exc))) from exc


@app.command("context-hook")
def task_context_hook(client: Annotated[str, typer.Option("--client")]):
    """Handle a native context lifecycle event without model calls."""
    from tokencut.core.context_hooks import run_context_hook

    run_context_hook(client, sys.stdin, sys.stdout)


@app.command("context-install")
def task_context_install(
    client: Annotated[str, typer.Option("--client")],
    cache_dir: Annotated[Path, typer.Option("--cache-dir")],
):
    """Opt into task-memory hooks; preserve client settings and back up every change."""
    from tokencut.core.context_hooks import install_context_hooks

    try:
        executable = Path(shutil.which("tokencut") or sys.argv[0])
        path = install_context_hooks(client, executable, cache_dir)
        _emit(
            f"Configured task-memory hooks in {path}. Reopen the session. Configured does not mean active."
        )
        if client == "codex":
            _emit(
                "Review and trust these hooks in Codex before they can run. TokenCut does not bypass hook trust."
            )
    except (ValueError, OSError) as exc:
        raise typer.BadParameter(str(exc)) from exc


@app.command("code")
def code_query(
    root: Annotated[Path, typer.Argument(help="Absolute project directory")],
    mode: Annotated[str, typer.Option("--mode")] = "map",
    query: Annotated[str, typer.Option("--query", "-q")] = "",
    file: Annotated[str | None, typer.Option("--file")] = None,
    limit: Annotated[int, typer.Option("--limit", min=1, max=200)] = 30,
    budget: Annotated[int, typer.Option("--budget", min=64, max=32000)] = 2000,
):
    """Query an incremental local syntax index without AI calls."""
    from tokencut.mcp.server import handle_tokencut_code

    arguments = {
        "root": str(root),
        "mode": mode,
        "query": query,
        "limit": limit,
        "max_tokens": budget,
    }
    if file is not None:
        arguments["file"] = file
    try:
        _emit(handle_tokencut_code(arguments))
    except (ValueError, OSError) as exc:
        raise typer.BadParameter(str(exc)) from exc


@app.command("edit-symbol")
def edit_symbol(
    path: Annotated[Path, typer.Argument(help="Absolute source file")],
    symbol: Annotated[str, typer.Argument(help="Qualified name, optionally @line")],
    replacement_file: Annotated[Path, typer.Option("--replacement-file")],
    expected_hash: Annotated[str, typer.Option("--expected-hash")],
    apply: Annotated[bool, typer.Option("--apply", help="Write the previewed change")] = False,
):
    """Preview/replace an exact symbol; run through the client's native shell permissions."""
    from tokencut.core.redactor import redact_secrets
    from tokencut.core.symbol_edit import replace_symbol

    try:
        result = replace_symbol(
            path, symbol, replacement_file.read_bytes().decode("utf-8"), expected_hash, apply=apply
        )
        _emit(redact_secrets(result))
    except (ValueError, SyntaxError, OSError) as exc:
        raise typer.BadParameter(str(exc)) from exc


@app.command("clip")
def clip_command(
    file: Annotated[
        Path | None,
        typer.Option("--file", "-f", help="Read input from file instead of clipboard/stdin"),
    ] = None,
    budget: Annotated[
        int, typer.Option("--budget", "-b", min=64, max=100000, help="Target token budget ceiling")
    ] = 2000,
    copy: Annotated[
        bool, typer.Option("--copy", "-c", help="Copy compacted output back to clipboard")
    ] = False,
    stats: Annotated[
        bool, typer.Option("--stats", "-s", help="Print token reduction stats to stderr")
    ] = False,
):
    """Compact noisy terminal text, test logs, diffs, JSON, or tracebacks from clipboard or stdin."""
    from tokencut.core.clip import compact_text, get_clipboard, set_clipboard

    if file is not None:
        try:
            raw = file.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise typer.BadParameter(f"Cannot read file: {exc}") from exc
    elif not sys.stdin.isatty():
        raw = sys.stdin.read()
    else:
        raw = get_clipboard()
        if not raw:
            err_console.print("[yellow]Clipboard is empty and no stdin provided.[/yellow]")
            raise typer.Exit(code=1)

    result = compact_text(raw, budget=budget)

    if copy:
        if set_clipboard(result.text):
            err_console.print(
                f"[green]Compacted text ({result.compacted_tokens} tokens) copied to clipboard![/green]"
            )
        else:
            err_console.print("[yellow]Failed to copy to clipboard.[/yellow]")

    if stats:
        err_console.print(
            f"[dim]Tokens: {result.original_tokens} -> {result.compacted_tokens} "
            f"({result.reduction_pct}% reduction, saved {result.saved_tokens} tok) "
            f"[type: {result.content_type}][/dim]"
        )

    _emit(result.text)


@app.command("pack")
def pack_command(
    paths: Annotated[list[Path] | None, typer.Argument(help="Files or directories to pack")] = None,
    root: Annotated[
        Path | None, typer.Option("--root", "-r", help="Project root directory")
    ] = None,
    budget: Annotated[
        int, typer.Option("--budget", "-b", min=100, max=200000, help="Target token budget ceiling")
    ] = 4000,
    skeleton: Annotated[
        bool, typer.Option("--skeleton", "-s", help="Force AST skeletonization on code files")
    ] = False,
    copy: Annotated[
        bool, typer.Option("--copy", "-c", help="Copy packed bundle to clipboard")
    ] = False,
    output: Annotated[
        Path | None, typer.Option("--output", "-o", help="Write bundle to output file")
    ] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Emit pack summary as JSON")] = False,
):
    """Pack repository files into an AI-optimized context bundle with AST skeletons and secret scrubbing."""
    from tokencut.core.clip import set_clipboard
    from tokencut.core.pack import pack_context

    project_root = (root or Path.cwd()).resolve()
    path_strs = [str(p) for p in paths] if paths else None
    result = pack_context(
        paths=path_strs,
        root=project_root,
        budget=budget,
        force_skeleton=skeleton,
    )

    if json_output:
        _emit(json.dumps(result.to_dict(), indent=2))
        return

    if output is not None:
        try:
            output.write_text(result.bundle_text, encoding="utf-8")
            err_console.print(f"[green]Packed bundle written to {output}[/green]")
        except OSError as exc:
            raise typer.BadParameter(f"Failed to write output file: {exc}") from exc
    else:
        _emit(result.bundle_text)

    if copy:
        if set_clipboard(result.bundle_text):
            err_console.print(
                f"[green]Packed bundle ({result.packed_tokens} tokens) copied to clipboard![/green]"
            )
        else:
            err_console.print("[yellow]Failed to copy to clipboard.[/yellow]")

    err_console.print(
        f"[dim]Packed {result.file_count} files: {result.original_tokens} -> {result.packed_tokens} tokens ({result.reduction_pct}% saved)[/dim]"
    )


@app.command("prepare")
def prepare_command(
    file: Annotated[Path | None, typer.Option("--file", "-f", help="Read a supplied draft")] = None,
    mode: Annotated[
        str, typer.Option(help="conservative, summary (lossy), or optimize (autonomous)")
    ] = "conservative",
    budget: Annotated[
        int, typer.Option(min=128, max=8000, help="Summary or optimize target budget")
    ] = 1500,
    json_output: Annotated[
        bool, typer.Option("--json", help="Include local preview measurements")
    ] = False,
):
    """Preview shorter input before pasting it into any chat; never sends or counts usage."""
    from tokencut.core.prepare import MAX_INPUT_BYTES, prepare_text

    try:
        if file is not None:
            with file.open("rb") as stream:
                raw = stream.read(MAX_INPUT_BYTES + 1)
        elif not sys.stdin.isatty():
            raw = sys.stdin.read(MAX_INPUT_BYTES + 1).encode("utf-8")
        else:
            raise ValueError(
                "Supply --file or pipe text through stdin; clipboard is not read automatically"
            )
        if len(raw) > MAX_INPUT_BYTES:
            raise ValueError("Draft exceeds 128 KiB; select a smaller relevant excerpt")
        result = prepare_text(raw.decode("utf-8"), mode=mode, budget=budget)
    except (OSError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    if json_output:
        print(json.dumps(result, ensure_ascii=False))
    else:
        sys.stdout.write(result["text"])
        err_console.print(
            f"Preview: {result['before']} → {result['after']} local o200k tokens. "
            "Review before pasting; not counted as usage savings. "
            "Recognized credentials are redacted; compaction may cache a redacted original."
        )
        if mode == "summary":
            err_console.print(
                "Summary is heuristic and lossy; verify goals, constraints and decisions."
            )
        elif mode == "optimize":
            err_console.print(
                "Autonomous optimizer applied intra-fence compaction, TOON, or cache alignment."
            )


@app.command("distill")
def distill_command(
    file: Annotated[
        Path | None,
        typer.Option("--file", "-f", help="Read conversation from file instead of clipboard/stdin"),
    ] = None,
    budget: Annotated[
        int, typer.Option("--budget", "-b", min=100, max=100000, help="Target token budget ceiling")
    ] = 1500,
    copy: Annotated[
        bool, typer.Option("--copy", "-c", help="Copy distilled context back to clipboard")
    ] = False,
    stats: Annotated[
        bool, typer.Option("--stats", "-s", help="Print token reduction stats to stderr")
    ] = False,
):
    """Prepare a lossy transcript summary for review, with a recoverable cached original."""
    from tokencut.core.clip import get_clipboard, set_clipboard
    from tokencut.core.distill import distill_conversation

    if file is not None:
        try:
            raw = file.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise typer.BadParameter(f"Cannot read file: {exc}") from exc
    elif not sys.stdin.isatty():
        raw = sys.stdin.read()
    else:
        raw = get_clipboard()
        if not raw:
            err_console.print("[yellow]Clipboard is empty and no stdin provided.[/yellow]")
            raise typer.Exit(code=1)

    result = distill_conversation(raw, budget=budget)

    if copy:
        if set_clipboard(result.text):
            err_console.print(
                f"[green]Distilled context ({result.distilled_tokens} tokens) copied to clipboard![/green]"
            )
        else:
            err_console.print("[yellow]Failed to copy to clipboard.[/yellow]")

    if stats:
        err_console.print(
            f"[dim]Tokens: {result.original_tokens} -> {result.distilled_tokens} "
            f"({result.reduction_pct}% reduction, saved {result.saved_tokens} tok) "
            f"[{result.message_count} messages, {len(result.files_referenced)} files][/dim]"
        )

    _emit(result.text)


@app.command("table")
def table_command(
    file: Annotated[
        Path | None,
        typer.Option("--file", "-f", help="Read tabular data from file instead of stdin/clipboard"),
    ] = None,
    budget: Annotated[
        int, typer.Option("--budget", "-b", min=100, max=100000, help="Target token budget ceiling")
    ] = 2000,
    format_type: Annotated[
        str, typer.Option("--format", help="Output table format: 'toon' or 'markdown'")
    ] = "toon",
    copy: Annotated[
        bool, typer.Option("--copy", "-c", help="Copy compacted table back to clipboard")
    ] = False,
    stats: Annotated[
        bool, typer.Option("--stats", "-s", help="Print token reduction stats to stderr")
    ] = False,
):
    """Compress JSON arrays, CSV, or TSV data into compact TOON or Markdown table."""
    from tokencut.core.clip import get_clipboard, set_clipboard
    from tokencut.core.table import compact_table

    if file is not None:
        try:
            raw = file.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise typer.BadParameter(f"Cannot read file: {exc}") from exc
    elif not sys.stdin.isatty():
        raw = sys.stdin.read()
    else:
        raw = get_clipboard()
        if not raw:
            err_console.print("[yellow]Clipboard is empty and no stdin provided.[/yellow]")
            raise typer.Exit(code=1)

    result = compact_table(raw, budget=budget, format_type=format_type)

    if copy:
        if set_clipboard(result.text):
            err_console.print(
                f"[green]Compacted table ({result.compacted_tokens} tokens) copied to clipboard![/green]"
            )
        else:
            err_console.print("[yellow]Failed to copy to clipboard.[/yellow]")

    if stats:
        err_console.print(
            f"[dim]Tokens: {result.original_tokens} -> {result.compacted_tokens} "
            f"({result.reduction_pct}% reduction, saved {result.saved_tokens} tok) "
            f"[{result.row_count} rows, {result.column_count} columns][/dim]"
        )

    _emit(result.text)


prompt_app = typer.Typer(
    name="prompt",
    help="Audit and optimize system prompts for Anthropic, OpenAI, and Gemini prompt caching.",
    no_args_is_help=True,
)
app.add_typer(prompt_app, name="prompt")


@prompt_app.command("lint")
def prompt_lint_command(
    file: Annotated[Path, typer.Argument(help="Path to prompt or instructions file")],
    json_output: Annotated[bool, typer.Option("--json", help="Emit audit as JSON")] = False,
):
    """Audit prompt for cache-busting dynamic elements in prefix."""
    from tokencut.core.prompt_optimizer import lint_prompt

    try:
        raw = file.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise typer.BadParameter(f"Cannot read file: {exc}") from exc

    result = lint_prompt(raw)
    if json_output:
        _emit(json.dumps(result, indent=2))
        return

    score = result["cacheability_score"]
    color = "green" if score >= 80 else "yellow" if score >= 50 else "red"
    err_console.print(f"[{color}]Prompt Cacheability Score: {score}/100[/{color}]")
    if result["issues"]:
        err_console.print("[bold red]Cache-Busting Issues Found in Prefix:[/bold red]")
        for issue in result["issues"]:
            err_console.print(f"  • {issue}")
    if result["recommendations"]:
        err_console.print("[bold cyan]Recommendations:[/bold cyan]")
        for rec in result["recommendations"]:
            err_console.print(f"  → {rec}")


@prompt_app.command("align")
def prompt_align_command(
    file: Annotated[Path, typer.Argument(help="Path to prompt or instructions file")],
    output: Annotated[
        Path | None, typer.Option("--output", "-o", help="Write aligned prompt to file")
    ] = None,
    copy: Annotated[
        bool, typer.Option("--copy", "-c", help="Copy aligned prompt to clipboard")
    ] = False,
):
    """Restructure prompt: move static instructions to prefix and isolate dynamic context to suffix."""
    from tokencut.core.clip import set_clipboard
    from tokencut.core.prompt_optimizer import align_prompt

    try:
        raw = file.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise typer.BadParameter(f"Cannot read file: {exc}") from exc

    result = align_prompt(raw)
    if output is not None:
        output.write_text(result.aligned_text, encoding="utf-8")
        err_console.print(f"[green]Aligned prompt written to {output}[/green]")
    else:
        _emit(result.aligned_text)

    if copy:
        if set_clipboard(result.aligned_text):
            err_console.print("[green]Aligned prompt copied to clipboard![/green]")
        else:
            err_console.print("[yellow]Failed to copy to clipboard.[/yellow]")

    err_console.print(f"[dim]Cacheability score: {result.cacheability_score}/100[/dim]")


@prompt_app.command("minify")
def prompt_minify_command(
    file: Annotated[Path, typer.Argument(help="Path to prompt, CLAUDE.md, or AGENTS.md file")],
    output: Annotated[
        Path | None, typer.Option("--output", "-o", help="Write minified prompt to file")
    ] = None,
    stats: Annotated[
        bool, typer.Option("--stats", "-s", help="Print token reduction summary to stderr")
    ] = False,
    json_output: Annotated[
        bool, typer.Option("--json", help="Emit minification metrics as JSON")
    ] = False,
    copy: Annotated[
        bool, typer.Option("--copy", "-c", help="Copy minified prompt to clipboard")
    ] = False,
):
    """Minify system instructions, CLAUDE.md, and AGENTS.md without semantic loss."""
    from tokencut.core.clip import set_clipboard
    from tokencut.core.prompt_optimizer import minify_prompt

    try:
        raw = file.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise typer.BadParameter(f"Cannot read file: {exc}") from exc

    result = minify_prompt(raw)

    if json_output:
        _emit(json.dumps(result.to_dict(), indent=2))
        return

    if output is not None:
        output.write_text(result.minified_text, encoding="utf-8")
        err_console.print(f"[green]Minified prompt written to {output}[/green]")
    else:
        _emit(result.minified_text)

    if copy:
        if set_clipboard(result.minified_text):
            err_console.print("[green]Minified prompt copied to clipboard![/green]")
        else:
            err_console.print("[yellow]Failed to copy to clipboard.[/yellow]")

    if stats or output is not None:
        err_console.print(
            f"[dim]Tokens: {result.original_tokens} → {result.minified_tokens} "
            f"({result.reduction_pct}% reduction, {result.saved_tokens} tokens saved)[/dim]"
        )


@app.command("optimize")
def optimize_command(
    target: Annotated[
        str | None,
        typer.Argument(
            help="Optional file or directory to optimize (defaults to stdin or clipboard)"
        ),
    ] = None,
    file: Annotated[
        Path | None,
        typer.Option("--file", "-f", help="Read input from file instead of stdin/clipboard"),
    ] = None,
    budget: Annotated[
        int, typer.Option("--budget", "-b", min=100, max=200000, help="Target token budget ceiling")
    ] = 2000,
    copy: Annotated[
        bool, typer.Option("--copy", "-c", help="Copy optimized result to clipboard")
    ] = False,
    stats: Annotated[
        bool, typer.Option("--stats", "-s", help="Print token reduction stats to stderr")
    ] = False,
    json_output: Annotated[
        bool, typer.Option("--json", help="Emit structured optimization metrics as JSON")
    ] = False,
):
    """Unified autonomous context optimizer.

    Self-routes and applies hybrid intra-fence code compaction, TOON tabular compression,
    conversation distillation, prompt cache alignment, and secret redaction with 0-loss CCR guarantee.
    """
    from tokencut.core.clip import get_clipboard, set_clipboard
    from tokencut.core.optimizer import optimize_context
    from tokencut.core.pack import pack_context

    raw = ""
    input_path = file or (Path(target) if target else None)
    if input_path is not None:
        if input_path.exists():
            if input_path.is_dir():
                raw = pack_context(input_path, budget=budget).bundle_text
            else:
                try:
                    raw = input_path.read_text(encoding="utf-8", errors="replace")
                except OSError as exc:
                    err_console.print(
                        f"[bold red]Error reading file {input_path}:[/bold red] {exc}"
                    )
                    raise typer.Exit(code=1)
        else:
            err_console.print(f"[bold red]Target path not found:[/bold red] {input_path}")
            raise typer.Exit(code=1)
    elif not sys.stdin.isatty():
        raw = sys.stdin.read()
    else:
        clip_content = get_clipboard()
        if clip_content:
            raw = clip_content
            err_console.print("[dim]Reading from clipboard...[/dim]")
        else:
            err_console.print("[yellow]Clipboard is empty and no file/stdin provided.[/yellow]")
            raise typer.Exit(code=1)

    result = optimize_context(raw, budget=budget)

    if json_output:
        _emit(json.dumps(result.to_dict(), indent=2))
        return

    if copy:
        if set_clipboard(result.text):
            err_console.print(
                f"[green]Optimized context ({result.optimized_tokens} tokens) copied to clipboard![/green]"
            )
        else:
            err_console.print("[yellow]Failed to copy to clipboard.[/yellow]")

    if stats:
        stages = " -> ".join(result.pipeline_stages)
        err_console.print(
            f"[dim]Tokens: {result.original_tokens} -> {result.optimized_tokens} "
            f"({result.reduction_pct}% reduction, saved {result.saved_tokens} tok) "
            f"[mode: {result.primary_mode}, stages: {stages}, ref: {result.ref_id}][/dim]"
        )

    _emit(result.text)


@app.command()
def monitor(stdio: Annotated[bool, typer.Option("--stdio")] = False):
    """Local companion JSON-lines protocol (stdin/stdout; no listening port)."""
    from tokencut.core.monitor import Monitor

    service = Monitor()
    if stdio:
        service.serve(sys.stdin, sys.stdout)
    else:
        sys.stdout.write(json.dumps(service.snapshot(), ensure_ascii=False) + "\n")


@app.command()
def run(
    command: Annotated[list[str], typer.Argument(help="Command and arguments to execute")],
    max_lines: Annotated[int, typer.Option("--max-lines", "-m", help="Max lines to keep")] = 80,
    budget: Annotated[
        int | None, typer.Option("--budget", "-b", min=1, help="Strict token ceiling budget")
    ] = None,
    quiet: Annotated[bool, typer.Option("--quiet", "-q", help="Omit the summary footer")] = False,
    engine: Annotated[str, typer.Option("--engine", help="auto|tokencut|none")] = "auto",
    safe: Annotated[
        bool,
        typer.Option(
            "--safe/--compact",
            help="Preserve unknown output and diagnostics; --compact permits truncation",
        ),
    ] = True,
):
    """Execute a command and optimize its output for AI context windows."""
    full_cmd = shlex.join(command)
    try:
        selected = select_engine(engine)
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--engine") from exc
    wrapped = already_wrapped(full_cmd)
    if wrapped:
        selected = "none"
    start_time = time.perf_counter()

    # Preserve argument boundaries and literal shell metacharacters. Shell syntax
    # remains available explicitly: tokencut run -- bash -lc 'command | other'.
    proc = subprocess.run(
        command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace"
    )
    raw_output = proc.stdout

    duration = time.perf_counter() - start_time

    # Step 1: Check specialized command handler
    specialized = None if safe else auto_specialize_command_output(full_cmd, raw_output)
    base_text = specialized if specialized is not None else raw_output

    # Step 2: Apply adaptive budget or standard compaction
    if selected == "none":
        compacted = raw_output
    elif budget is not None:
        compacted = compress_to_budget(
            base_text, max_tokens=budget, source="run", original_text=raw_output
        )
    elif safe:
        compacted = safe_compact_output(raw_output, command=full_cmd, exit_code=proc.returncode)
    elif len(base_text) > 500 and base_text.lstrip().startswith(("{", "[")):
        compacted = slim_json(base_text, max_array_items=3)
    else:
        opts = CleanerOptions(max_lines=max_lines)
        compacted = compact_terminal_output(base_text, opts)

    if compacted:
        # Rich markup/wrapping can alter diagnostic text and hide recovery refs.
        sys.stdout.write(compacted)
        if not compacted.endswith("\n"):
            sys.stdout.write("\n")

    if raw_output and not quiet and not safe:
        metrics = compute_metrics(raw_output, compacted)
        if not quiet and not safe:
            err_console.print(
                f"[tokencut: estimated text reduction {metrics.reduction_pct}%; {duration:.2f}s]",
                markup=False,
            )

    if not wrapped:
        emitted = compacted + ("\n" if compacted and not compacted.endswith("\n") else "")
        record_text(
            raw_output, emitted, duration_s=time.perf_counter() - start_time, engine=selected
        )

    if proc.returncode != 0:
        raise typer.Exit(code=proc.returncode)


@app.command()
def cat(
    file_path: Annotated[Path, typer.Argument(help="Path to file")],
    skeleton: Annotated[
        bool,
        typer.Option("--skeleton", "-s", help="Extract AST code skeleton (classes & signatures)"),
    ] = False,
    lines: Annotated[
        str | None, typer.Option("--lines", "-l", help="Line range to inspect (e.g. 10-50)")
    ] = None,
    symbol: Annotated[
        str | None,
        typer.Option("--symbol", "-y", help="Specific class or function name to extract"),
    ] = None,
    strip_comments: Annotated[
        bool, typer.Option("--strip-comments", "-c", help="Strip comments and blank lines")
    ] = False,
    if_modified_since: Annotated[
        str | None,
        typer.Option(
            "--if-modified-since",
            "-m",
            help="SHA-256 hash to check for conditional 304 read (returns short notice if unchanged)",
        ),
    ] = None,
    include_hash: Annotated[
        bool, typer.Option("--include-hash", "-H", help="Prepend file SHA-256 hash header")
    ] = False,
    budget: Annotated[
        int | None, typer.Option("--budget", "-b", help="Strict token ceiling budget")
    ] = None,
):
    """Inspect file with AST skeletonization, symbol filtering, or line slicing."""
    if not file_path.exists():
        err_console.print(f"[bold red]File not found:[/bold red] {file_path}")
        raise typer.Exit(code=1)

    start = time.perf_counter()
    if if_modified_since:
        source_bytes = file_path.read_bytes()
        current_hash = hashlib.sha256(source_bytes).hexdigest()
        clean_req = if_modified_since.strip().lower()
        if (
            current_hash == clean_req
            or current_hash.startswith(clean_req)
            or clean_req.startswith(current_hash)
        ):
            notice = (
                f"# [tokencut: 304 Not Modified. File '{file_path.name}' is unchanged "
                f"since hash {current_hash[:12]} ({len(source_bytes):,} bytes).]\n"
            )
            sys.stdout.write(notice)
            record_text(
                file_path.read_text(encoding="utf-8", errors="replace"),
                notice,
                operation="read",
                project=file_path,
                duration_s=time.perf_counter() - start,
                engine="none" if paused() else "tokencut",
            )
            return

    try:
        output = extract_symbol_or_range(
            file_path,
            symbol=symbol,
            lines_range=lines,
            skeleton=skeleton,
            strip_comments=strip_comments,
        )
    except (ValueError, SyntaxError, OSError) as exc:
        raise typer.BadParameter(str(exc)) from exc

    if include_hash:
        source_bytes = file_path.read_bytes()
        current_hash = hashlib.sha256(source_bytes).hexdigest()
        output = f"# [sha256: {current_hash[:16]}]\n" + output

    requested = output
    if budget and not paused():
        output = compress_to_budget(output, max_tokens=budget, source=str(file_path))
    record_text(
        requested,
        _emit(output),
        operation="read",
        project=file_path,
        duration_s=time.perf_counter() - start,
        engine="none" if paused() else "tokencut",
    )


@app.command(name="json")
def json_cmd(
    target: Annotated[
        str | None,
        typer.Argument(help="JSON file path or string (reads stdin if omitted)"),
    ] = None,
    max_items: Annotated[
        int, typer.Option("--max-items", "-n", help="Max array items to retain")
    ] = 3,
    max_str: Annotated[int, typer.Option("--max-str", "-s", help="Max string length")] = 120,
    no_cache: Annotated[
        bool, typer.Option("--no-cache", help="Do not store in SQLite CCR")
    ] = False,
):
    """Compact large JSON payloads, folding arrays and truncating long strings."""
    start = time.perf_counter()
    if target:
        p = Path(target)
        if p.exists() and p.is_file():
            raw_text = p.read_text(encoding="utf-8", errors="replace")
        else:
            raw_text = target
    else:
        raw_text = sys.stdin.read()

    if not raw_text.strip():
        err_console.print("[dim]No JSON input received.[/dim]")
        return

    slimmed = (
        raw_text
        if paused()
        else slim_json(
            raw_text, max_array_items=max_items, max_string_len=max_str, cache_full=not no_cache
        )
    )
    record_text(
        raw_text,
        _emit(slimmed),
        operation="json",
        project=p if target and p.is_file() else None,
        duration_s=time.perf_counter() - start,
        engine="none" if paused() else "tokencut",
    )


@app.command()
def retrieve(
    ref_id: Annotated[
        str, typer.Argument(help="Reference ID from tokencut log notice (e.g. 'tc_8f2a1b')")
    ],
    query: Annotated[str | None, typer.Option("--query", "-q")] = None,
    lines: Annotated[
        str | None, typer.Option("--lines", "-l", help="Line range to inspect (e.g. 20-60)")
    ] = None,
):
    """Retrieve full uncompressed raw output from the local Compress-Cache-Retrieve store."""
    cache = ContextCache()
    if query is not None and lines is not None:
        raise typer.BadParameter("Choose --query or --lines, not both")
    try:
        raw = (
            cache.search(ref_id, query)
            if query is not None
            else cache.retrieve(ref_id, lines_range=lines)
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    emitted = _emit(raw)
    # Recovery is additional context, not a second saving of the original log.
    try:
        record_text("", emitted, operation="retrieve", engine=recovery_engine(ref_id))
    except Exception:
        pass


@app.command()
def cache(
    action: Annotated[str, typer.Argument(help="Action: stats, clear")] = "stats",
):
    """Manage local SQLite Compress-Cache-Retrieve store."""
    c = ContextCache()
    if action == "clear":
        c.clear()
        console.print("[green]✓ Cleared tokencut cache store successfully.[/green]")
    else:
        s = c.get_stats()
        table = Table(title="tokencut CCR Cache Store")
        table.add_column("Property", style="cyan")
        table.add_column("Value", style="bold")
        table.add_row("Database Path", str(s["path"]))
        table.add_row("Cached Entries", f"{s['count']:,}")
        table.add_row("File Size", f"{s['size_kb']:.1f} KB")
        console.print(table)


@app.command()
def tree(
    directory: Annotated[Path, typer.Argument(help="Root directory to analyze")] = Path("."),
    depth: Annotated[int, typer.Option("--depth", "-d", help="Max directory depth to display")] = 3,
):
    """Visualize repository token breakdown and identify token-hogging files."""
    if not directory.exists() or not directory.is_dir():
        err_console.print(f"[bold red]Invalid directory:[/bold red] {directory}")
        raise typer.Exit(code=1)

    with console.status("[bold cyan]Scanning repository token distribution...[/bold cyan]"):
        root_node, all_files = scan_directory(directory.resolve(), max_depth=depth)

    rich_tree = render_tree(root_node, root_node.tokens)
    console.print(rich_tree)

    if all_files:
        top_table = Table(title="Top Token Consumers (Candidates for Skeleton / Exclusion)")
        top_table.add_column("File", style="cyan")
        top_table.add_column("Tokens", style="bold yellow")
        top_table.add_column("% of Repo", style="magenta")

        for rel, tok in all_files[:6]:
            pct = (tok / root_node.tokens * 100) if root_node.tokens > 0 else 0
            top_table.add_row(rel, f"{tok:,}", f"{pct:.1f}%")

        console.print(top_table)


@app.command()
def stats(
    format_type: Annotated[
        str, typer.Option("--format", "-f", help="Output format: table, json, markdown")
    ] = "table",
):
    """Display local output estimates, not provider billing or usage quotas."""
    telemetry = TelemetryStore()
    s = telemetry.get_stats()

    if format_type == "json":
        data = {
            "total_runs": s.total_runs,
            "saved_claude": s.saved_claude,
            "saved_openai": s.saved_openai,
            "saved_gemini": s.saved_gemini,
            "reduction_pct": s.reduction_pct,
            "measurement": "local output estimates, not model usage or subscription quota",
        }
        sys.stdout.write(json.dumps(data, indent=2) + "\n")
        return

    if format_type == "markdown":
        md = f"""| Metric | Value |
| :--- | :--- |
| **Total Executions** | {s.total_runs:,} |
| **Claude Tokens Saved** | {s.saved_claude:,} |
| **OpenAI Tokens Saved** | {s.saved_openai:,} |
| **Gemini Tokens Saved** | {s.saved_gemini:,} |
| **Average Reduction** | {s.reduction_pct}% |
| **Measurement** | Local output estimates; not model billing or quota |
"""
        console.print(md.strip())
        return

    table = Table(title="TokenCut local output estimates (not model usage)")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="bold")

    table.add_row("Recorded CLI output events", f"{s.total_runs:,}")
    table.add_row("Claude heuristic net reduction", f"{s.saved_claude:,}")
    table.add_row("OpenAI tokenizer net reduction", f"{s.saved_openai:,}")
    table.add_row("Gemini heuristic net reduction", f"{s.saved_gemini:,}")
    table.add_row("Average estimated reduction", f"{s.reduction_pct}%")
    table.add_row("Scope", "CLI output and retrieval only; excludes prompts, schemas and reasoning")

    console.print(table)


@app.command("share")
def share_command(
    badge: Annotated[
        bool, typer.Option("--badge", "-b", help="Output only the Markdown badge code")
    ] = False,
):
    """Generate shareable badges and links for GitHub READMEs, social media, and PRs."""
    telemetry = TelemetryStore()
    s = telemetry.get_stats()
    badge_pct = f"{s.reduction_pct}%25" if s.reduction_pct > 0 else "active"
    badge_md = f"[![TokenCut Context](https://img.shields.io/badge/tokencut-{badge_pct}%20saved-b3f5cd)](https://github.com/00200200/tokencut)"

    if badge:
        sys.stdout.write(badge_md + "\n")
        return

    console.print("\n[bold green]⚡ Share TokenCut & Add Badge to your Repository[/bold green]\n")
    console.print("[bold]1. README.md Badge (Markdown):[/bold]")
    console.print(f"   `{badge_md}`\n")
    console.print("[bold]2. Share on Social Media & Developer Forums:[/bold]")
    console.print("   • GitHub: https://github.com/00200200/tokencut")
    console.print(
        "   • X / Twitter: https://twitter.com/intent/tweet?text=Cutting+LLM+coding+context+bloat+by+up+to+90%25+with+TokenCut+%28local+MCP+%2B+CLI%29%3A+https%3A%2F%2Fgithub.com%2F00200200%2Ftokencut"
    )
    console.print(
        "   • Hacker News: https://news.ycombinator.com/submitlink?u=https://github.com/00200200/tokencut&t=Show%20HN%3A%20TokenCut%20%E2%80%93%20Zero-bloat%20context%20optimizer%20and%20MCP%20companion%20for%20AI%20coding\n"
    )


@app.command()
def doctor(
    fix: Annotated[
        bool, typer.Option("--fix", "-f", help="Automatically configure missing integrations")
    ] = False,
):
    """Diagnose environment and integration health across Claude, Cursor, and shell."""
    diagnostics = run_all_diagnostics()

    table = Table(title="tokencut System & Integration Diagnostics")
    table.add_column("Component", style="cyan")
    table.add_column("Status", style="bold")
    table.add_column("Details", style="dim")

    for item in diagnostics:
        if item.status == "ok":
            status_badge = "[green]✓ OK[/green]"
        elif item.status == "warning":
            status_badge = "[yellow]! WARN[/yellow]"
        else:
            status_badge = "[red]✗ MISSING[/red]"
        table.add_row(item.name, status_badge, item.message)

    console.print(table)

    if fix:
        console.print("\n[bold cyan]Applying automatic configuration fixes...[/bold cyan]")
        c_ok, c_msg = configure_cursor_mcp()
        if c_ok:
            console.print(f"[green]✓ Configured Cursor MCP in {c_msg}[/green]")
        w_ok, w_msg = configure_windsurf_mcp()
        if w_ok:
            console.print(f"[green]✓ Configured Windsurf MCP in {w_msg}[/green]")
        if sys.platform == "darwin":
            cd_ok, cd_msg = configure_claude_desktop_mcp()
            if cd_ok:
                console.print(f"[green]✓ Configured Claude Desktop MCP in {cd_msg}[/green]")
        a_ok, a_msg = configure_shell_alias()
        if a_ok:
            console.print(f"[green]✓ Configured shell alias in {a_msg}[/green]")
        else:
            console.print(f"[dim]• {a_msg}[/dim]")
    else:
        missing = [d for d in diagnostics if d.status in {"missing", "warning"} and d.remedy]
        if missing:
            console.print(
                "\n[bold yellow]Recommended actions (or run `tokencut doctor --fix`):[/bold yellow]"
            )
            for m in missing:
                console.print(f"  • {m.name}: {m.remedy}")


@app.command()
def install(
    all_targets: Annotated[
        bool,
        typer.Option(
            "--all", "-a", help="Install Claude Desktop, Cursor, Windsurf MCP, and shell alias"
        ),
    ] = False,
    cursor: Annotated[
        bool, typer.Option("--cursor", help="Configure Cursor MCP (~/.cursor/mcp.json)")
    ] = False,
    windsurf: Annotated[
        bool,
        typer.Option(
            "--windsurf", help="Configure Windsurf MCP (~/.codeium/windsurf/mcp_config.json)"
        ),
    ] = False,
    claude_desktop: Annotated[
        bool, typer.Option("--claude-desktop", help="Configure Claude Desktop local MCP")
    ] = False,
    alias: Annotated[
        bool, typer.Option("--alias", help="Add 'alias cc=tokencut run --' to shell rc")
    ] = False,
):
    """Configure local MCP integrations and optional shell aliases."""
    if not (all_targets or cursor or windsurf or claude_desktop or alias):
        console.print(
            "[yellow]Specify --all, --claude-desktop, --cursor, --windsurf, or --alias.[/yellow]"
        )
        raise typer.Exit(code=1)

    if all_targets or cursor:
        ok, msg = configure_cursor_mcp()
        if not ok:
            err_console.print(msg, markup=False)
            raise typer.Exit(code=1)
        console.print(f"[green]✓ Cursor MCP configured in {msg}![/green]")

    if all_targets or windsurf:
        ok, msg = configure_windsurf_mcp()
        if not ok:
            err_console.print(msg, markup=False)
            raise typer.Exit(code=1)
        console.print(f"[green]✓ Windsurf MCP configured in {msg}![/green]")

    if all_targets or claude_desktop:
        ok, msg = configure_claude_desktop_mcp()
        if not ok:
            err_console.print(msg, markup=False)
            raise typer.Exit(code=1)
        console.print(
            f"Claude Desktop MCP configured in {msg}. Restart/reconnect to activate.", markup=False
        )

    if all_targets or alias:
        _, msg = configure_shell_alias()
        console.print(f"[green]✓ Shell alias configured in {msg}![/green]")


@app.command()
def hook(
    install: Annotated[
        bool, typer.Option("--install", "-i", help="Install shell wrapper to ~/.zshrc")
    ] = False,
    client: Annotated[
        str,
        typer.Option("--client", help="claude for native output filtering, or shell for aliases"),
    ] = "shell",
):
    """Configure Claude Code or terminal hooks for automatic optimization."""
    if install:
        if client == "claude":
            executable = Path(shutil.which("tokencut") or sys.argv[0])
            settings = install_claude_hook(executable)
            console.print(
                f"Installed Claude Bash output hook in {settings}. Restart Claude Code to activate.",
                markup=False,
            )
            return
        if client != "shell":
            raise typer.BadParameter("client must be claude or shell")
        zshrc = install_zsh_hook()
        console.print(f"[green]✓ Successfully installed alias to {zshrc}![/green]")
        console.print("Run [bold cyan]source ~/.zshrc[/bold cyan] to enable [bold]cc-run[/bold].")
    else:
        console.print(
            Panel(
                "[bold cyan]tokencut Harness Integration[/bold cyan]\n\n"
                "1. [bold]Claude Code MCP:[/bold]\n"
                f"   {setup_claude_code_mcp_config()}\n\n"
                "2. [bold]Shell Alias (run with --install):[/bold]\n"
                "   alias cc-run='tokencut run'\n",
                title="Auto-Wiring",
                border_style="cyan",
            )
        )


@app.command("hook-filter")
def hook_filter(client: Annotated[str, typer.Option("--client")] = "claude"):
    """Process one native hook event on stdin, without model calls."""
    run_hook_filter(client, sys.stdin, sys.stdout)


@app.command()
def pipe(
    max_lines: Annotated[int, typer.Option("--max-lines", "-m", help="Max lines to keep")] = 80,
    budget: Annotated[
        int | None, typer.Option("--budget", "-b", help="Strict token ceiling")
    ] = None,
):
    """Stream or pipe standard input through tokencut."""
    start = time.perf_counter()
    raw_input = sys.stdin.read()
    if not raw_input:
        return

    trimmed = raw_input.strip()
    if paused():
        compacted = raw_input
    elif (trimmed.startswith("{") and trimmed.endswith("}")) or (
        trimmed.startswith("[") and trimmed.endswith("]")
    ):
        if len(trimmed) > 500:
            compacted = slim_json(trimmed, max_array_items=3)
        else:
            compacted = trimmed
    elif budget:
        compacted = compress_to_budget(raw_input, max_tokens=budget)
    else:
        opts = CleanerOptions(max_lines=max_lines)
        compacted = compact_terminal_output(raw_input, opts)

    record_text(
        raw_input,
        _emit(compacted),
        operation="pipe",
        duration_s=time.perf_counter() - start,
        engine="none" if paused() else "tokencut",
    )


@app.command()
def diff(
    staged: Annotated[bool, typer.Option("--staged", "-s", help="Inspect staged changes")] = False,
    ignore_patterns: Annotated[
        list[str] | None,
        typer.Option("--ignore", "-i", help="Regex patterns of files to fold in diff"),
    ] = None,
):
    """Slim git diff by folding lockfiles and suppressing excessive context."""
    start = time.perf_counter()
    cmd = ["git", "diff", "--no-ext-diff", "--no-textconv", "--no-color"]
    if staged:
        cmd.append("--cached")
    res = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    raw_diff = res.stdout
    if res.returncode:
        sys.stderr.write(res.stderr)
        raise typer.Exit(res.returncode)
    slimmed = raw_diff if paused() else slim_git_diff(raw_diff, extra_patterns=ignore_patterns)
    emitted = _emit(slimmed)
    sys.stderr.write(res.stderr)
    record_text(
        raw_diff + res.stderr,
        emitted + res.stderr,
        operation="diff",
        duration_s=time.perf_counter() - start,
        engine="none" if paused() else "tokencut",
    )


@app.command()
def pr(
    base: Annotated[
        str, typer.Option("--base", "-b", help="Base git ref to compare against")
    ] = "origin/main",
    markdown: Annotated[
        bool, typer.Option("--markdown", "-m", help="Output Markdown report for PR comments")
    ] = False,
    max_delta: Annotated[
        int | None,
        typer.Option("--max-delta", help="Maximum allowable net token delta before failure"),
    ] = None,
):
    """Analyze repository token impact of current branch compared to base."""
    report = analyze_pr_tokens(base_ref=base)
    if markdown:
        console.print(report.format_markdown())
    else:
        table = Table(title=f"tokencut PR Token Impact: {report.base_ref}...HEAD")
        table.add_column("Category", style="cyan")
        table.add_column("Token Delta", style="bold")

        table.add_row("Application Code", f"{report.code_delta:+,} tok")
        table.add_row("Documentation & Prompts", f"{report.docs_delta:+,} tok")
        table.add_row("Dependencies & Lockfiles", f"{report.lockfile_delta:+,} tok")
        table.add_row("Net Repository Change", f"[bold]{report.total_delta:+,} tok[/bold]")
        console.print(table)

    cfg = load_config()
    threshold = max_delta if max_delta is not None else cfg.max_token_delta
    if threshold is not None and report.total_delta > threshold:
        err_console.print(
            f"[bold red]Error:[/bold red] Token increase (+{report.total_delta:,}) exceeds threshold (+{threshold:,})!"
        )
        raise typer.Exit(code=1)


@app.command()
def lint(
    file_path: Annotated[Path, typer.Argument(help="Path to CLAUDE.md or rules file")] = Path(
        "CLAUDE.md"
    ),
    minify: Annotated[
        bool, typer.Option("--minify", "-m", help="Write out minified version")
    ] = False,
):
    """Audit CLAUDE.md / .cursorrules for prompt cache busting and token bloat."""
    if not file_path.exists():
        err_console.print(f"[bold red]File not found:[/bold red] {file_path}")
        raise typer.Exit(code=1)

    content = file_path.read_text(encoding="utf-8", errors="replace")
    result = lint_rule_content(content, file_name=str(file_path))

    table = Table(title=f"tokencut Rule Audit: {file_path.name}")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="bold")

    table.add_row("Token Footprint", f"~{result.token_count:,} tokens")
    table.add_row("Line Count", f"{result.line_count} lines")
    cache_status = (
        "[green]YES[/green]"
        if result.is_cache_friendly
        else "[red]NO (Cache Busting Detected!)[/red]"
    )
    table.add_row("Cache Friendly?", cache_status)

    console.print(table)

    if result.issues:
        console.print("\n[bold yellow]Issues Detected:[/bold yellow]")
        for iss in result.issues:
            console.print(f"  Line {iss.line_num} [{iss.rule_name}]: {iss.message}")
            console.print(f"    [dim]{iss.snippet}[/dim]")

    if minify:
        minified = minify_rules(content)
        file_path.write_text(minified, encoding="utf-8")
        before_tok = count_tokens(content).avg
        after_tok = count_tokens(minified).avg
        console.print(
            f"\n[green]Successfully minified {file_path}: {before_tok} -> {after_tok} tokens![/green]"
        )


@app.command()
def mcp(
    profile: Annotated[
        str,
        typer.Option(
            "--profile",
            envvar="TOKENCUT_MCP_PROFILE",
            help="coding: 8 core tools; full: all tools (default)",
        ),
    ] = "full",
):
    """Start the Model Context Protocol (MCP) server for Claude Code, Cursor, and Codex."""
    from tokencut.mcp.server import tool_definitions

    try:
        tool_definitions(profile)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    run_mcp_stdio_server(profile)


@app.command()
def demo(
    json_output: Annotated[
        bool, typer.Option("--json", help="Emit the measured fixture result and checks as JSON")
    ] = False,
):
    """Verify safe filtering and recovery on an authored fixture, without model calls."""
    noisy_pytest = (
        "pytest -v tests/\n"
        + "\n".join(
            [f"tests/test_mod_{i}.py::test_feature_ok PASSED [ {i}%]" for i in range(1, 85)]
        )
        + "\n\n"
        + "=================================== FAILURES ===================================\n"
        + "_________________________________ test_payment _________________________________\n"
        + "def test_payment():\n"
        + "    client = PaymentClient(sandbox=True)\n"
        + ">   assert client.charge(amount=100) == 'SUCCESS'\n"
        + "E   AssertionError: assert 'GATEWAY_TIMEOUT' == 'SUCCESS'\n"
        + "E     - SUCCESS\n"
        + "E     + GATEWAY_TIMEOUT\n"
        + "tests/test_payment.py:42: AssertionError\n"
        + "=========================== short test summary info ============================\n"
        + "FAILED tests/test_payment.py::test_payment - AssertionError: assert 'GATEWAY_TIMEOUT' == 'SUCCESS'\n"
        + "========================= 1 failed, 84 passed in 3.42s =========================\n"
    )
    noisy_git_diff = (
        "diff --git a/src/main.py b/src/main.py\n"
        "index 1234567..89abcdef 100644\n"
        "--- a/src/main.py\n"
        "+++ b/src/main.py\n"
        "@@ -10,6 +10,7 @@ def process():\n"
        "     context_line_1\n"
        "     context_line_2\n"
        "     context_line_3\n"
        "+    new_important_logic()\n"
        "     context_line_4\n"
        "     context_line_5\n"
        "diff --git a/uv.lock b/uv.lock\n"
        "index aaaaaaa..bbbbbbb 100644\n"
        "--- a/uv.lock\n"
        "+++ b/uv.lock\n"
        "@@ -1,500 +1,500 @@\n"
        '-old_package_version = "1.0.0"\n'
        '+new_package_version = "1.0.1"\n'
        + "\n".join(f"+ extra_lock_line_{i}" for i in range(100))
        + "\n"
    )
    noisy_ruff = (
        "src/auth/session.py:12:8: F401 [*] `os` imported but unused\n"
        "  |\n"
        "10 | import sys\n"
        "11 | import json\n"
        "12 | import os\n"
        "   |        ^^\n"
        "  |\n"
        "  = help: Remove unused import: `os`\n"
        "\n"
        "src/auth/session.py:44:5: F841 Local variable `token` is assigned to but never used\n"
        "  |\n"
        "42 | def refresh():\n"
        "43 |     client = Client()\n"
        "44 |     token = client.issue()\n"
        "   |     ^^^^^\n"
        "45 |     return client\n"
        "  |\n"
        "  = help: Remove assignment to unused variable `token`\n"
        "\n"
        "Found 2 errors.\n"
        "[*] 1 fixable with the `--fix` option.\n"
    )
    docker_lines: list[str] = []
    for step in range(1, 25):
        docker_lines.extend(
            [
                f"#{step} [internal] load build context",
                f"#{step} transferring context: {120 + step}B done",
                f"#{step} DONE 0.{step % 9}s",
                (
                    f"#{step} [stage-0 {step}/24] RUN echo layer_{step} "
                    f"&& pip install pkg{step}==1.0.{step}"
                ),
            ]
        )
        for j in range(8):
            docker_lines.extend(
                [
                    f"#{step} {j}.1 Collecting pkg{step}-dep{j}==2.0.{j}",
                    (
                        f"#{step} {j}.2   Downloading "
                        f"pkg{step}_dep{j}-2.0.{j}-py3-none-any.whl ({40 + j} kB)"
                    ),
                    f"#{step} {j}.3 Installing collected packages: pkg{step}-dep{j}",
                    f"#{step} {j}.4 Successfully installed pkg{step}-dep{j}-2.0.{j}",
                ]
            )
        docker_lines.append(f"#{step} DONE {1 + step % 5}.{step % 9}s")
    docker_lines.extend(
        [
            (
                'ERROR: failed to solve: process "/bin/sh -c pip install broken==9.9.9" '
                "did not complete successfully: exit code: 1"
            ),
            "------",
            " > [stage-0 24/24] RUN pip install broken==9.9.9:",
            "1.2 ERROR: Could not find a version that satisfies the requirement broken==9.9.9",
            "1.2 ERROR: No matching distribution found for broken==9.9.9",
            "------",
        ]
    )
    noisy_docker = "\n".join(docker_lines)

    noisy_tsc = (
        "src/auth/jwt.ts:45:12 - error TS2345: Argument of type 'string | undefined' "
        "is not assignable to parameter of type 'string'.\n"
        "  Type 'undefined' is not assignable to type 'string'.\n"
        "\n"
        '  43 |   const headerToken = headers.get("authorization") ?? undefined;\n'
        "  44 |   // verify the bearer token before continuing the chain\n"
        "> 45 |   verifyToken(headerToken);\n"
        "     |               ~~~~~~~~~~~\n"
        "  46 |   return next();\n"
        "  47 | }\n"
        "\n"
        "src/auth/jwt.ts:45:12 - error TS2345: Argument of type 'string | undefined' "
        "is not assignable to parameter of type 'string'.\n"
        "  Type 'undefined' is not assignable to type 'string'.\n"
        "\n"
        '  43 |   const headerToken = headers.get("authorization") ?? undefined;\n'
        "  44 |   // verify the bearer token before continuing the chain\n"
        "> 45 |   verifyToken(headerToken);\n"
        "     |               ~~~~~~~~~~~\n"
        "  46 |   return next();\n"
        "  47 | }\n"
        "\n"
        "src/models/user.ts:18:7 - error TS2741: Property 'email' is missing in type "
        "'{ id: number; name: string; }' but required in type 'User'.\n"
        "\n"
        "  16 | export function buildUser(id: number, name: string): User {\n"
        "  17 |   // TODO: pull email from the directory service\n"
        '> 18 |   const u: User = { id: 1, name: "Alice" };\n'
        "     |         ~\n"
        "  19 |   return u;\n"
        "  20 | }\n"
        "\n"
        "Found 3 errors in 2 files.\n"
        "\n"
        "Errors  Files\n"
        "     2  src/auth/jwt.ts:45\n"
        "     1  src/models/user.ts:18\n"
    )
    noisy_eslint = (
        "error: 'os' is defined but never used (@typescript-eslint/no-unused-vars) "
        "at src/auth/session.ts:12:8:\n"
        '  10 | import sys from "sys";\n'
        '  11 | import json from "json";\n'
        '> 12 | import os from "os";\n'
        "     |        ^\n"
        "  13 |\n"
        "  at Object.<anonymous> (src/auth/session.ts:12:8)\n"
        "  at Module._compile (node:internal/modules/cjs/loader:1521:14)\n"
        "\n"
        "error: 'os' is defined but never used (@typescript-eslint/no-unused-vars) "
        "at src/auth/session.ts:12:8:\n"
        '  10 | import sys from "sys";\n'
        '  11 | import json from "json";\n'
        '> 12 | import os from "os";\n'
        "     |        ^\n"
        "  13 |\n"
        "  at Object.<anonymous> (src/auth/session.ts:12:8)\n"
        "  at Module._compile (node:internal/modules/cjs/loader:1521:14)\n"
        "\n"
        "error: Unexpected any. Specify a different type (@typescript-eslint/no-explicit-any) "
        "at src/auth/session.ts:44:5:\n"
        "  42 | function refresh() {\n"
        "  43 |   const client = new Client();\n"
        "> 44 |   const token: any = client.issue();\n"
        "     |     ^^^\n"
        "  45 |   return client;\n"
        "  46 | }\n"
        "\n"
        "✖ 3 problems (3 errors, 0 warnings)\n"
    )
    npm_chunks: list[str] = ["PASS src/widget.test.js", "  ✓ renders (2 ms)"]
    for i in range(40):
        npm_chunks.extend(
            [
                "  console.log",
                f"    debug payload item={i} value={'x' * 48}",
                "",
                f"      at Object.<anonymous> (src/widget.test.js:{10 + i}:13)",
                "",
            ]
        )
    npm_chunks.extend(
        [
            "  ✓ saves (3 ms)",
            "PASS src/other.test.js",
            "  ✓ ok (1 ms)",
            "",
            "stdout | src/other.test.js > ok",
            "vitest live stdout " + ("y" * 60),
            "vitest live stdout more " + ("y" * 40),
            "",
            "FAIL src/payment.test.js",
            "  ● charge › times out",
            "",
            "    expect(received).toBe(expected)",
            "",
            '    Expected: "SUCCESS"',
            '    Received: "GATEWAY_TIMEOUT"',
            "",
            "      42 |   expect(result).toBe('SUCCESS');",
            "",
            "  console.error",
            "    failure side channel must stay",
            "",
            "      at Object.<anonymous> (src/payment.test.js:50:13)",
            "",
            "Test Suites: 1 failed, 2 passed, 3 total",
            "Tests:       1 failed, 3 passed, 4 total",
        ]
    )
    noisy_npm_test = "\n".join(npm_chunks)

    noisy_mypy = """src/auth/session.py:12: error: Name "os" is not defined  [name-defined]
    |
  10 | import sys
  11 | import json
  12 | print(os.getcwd())
    |           ^
  13 | return True
    |
src/auth/session.py:44: error: Incompatible return value type (got "None", expected "str")  [return-value]
    |
  42 | def refresh() -> str:
  43 |     client = Client()
  44 |     return None
    |            ^
    |
src/models/user.py:18: error: Missing named argument "email" for "User"  [call-arg]
    |
  17 | def build():
  18 |     return User(id=1, name="Alice")
    |            ^
    |
src/models/user.py:31: error: Incompatible types in assignment (expression has type "str", variable has type "int")  [assignment]
    |
  30 | age: int
  31 | age = "thirty"
    |       ^
  32 | return age
    |
src/api/handlers.py:7: error: Argument 1 to "loads" has incompatible type "bytes"; expected "str"  [arg-type]
    |
   5 | import json
   6 | def parse(raw: bytes):
   7 |     return json.loads(raw)
    |                         ^
    |
src/api/handlers.py:22: error: Item "None" of "str | None" has no attribute "strip"  [union-attr]
    |
  21 | def clean(value: str | None) -> str:
  22 |     return value.strip()
    |            ^
    |
src/db/pool.py:55: error: Need type annotation for "cache"  [var-annotated]
    |
  53 | class Pool:
  54 |     def __init__(self):
  55 |         self.cache = {}
    |              ^
    |
src/db/pool.py:88: error: Returning Any from function declared to return "Connection"  [no-any-return]
    |
  87 | def connect(self):
  88 |     return self._factory()
    |            ^
    |
src/auth/session.py:44: note: Error code "return-value" not covered by "type: ignore" comment
Found 8 errors in 4 files (checked 24 source files)
"""

    # A disposable cache makes the demo independent of the user's project and
    # existing history. Always restore an explicit caller-provided cache path.
    previous_cache = os.environ.get("TOKENCUT_CACHE_DIR")
    with TemporaryDirectory(prefix="tokencut-demo-") as directory:
        try:
            os.environ["TOKENCUT_CACHE_DIR"] = directory
            compacted = safe_compact_output(noisy_pytest, command="pytest -v tests/", exit_code=1)
            ref = re.search(r"tc_[a-f0-9]{16}", compacted)
            recovered = ContextCache().retrieve(ref[0]) if ref else None
            failure_tail = noisy_pytest[noisy_pytest.index("=== FAILURES") :]
            unknown = "".join(f"unique custom record {i}\n" for i in range(150))
            git_diff_compact = auto_specialize_command_output("git diff", noisy_git_diff) or ""
            ruff_compact = auto_specialize_command_output("ruff check .", noisy_ruff) or ""
            docker_compact = (
                auto_specialize_command_output("docker build -t app .", noisy_docker) or ""
            )
            tsc_compact = auto_specialize_command_output("npx tsc --noEmit", noisy_tsc) or ""
            eslint_compact = (
                auto_specialize_command_output("npx eslint . --format codeframe", noisy_eslint)
                or ""
            )
            mypy_compact = auto_specialize_command_output("mypy src", noisy_mypy) or ""
            npm_test_compact = auto_specialize_command_output("npm test", noisy_npm_test) or ""
            checks = {
                "complete_failure_tail_preserved": failure_tail in compacted,
                "original_recovered_exactly": recovered == noisy_pytest,
                "unknown_output_unchanged": safe_compact_output(unknown) == unknown,
                "git_diff_folds_lockfile_keeps_code": (
                    "omitted by tokencut" in git_diff_compact
                    and "+    new_important_logic()" in git_diff_compact
                    and "+ extra_lock_line_50" not in git_diff_compact
                ),
                "ruff_keeps_codes_drops_frames": (
                    "F401" in ruff_compact
                    and "F841" in ruff_compact
                    and "Found 2 errors." in ruff_compact
                    and "import os" not in ruff_compact
                ),
                "docker_keeps_failure_drops_layer_progress": (
                    "failed to solve" in docker_compact
                    and "No matching distribution found for broken==9.9.9" in docker_compact
                    and "Collecting pkg1-dep0" not in docker_compact
                    and "docker build progress lines" in docker_compact
                ),
                "tsc_keeps_codes_drops_frames": (
                    "TS2345" in tsc_compact
                    and "TS2741" in tsc_compact
                    and "verifyToken(headerToken);" not in tsc_compact
                    and tsc_compact.count("src/auth/jwt.ts:45:12 TS2345") == 1
                ),
                "eslint_keeps_rules_drops_frames": (
                    "@typescript-eslint/no-unused-vars" in eslint_compact
                    and "@typescript-eslint/no-explicit-any" in eslint_compact
                    and "import os from" not in eslint_compact
                    and "at Module._compile" not in eslint_compact
                    and eslint_compact.count("src/auth/session.ts:12:8 error") == 1
                ),
                "mypy_keeps_codes_drops_frames": (
                    "[name-defined]" in mypy_compact
                    and "[return-value]" in mypy_compact
                    and "Found 8 errors in 4 files" in mypy_compact
                    and "print(os.getcwd())" not in mypy_compact
                ),
                "npm_test_keeps_failure_drops_console": (
                    "GATEWAY_TIMEOUT" in npm_test_compact
                    and "failure side channel must stay" in npm_test_compact
                    and "debug payload item=0" not in npm_test_compact
                    and "console lines omitted" in npm_test_compact
                ),
            }
        finally:
            if previous_cache is None:
                os.environ.pop("TOKENCUT_CACHE_DIR", None)
            else:
                os.environ["TOKENCUT_CACHE_DIR"] = previous_cache

    raw_tokens = count_tokens(noisy_pytest).openai
    output_tokens = count_tokens(compacted).openai
    checks["smaller_including_recovery_notice"] = output_tokens < raw_tokens
    git_raw_tokens = count_tokens(noisy_git_diff).openai
    git_output_tokens = count_tokens(git_diff_compact).openai
    ruff_raw_tokens = count_tokens(noisy_ruff).openai
    ruff_output_tokens = count_tokens(ruff_compact).openai
    docker_raw_tokens = count_tokens(noisy_docker).openai
    docker_output_tokens = count_tokens(docker_compact).openai
    tsc_raw_tokens = count_tokens(noisy_tsc).openai
    tsc_output_tokens = count_tokens(tsc_compact).openai
    eslint_raw_tokens = count_tokens(noisy_eslint).openai
    eslint_output_tokens = count_tokens(eslint_compact).openai
    mypy_raw_tokens = count_tokens(noisy_mypy).openai
    mypy_output_tokens = count_tokens(mypy_compact).openai
    npm_raw_tokens = count_tokens(noisy_npm_test).openai
    npm_output_tokens = count_tokens(npm_test_compact).openai
    passed = all(checks.values())
    result = {
        "measurement": "local tokenizer estimate on authored fixtures; not model billing or quota",
        "model_calls": 0,
        "raw_tokens": raw_tokens,
        "output_tokens": output_tokens,
        "reduction_pct": round(100 * (raw_tokens - output_tokens) / raw_tokens, 1),
        "specialized": {
            "git_diff": {
                "raw_tokens": git_raw_tokens,
                "output_tokens": git_output_tokens,
                "reduction_pct": round(
                    100 * (git_raw_tokens - git_output_tokens) / git_raw_tokens, 1
                ),
            },
            "ruff": {
                "raw_tokens": ruff_raw_tokens,
                "output_tokens": ruff_output_tokens,
                "reduction_pct": round(
                    100 * (ruff_raw_tokens - ruff_output_tokens) / ruff_raw_tokens, 1
                ),
            },
            "docker_build": {
                "raw_tokens": docker_raw_tokens,
                "output_tokens": docker_output_tokens,
                "reduction_pct": round(
                    100 * (docker_raw_tokens - docker_output_tokens) / docker_raw_tokens, 1
                ),
            },
            "tsc": {
                "raw_tokens": tsc_raw_tokens,
                "output_tokens": tsc_output_tokens,
                "reduction_pct": round(
                    100 * (tsc_raw_tokens - tsc_output_tokens) / tsc_raw_tokens, 1
                ),
            },
            "eslint": {
                "raw_tokens": eslint_raw_tokens,
                "output_tokens": eslint_output_tokens,
                "reduction_pct": round(
                    100 * (eslint_raw_tokens - eslint_output_tokens) / eslint_raw_tokens, 1
                ),
            },
            "mypy": {
                "raw_tokens": mypy_raw_tokens,
                "output_tokens": mypy_output_tokens,
                "reduction_pct": round(
                    100 * (mypy_raw_tokens - mypy_output_tokens) / mypy_raw_tokens, 1
                ),
            },
            "npm_test": {
                "raw_tokens": npm_raw_tokens,
                "output_tokens": npm_output_tokens,
                "reduction_pct": round(
                    100 * (npm_raw_tokens - npm_output_tokens) / npm_raw_tokens, 1
                ),
            },
        },
        "checks": checks,
        "passed": passed,
    }
    if json_output:
        sys.stdout.write(json.dumps(result, indent=2) + "\n")
    else:
        table = Table(title="TokenCut: verify your installation")
        table.add_column("Authored fixture", style="cyan")
        table.add_column("Result")
        table.add_row(
            "pytest (incl. recovery notice)",
            f"{raw_tokens:,} -> {output_tokens:,} ({result['reduction_pct']}%)",
        )
        table.add_row(
            "git diff (lockfile + code hunk)",
            (
                f"{git_raw_tokens:,} -> {git_output_tokens:,} "
                f"({result['specialized']['git_diff']['reduction_pct']}%)"
            ),
        )
        table.add_row(
            "ruff check (full frames)",
            (
                f"{ruff_raw_tokens:,} -> {ruff_output_tokens:,} "
                f"({result['specialized']['ruff']['reduction_pct']}%)"
            ),
        )
        table.add_row(
            "docker build (BuildKit progress)",
            (
                f"{docker_raw_tokens:,} -> {docker_output_tokens:,} "
                f"({result['specialized']['docker_build']['reduction_pct']}%)"
            ),
        )
        table.add_row(
            "tsc (pretty frames)",
            (
                f"{tsc_raw_tokens:,} -> {tsc_output_tokens:,} "
                f"({result['specialized']['tsc']['reduction_pct']}%)"
            ),
        )
        table.add_row(
            "eslint (codeframe + stacks)",
            (
                f"{eslint_raw_tokens:,} -> {eslint_output_tokens:,} "
                f"({result['specialized']['eslint']['reduction_pct']}%)"
            ),
        )
        table.add_row(
            "mypy --pretty (frames)",
            (
                f"{mypy_raw_tokens:,} -> {mypy_output_tokens:,} "
                f"({result['specialized']['mypy']['reduction_pct']}%)"
            ),
        )
        table.add_row(
            "npm test (console dumps)",
            (
                f"{npm_raw_tokens:,} -> {npm_output_tokens:,} "
                f"({result['specialized']['npm_test']['reduction_pct']}%)"
            ),
        )
        for name, ok in checks.items():
            table.add_row(name.replace("_", " "), "PASS" if ok else "FAIL")
        console.print(table)
        console.print(
            "No model calls. Fixture results are not subscription savings or a task-quality benchmark."
        )
        console.print("Try your own command: tokencut run -- <command> <args>")
    if not passed:
        raise typer.Exit(code=1)


@app.command()
def benchmark():
    """Run the installation fixture; use scripts/benchmark_suite.py for the full suite."""
    demo()


def main():
    app()


if __name__ == "__main__":
    main()
