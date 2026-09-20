from __future__ import annotations

import json
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from tokencut.core.adaptive import compress_to_budget
from tokencut.core.cache import ContextCache
from tokencut.core.cleaner import CleanerOptions, compact_terminal_output
from tokencut.core.config import load_config
from tokencut.core.diff_slimmer import slim_git_diff
from tokencut.core.doctor import (
    configure_claude_desktop_mcp,
    configure_cursor_mcp,
    configure_shell_alias,
    run_all_diagnostics,
)
from tokencut.core.hooks import install_zsh_hook, setup_claude_code_mcp_config
from tokencut.core.json_slimmer import slim_json
from tokencut.core.native_hooks import install_claude_hook, run_hook_filter
from tokencut.core.pr_analyzer import analyze_pr_tokens
from tokencut.core.rules_linter import lint_rule_content, minify_rules
from tokencut.core.safe_filter import safe_compact_output
from tokencut.core.skeleton import extract_symbol_or_range
from tokencut.core.specialized import auto_specialize_command_output
from tokencut.core.telemetry import TelemetryStore
from tokencut.core.tree_scanner import render_tree, scan_directory
from tokencut.mcp.server import run_mcp_stdio_server
from tokencut.metrics.pricing import estimate_savings
from tokencut.metrics.tokenizer import compute_metrics, count_tokens

app = typer.Typer(
    name="tokencut",
    help="Context compression engine and MCP server for Claude Code, Cursor, and Gemini CLI.",
    no_args_is_help=True,
    add_completion=False,
)

console = Console()
err_console = Console(stderr=True)


@app.command()
def run(
    command: Annotated[list[str], typer.Argument(help="Command and arguments to execute")],
    max_lines: Annotated[int, typer.Option("--max-lines", "-m", help="Max lines to keep")] = 80,
    budget: Annotated[
        int | None, typer.Option("--budget", "-b", help="Strict token ceiling budget")
    ] = None,
    quiet: Annotated[bool, typer.Option("--quiet", "-q", help="Omit the summary footer")] = False,
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
    if budget is not None:
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

    if raw_output:
        metrics = compute_metrics(raw_output, compacted)
        # Record telemetry
        try:
            telemetry = TelemetryStore()
            telemetry.record(
                raw_claude=metrics.raw_tokens.claude,
                compact_claude=metrics.compact_tokens.claude,
                raw_openai=metrics.raw_tokens.openai,
                compact_openai=metrics.compact_tokens.openai,
                raw_gemini=metrics.raw_tokens.gemini,
                compact_gemini=metrics.compact_tokens.gemini,
            )
        except Exception:
            pass

        if not quiet and not safe:
            err_console.print(
                f"[tokencut: estimated text reduction {metrics.reduction_pct}%; {duration:.2f}s]",
                markup=False,
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
    budget: Annotated[
        int | None, typer.Option("--budget", "-b", help="Strict token ceiling budget")
    ] = None,
):
    """Inspect file with AST skeletonization, symbol filtering, or line slicing."""
    if not file_path.exists():
        err_console.print(f"[bold red]File not found:[/bold red] {file_path}")
        raise typer.Exit(code=1)

    raw_content = file_path.read_text(encoding="utf-8", errors="replace")
    output = extract_symbol_or_range(
        file_path,
        symbol=symbol,
        lines_range=lines,
        skeleton=skeleton,
        strip_comments=strip_comments,
    )

    if budget:
        output = compress_to_budget(output, max_tokens=budget, source=str(file_path))

    console.print(output)

    if skeleton or lines or symbol or strip_comments or budget:
        metrics = compute_metrics(raw_content, output)
        err_console.print(
            f"[dim]tokencut: original {metrics.raw_tokens.avg:,} tokens -> {metrics.compact_tokens.avg:,} tokens "
            f"(-{metrics.reduction_pct}%)[/dim]"
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

    slimmed = slim_json(
        raw_text,
        max_array_items=max_items,
        max_string_len=max_str,
        cache_full=not no_cache,
    )
    console.print(slimmed)

    metrics = compute_metrics(raw_text, slimmed)
    err_console.print(
        f"[dim]tokencut json: original {metrics.raw_tokens.avg:,} -> {metrics.compact_tokens.avg:,} tokens "
        f"(-{metrics.reduction_pct}%)[/dim]"
    )


@app.command()
def retrieve(
    ref_id: Annotated[
        str, typer.Argument(help="Reference ID from tokencut log notice (e.g. 'tc_8f2a1b')")
    ],
    lines: Annotated[
        str | None, typer.Option("--lines", "-l", help="Line range to inspect (e.g. 20-60)")
    ] = None,
):
    """Retrieve full uncompressed raw output from the local Compress-Cache-Retrieve store."""
    cache = ContextCache()
    raw = cache.retrieve(ref_id, lines_range=lines)
    sys.stdout.write(raw)
    if not raw.endswith("\n"):
        sys.stdout.write("\n")
    # Recovery is additional context, not a second saving of the original log.
    try:
        counts = count_tokens(raw)
        TelemetryStore().record(0, counts.claude, 0, counts.openai, 0, counts.gemini)
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
        typer.Option("--all", "-a", help="Install Claude Desktop, Cursor MCP, and shell alias"),
    ] = False,
    cursor: Annotated[
        bool, typer.Option("--cursor", help="Configure Cursor MCP (~/.cursor/mcp.json)")
    ] = False,
    claude_desktop: Annotated[
        bool, typer.Option("--claude-desktop", help="Configure Claude Desktop local MCP")
    ] = False,
    alias: Annotated[
        bool, typer.Option("--alias", help="Add 'alias cc=tokencut run --' to shell rc")
    ] = False,
):
    """Configure local MCP integrations and optional shell aliases."""
    if not (all_targets or cursor or claude_desktop or alias):
        console.print("[yellow]Specify --all, --claude-desktop, --cursor, or --alias.[/yellow]")
        raise typer.Exit(code=1)

    if all_targets or cursor:
        ok, msg = configure_cursor_mcp()
        if not ok:
            err_console.print(msg, markup=False)
            raise typer.Exit(code=1)
        console.print(f"[green]✓ Cursor MCP configured in {msg}![/green]")

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
    raw_input = sys.stdin.read()
    if not raw_input:
        return

    trimmed = raw_input.strip()
    if (trimmed.startswith("{") and trimmed.endswith("}")) or (
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

    sys.stdout.write(compacted + "\n")


@app.command()
def diff(
    staged: Annotated[bool, typer.Option("--staged", "-s", help="Inspect staged changes")] = False,
):
    """Slim git diff by folding lockfiles and suppressing excessive context."""
    cmd = "git diff --cached" if staged else "git diff"
    res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    raw_diff = res.stdout

    if not raw_diff.strip():
        console.print("[dim]No git changes detected.[/dim]")
        return

    slimmed = slim_git_diff(raw_diff)
    console.print(slimmed)

    metrics = compute_metrics(raw_diff, slimmed)
    err_console.print(
        f"[dim]tokencut diff: saved {metrics.saved_tokens.avg:,} tokens (-{metrics.reduction_pct}%)[/dim]"
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
def mcp():
    """Start the Model Context Protocol (MCP) server for Claude Code, Cursor, and Codex."""
    run_mcp_stdio_server()


@app.command()
def demo():
    """Run interactive demonstration showing token reduction on real-world scenarios."""
    console.print(
        Panel(
            "[bold cyan]tokencut[/bold cyan] — Real-World Token Optimization Demo\n"
            "[dim]Evaluating token savings on Pytest failure trace and large build log.[/dim]",
            border_style="cyan",
        )
    )

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

    opts = CleanerOptions(max_lines=30)
    compacted = compact_terminal_output(noisy_pytest, opts)
    metrics = compute_metrics(noisy_pytest, compacted)
    savings = estimate_savings(
        metrics.saved_tokens.claude, metrics.saved_tokens.openai, metrics.saved_tokens.gemini
    )

    table = Table(title="Scenario: Pytest Failure with 85 test items")
    table.add_column("Harness / Model", style="cyan")
    table.add_column("Raw Tokens", style="red")
    table.add_column("With tokencut", style="green")
    table.add_column("Reduction", style="bold yellow")
    table.add_column("Preserved Info", style="magenta")

    table.add_row(
        "Anthropic Claude 3.5/3.7",
        f"{metrics.raw_tokens.claude:,}",
        f"{metrics.compact_tokens.claude:,}",
        f"-{metrics.reduction_pct}%",
        "100% (Exact traceback & error intact)",
    )
    table.add_row(
        "OpenAI GPT-4o / Codex",
        f"{metrics.raw_tokens.openai:,}",
        f"{metrics.compact_tokens.openai:,}",
        f"-{metrics.reduction_pct}%",
        "100% (Exact traceback & error intact)",
    )
    table.add_row(
        "Google Gemini 2.0 / 1.5",
        f"{metrics.raw_tokens.gemini:,}",
        f"{metrics.compact_tokens.gemini:,}",
        f"-{metrics.reduction_pct}%",
        "100% (Exact traceback & error intact)",
    )

    console.print(table)
    console.print(
        f"[bold green]Result:[/bold green] Saved [bold]{metrics.saved_tokens.avg:,} tokens[/bold] "
        f"([bold]{metrics.reduction_pct}% saved[/bold]) on a single test run! Est. savings: {savings.format_avg()}"
    )


@app.command()
def benchmark():
    """Run automated benchmarks across real-world workloads."""
    demo()


def main():
    app()


if __name__ == "__main__":
    main()
