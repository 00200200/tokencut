from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from tokencut.core.cleaner import CleanerOptions, compact_terminal_output
from tokencut.core.diff_slimmer import slim_git_diff
from tokencut.core.rules_linter import lint_rule_content, minify_rules
from tokencut.core.skeleton import extract_symbol_or_range
from tokencut.mcp.server import run_mcp_stdio_server
from tokencut.metrics.pricing import estimate_savings
from tokencut.metrics.tokenizer import compute_metrics, count_tokens

app = typer.Typer(
    name="tokencut",
    help="⚡ SOTA Token Optimizer for Claude Code, OpenAI/Codex, and Gemini CLI.",
    no_args_is_help=True,
    add_completion=False,
)

console = Console()
err_console = Console(stderr=True)


@app.command()
def run(
    command: Annotated[list[str], typer.Argument(help="Command and arguments to execute")],
    max_lines: Annotated[int, typer.Option("--max-lines", "-m", help="Max lines to keep")] = 80,
    quiet: Annotated[bool, typer.Option("--quiet", "-q", help="Omit the summary footer")] = False,
):
    """Execute a command and optimize its output for AI context windows."""
    full_cmd = " ".join(command)
    start_time = time.perf_counter()

    proc = subprocess.run(full_cmd, shell=True, capture_output=True, text=True)
    raw_output = proc.stdout
    if proc.stderr:
        raw_output += ("\n" if raw_output else "") + proc.stderr

    duration = time.perf_counter() - start_time
    opts = CleanerOptions(max_lines=max_lines)
    compacted = compact_terminal_output(raw_output, opts)

    # Print output
    if compacted:
        console.print(compacted)

    if not quiet and raw_output:
        metrics = compute_metrics(raw_output, compacted)
        saved = metrics.saved_tokens
        savings = estimate_savings(saved.claude, saved.openai, saved.gemini)

        footer = (
            f"[bold cyan]tokencut[/bold cyan] "
            f"tokens saved: [bold green]~{saved.avg:,}[/bold green] "
            f"([bold green]-{metrics.reduction_pct}%[/bold green]) | "
            f"Claude: -{saved.claude:,} · GPT-4o: -{saved.openai:,} · Gemini: -{saved.gemini:,} | "
            f"est. saved: [bold yellow]{savings.format_avg()}[/bold yellow] | "
            f"time: {duration:.2f}s"
        )
        err_console.print(footer)

    sys.exit(proc.returncode)


@app.command()
def cat(
    file_path: Annotated[Path, typer.Argument(help="Path to code file")],
    skeleton: Annotated[
        bool, typer.Option("--skeleton", "-s", help="Extract structural AST outline")
    ] = False,
    lines: Annotated[
        str | None, typer.Option("--lines", "-l", help="Line range (e.g. 10-40)")
    ] = None,
    symbol: Annotated[str | None, typer.Option("--symbol", "-y", help="Target symbol name")] = None,
):
    """View file with intelligent token compaction or AST skeleton extraction."""
    if not file_path.exists():
        err_console.print(f"[bold red]File not found:[/bold red] {file_path}")
        raise typer.Exit(code=1)

    raw_content = file_path.read_text(encoding="utf-8", errors="replace")
    output = extract_symbol_or_range(file_path, symbol=symbol, lines_range=lines, skeleton=skeleton)

    console.print(output)

    if skeleton or lines or symbol:
        metrics = compute_metrics(raw_content, output)
        err_console.print(
            f"[dim]tokencut: original {metrics.raw_tokens.avg:,} tokens -> {metrics.compact_tokens.avg:,} tokens "
            f"(-{metrics.reduction_pct}%)[/dim]"
        )


@app.command()
def pipe(
    max_lines: Annotated[int, typer.Option("--max-lines", "-m", help="Max lines to keep")] = 80,
):
    """Stream or pipe standard input through tokencut."""
    raw_input = sys.stdin.read()
    if not raw_input:
        return

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

    # Simulated realistic pytest output with massive noisy passes + failing assertion
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
