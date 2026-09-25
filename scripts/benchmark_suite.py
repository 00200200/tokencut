from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from rich.console import Console
from rich.table import Table

from usagetrim.core.cache import ContextCache
from usagetrim.core.cleaner import CleanerOptions, compact_terminal_output
from usagetrim.core.diff_slimmer import slim_git_diff
from usagetrim.core.safe_filter import safe_compact_output
from usagetrim.core.skeleton import skeletonize_python
from usagetrim.mcp.server import TOOLS_DEFINITIONS, handle_usagetrim_read, tool_definitions
from usagetrim.metrics.tokenizer import compute_metrics

console = Console()


def run_benchmarks(json_output: bool = False):
    # Fixtures must not populate the user's cache or lifetime usage statistics.
    with TemporaryDirectory(prefix="usagetrim-benchmark-") as directory:
        with patch.dict(os.environ, {"USAGETRIM_CACHE_DIR": directory}):
            _run_benchmarks(json_output)


def _run_benchmarks(json_output: bool):
    # Scenario 1: Pytest failure log with 120 tests
    pytest_raw = "pytest -v tests/\n" + "\n".join(
        [f"tests/test_{i}.py::test_{i} PASSED [ {i % 100}%]" for i in range(1, 120)]
    )
    failure_tail = """
=================================== FAILURES ===================================
________________________________ test_database _________________________________
def test_database():
    conn = db.get_connection()
>   assert conn.ping() is True
E   ConnectionRefusedError: [Errno 61] Connection refused
tests/test_db.py:88: ConnectionRefusedError
=========================== short test summary info ============================
FAILED tests/test_db.py::test_database - ConnectionRefusedError
======================== 1 failed, 119 passed in 4.12s =========================
"""
    pytest_raw += failure_tail
    pytest_compact = compact_terminal_output(pytest_raw, CleanerOptions(max_lines=30))
    m_pytest = compute_metrics(pytest_raw, pytest_compact)

    # Safe mode must preserve the entire diagnostic region, including repeated
    # lines and text that resembles progress records inside captured output.
    safe_failure_tail = failure_tail.replace(
        "tests/test_db.py:88: ConnectionRefusedError\n",
        "tests/test_db.py:88: ConnectionRefusedError\n"
        "-------------------------- Captured stdout call --------------------------\n"
        + "database unavailable; retry still pending\n" * 80
        + "tests/test_mock.py::test_payload PASSED [100%]\n",
    )
    safe_pytest_raw = pytest_raw.replace(failure_tail, safe_failure_tail)
    safe_pytest = safe_compact_output(safe_pytest_raw, command="pytest -v tests/", exit_code=1)
    m_safe_pytest = compute_metrics(safe_pytest_raw, safe_pytest)
    safe_ref = re.search(r"tc_[0-9a-f]{16}", safe_pytest)
    safe_tail_preserved = safe_failure_tail in safe_pytest
    safe_recovery_exact = bool(
        safe_ref and ContextCache().retrieve(safe_ref.group()) == safe_pytest_raw
    )

    # Scenario 2: Webpack / Vite build logs with ANSI and spinners
    build_raw = "\x1b[36mvite v5.4.0 building for production...\x1b[0m\n"
    build_raw += "\n".join(
        [f"transforming ({i}/250) src/components/Widget_{i}.tsx" for i in range(1, 251)]
    )
    build_raw += """
✓ 250 modules transformed.
dist/index.html                   0.45 kB │ gzip:  0.29 kB
dist/assets/index-D8s27k.css      4.12 kB │ gzip:  1.42 kB
dist/assets/index-B7x90q.js     142.80 kB │ gzip: 45.20 kB
✓ built in 1420ms
"""
    build_compact = compact_terminal_output(build_raw, CleanerOptions(max_lines=25))
    m_build = compute_metrics(build_raw, build_compact)

    # Scenario 3: Python AST Skeleton on full codebase file
    cli_content = Path("src/usagetrim/cli.py").read_text()
    skeleton_content = skeletonize_python(cli_content)
    m_skel = compute_metrics(cli_content, skeleton_content)

    # Scenario 4: Git diff with lockfile
    diff_raw = """diff --git a/src/core.py b/src/core.py
index 1111111..2222222 100644
--- a/src/core.py
+++ b/src/core.py
@@ -10,6 +10,7 @@ def process():
     context_a
     context_b
+    enable_caching()
     context_c
diff --git a/uv.lock b/uv.lock
index 3333333..4444444 100644
--- a/uv.lock
+++ b/uv.lock
""" + "\n".join([f"+ lock_dep_{i} = '1.0.{i}'" for i in range(300)])
    diff_compact = slim_git_diff(diff_raw)
    m_diff = compute_metrics(diff_raw, diff_compact)

    # A line limit alone cannot bound this fixture. Measure MCP content JSON too.
    long_raw = "payload_field=abcdefghijk " * 2500
    with TemporaryDirectory() as directory:
        path = Path(directory) / "long.txt"
        path.write_text(long_raw)
        long_compact = handle_usagetrim_read({"path": str(path), "max_tokens": 2000})

    def envelope(text: str) -> str:
        return json.dumps({"content": [{"type": "text", "text": text}]})

    m_mcp = compute_metrics(envelope(long_raw), envelope(long_compact))
    safe_unknown = safe_compact_output(long_raw, command="example-tool", exit_code=0)
    m_safe_unknown = compute_metrics(long_raw, safe_unknown)

    scenarios = [
        ("Pytest compact mode (120 tests, 1 failure)", m_pytest),
        ("Pytest safe mode (complete long failure tail)", m_safe_pytest),
        ("Vite/Webpack Build Log (250 modules)", m_build),
        ("Source Code Inspection (AST Skeleton)", m_skel),
        ("Git Diff with modified lockfile", m_diff),
        ("MCP long-line read (content JSON)", m_mcp),
        ("Safe unknown output (intentional pass-through)", m_safe_unknown),
    ]

    checks = [
        all(
            s in pytest_compact
            for s in ("assert conn.ping() is True", "tests/test_db.py:88", "1 failed, 119 passed")
        ),
        safe_tail_preserved and safe_recovery_exact,
        all(s in build_compact for s in ("250 modules transformed", "built in 1420ms")),
        all(s in skeleton_content for s in ("def run(", "def main(")),
        "+    enable_caching()" in diff_compact and "uv.lock" in diff_compact,
        "Ref: tc_" in long_compact
        and compute_metrics("", long_compact).compact_tokens.claude <= 2000,
        safe_unknown == long_raw,
    ]
    if not all(checks):
        raise AssertionError("A fixture lost a required diagnostic or signature")
    if json_output:
        print(
            json.dumps(
                {
                    "measurement": "local token estimates; authored fixtures, not agent evaluations",
                    "quality_evaluated": False,
                    "safe_failure_tail_preserved_exactly": safe_tail_preserved,
                    "safe_cached_original_recovered_exactly": safe_recovery_exact,
                    "tool_schema_o200k_tokens": compute_metrics(
                        "", json.dumps(TOOLS_DEFINITIONS)
                    ).compact_tokens.openai,
                    "coding_tool_schema_o200k_tokens": compute_metrics(
                        "", json.dumps(tool_definitions("coding"))
                    ).compact_tokens.openai,
                    "scenarios": [
                        {
                            "name": name,
                            "raw_tokens": m.raw_tokens.avg,
                            "output_tokens": m.compact_tokens.avg,
                            "reduction_pct": m.reduction_pct,
                            "fixture_check_passed": passed,
                        }
                        for (name, m), passed in zip(scenarios, checks, strict=True)
                    ],
                },
                indent=2,
            )
        )
        return

    table = Table(title="usagetrim authored fixture benchmarks (local token estimates)")
    table.add_column("Workload / Scenario", style="cyan")
    table.add_column("Raw Tokens", style="red")
    table.add_column("usagetrim Tokens", style="green")
    table.add_column("Token Reduction", style="bold yellow")
    table.add_column("Fixture check", style="magenta")

    for name, m in scenarios:
        table.add_row(
            name,
            f"{m.raw_tokens.avg:,}",
            f"{m.compact_tokens.avg:,}",
            f"-{m.reduction_pct}%",
            "Passed",
        )

    console.print(table)
    console.print("Safe pytest: full failure tail preserved; cached original recovered exactly.")
    console.print(
        "Tool schema overhead (local o200k estimate): "
        f"{compute_metrics('', json.dumps(TOOLS_DEFINITIONS)).compact_tokens.openai:,} tokens."
    )
    console.print(
        "Model quality, subscription quotas, and end-to-end task tokens were not evaluated."
    )
    console.print(
        "Coding profile schema (local o200k estimate): "
        f"{compute_metrics('', json.dumps(tool_definitions('coding'))).compact_tokens.openai:,} tokens."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run local fixture measurements without model calls."
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable fixture results")
    run_benchmarks(json_output=parser.parse_args().json)
