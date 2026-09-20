"""Deterministic local navigation fixture, optionally against installed Serena.

No AI calls. Counts returned text and separately reports tool discovery costs.
This is not a model/task-quality, billing or subscription-quota benchmark.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from tokencut.core.code_index import digest
from tokencut.core.symbol_edit import replace_symbol
from tokencut.mcp.server import (
    TOOLS_DEFINITIONS,
    _respond,
    handle_tokencut_code,
    handle_tokencut_read,
)
from tokencut.metrics.tokenizer import count_tokens


def tokens(text):
    return count_tokens(text).openai


async def serena_probe(executable, root, home):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(
        command=executable,
        args=[
            "start-mcp-server",
            "--context=codex",
            "--project",
            str(root),
            "--enable-web-dashboard=false",
            "--open-web-dashboard=false",
            "--log-level=ERROR",
        ],
        env=os.environ | {"SERENA_HOME": str(home)},
    )
    with (home.parent / "serena-stderr.log").open("w") as errors:
        async with stdio_client(params, errlog=errors) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                schema = await session.list_tools()
                instructions = await session.call_tool("initial_instructions", {})
                result = await session.call_tool(
                    "find_symbol",
                    {
                        "name_path_pattern": "Service73/run",
                        "relative_path": "services.py",
                        "include_body": True,
                    },
                )
                text = "\n".join(c.text for c in result.content if hasattr(c, "text"))
                instruction_text = "\n".join(
                    c.text for c in instructions.content if hasattr(c, "text")
                )
                ok = (
                    not result.model_dump(by_alias=True).get("isError", False)
                    and "Service73/run" in text
                    and "important comment" in text
                )
                return {
                    "passed": ok,
                    "failure": text[:1200] if not ok else None,
                    "returned_tokens": tokens(text),
                    "discovery_tokens": tokens(
                        json.dumps(
                            [t.model_dump(exclude_none=True, by_alias=True) for t in schema.tools],
                            separators=(",", ":"),
                        )
                    ),
                    "instruction_tokens": tokens(instruction_text),
                    "tool_count": len(schema.tools),
                }


def benchmark(serena=None):
    with TemporaryDirectory(prefix="tokencut-code-benchmark-") as directory:
        folder = Path(directory)
        root = folder / "project"
        root.mkdir()
        source = "\n\n".join(
            f"class Service{i}:\n    def run(self, value):\n        # important comment {i}\n"
            f'        if value < 0:\n            raise ValueError("negative input")\n'
            f"        return value + {i}\n"
            for i in range(100)
        )
        path = root / "services.py"
        path.write_text(source)
        with patch.dict(
            os.environ,
            {
                "TOKENCUT_CACHE_DIR": str(folder / "cache"),
                "TOKENCUT_STATE_DIR": str(folder / "state"),
            },
        ):
            start = time.perf_counter()
            found = handle_tokencut_code(
                {"root": str(root), "mode": "symbols", "query": "Service73.run"}
            )
            cold_ms = (time.perf_counter() - start) * 1000
            start = time.perf_counter()
            warm = handle_tokencut_code(
                {"root": str(root), "mode": "symbols", "query": "Service73.run"}
            )
            warm_ms = (time.perf_counter() - start) * 1000
            body = handle_tokencut_read({"path": str(path), "symbol": "Service73.run"})
            assert "important comment 73" in body and "return value + 73" in body
            assert "0 reindexed" in warm
            replacement = (
                "    def run(self, value):\n        # important comment 73\n"
                '        if value < 0:\n            raise ValueError("negative input")\n'
                "        return value + 74"
            )
            preview = replace_symbol(path, "Service73.run", replacement, digest(source))
            assert path.read_text() == source and "+        return value + 74" in preview
            # Isolated fixture only: verify target changes while its neighbors do not.
            replace_symbol(path, "Service73.run", replacement, digest(source), apply=True)
            namespace = {}
            exec(compile(path.read_text(), str(path), "exec"), namespace)
            assert namespace["Service73"]().run(1) == 75
            assert namespace["Service72"]().run(1) == 73
            path.write_text(source)  # Serena sees the identical original fixture.
            report = {
                "fixture": "100 Python classes; locate/read Service73.run and separately verify guarded edit",
                "method": "o200k_base estimates; no model calls; not task quality or quota",
                "raw_full_file_tokens": tokens(source),
                "tokencut": {
                    "passed": True,
                    "query_and_read_tokens": tokens(found) + tokens(body),
                    "read_only_tokens": tokens(body),
                    "edit_preview_tokens": tokens(preview),
                    "discovery_tokens": tokens(
                        json.dumps(TOOLS_DEFINITIONS, separators=(",", ":"))
                    ),
                    "instruction_tokens": tokens(
                        _respond({"jsonrpc": "2.0", "id": 1, "method": "initialize"})["result"][
                            "instructions"
                        ]
                    ),
                    "tool_count": len(TOOLS_DEFINITIONS),
                    "cold_query_ms": round(cold_ms, 2),
                    "warm_query_ms": round(warm_ms, 2),
                },
                "serena": None,
            }
            if serena:
                try:
                    report["serena"] = asyncio.run(
                        asyncio.wait_for(serena_probe(serena, root, folder / "serena"), timeout=90)
                    )
                except Exception as exc:
                    failures = [exc]
                    while any(isinstance(error, BaseExceptionGroup) for error in failures):
                        failures = [
                            nested
                            for error in failures
                            for nested in (
                                error.exceptions
                                if isinstance(error, BaseExceptionGroup)
                                else [error]
                            )
                        ]
                    report["serena"] = {
                        "passed": False,
                        "error_type": type(exc).__name__,
                        "errors": [str(error)[:300] for error in failures],
                        "comparison_valid": False,
                    }
            print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serena", help="Optional absolute path to installed Serena executable")
    benchmark(parser.parse_args().serena)
