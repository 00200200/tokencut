from usagetrim.core.cleaner import (
    CleanerOptions,
    compact_terminal_output,
    deduplicate_repetitive_lines,
    resolve_carriage_returns,
    strip_ansi,
)


def test_strip_ansi():
    ansi_str = "\x1b[31;1mERROR:\x1b[0m Failed with \x1b[32mstatus 500\x1b[0m\x1b[?25h"
    cleaned = strip_ansi(ansi_str)
    assert cleaned == "ERROR: Failed with status 500"


def test_resolve_carriage_returns():
    progress = "Downloading... 10%\rDownloading... 50%\rDownloading... 100%\nDone!"
    resolved = resolve_carriage_returns(progress)
    assert "Downloading... 10%" not in resolved
    assert "Downloading... 100%" in resolved
    assert "Done!" in resolved


def test_deduplicate_repetitive_lines():
    lines = [
        "Building chunk 1",
        "Warning: unused var",
        "Warning: unused var",
        "Warning: unused var",
        "Warning: unused var",
        "Done chunk 1",
    ]
    res = deduplicate_repetitive_lines(lines, max_consecutive=2)
    assert len(res) < len(lines)
    assert any("identical lines omitted" in line for line in res)


def test_compact_terminal_output_preserves_error():
    # Build 100 lines of noise followed by a Python traceback
    routine = [f"Step {i}: processing item {i}..." for i in range(1, 101)]
    error = [
        "Traceback (most recent call last):",
        '  File "main.py", line 42, in calculate',
        "    return 100 / divisor",
        "ZeroDivisionError: division by zero",
    ]
    full_output = "\n".join(routine + error)

    opts = CleanerOptions(max_lines=30, head_lines=10, tail_lines=20, preserve_errors=True)
    compacted = compact_terminal_output(full_output, opts)

    # Must preserve first steps
    assert "Step 1: processing item 1..." in compacted
    # Must preserve the exact error
    assert "Traceback (most recent call last):" in compacted
    assert "ZeroDivisionError: division by zero" in compacted
    # Must omit middle routine steps
    assert "lines of routine output omitted by usagetrim" in compacted


def test_compact_terminal_output_no_error():
    lines = [f"Item {i}" for i in range(1, 150)]
    full_output = "\n".join(lines)
    opts = CleanerOptions(max_lines=30, head_lines=10, tail_lines=10, preserve_errors=True)
    compacted = compact_terminal_output(full_output, opts)

    assert "Item 1" in compacted
    assert "Item 149" in compacted
    assert "lines omitted by usagetrim" in compacted
