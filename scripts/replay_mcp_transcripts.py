"""Replay local Claude Code transcripts through the MCP output compactor.

Reads ~/.claude/projects/*/*.jsonl on this machine only, prints per-tool token
estimates before and after, and checks that every SQL result rewritten as TSV
decodes back to the original rows. Nothing is written or sent anywhere.

    uv run python scripts/replay_mcp_transcripts.py --days 14
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import time
from pathlib import Path

from usagetrim.core.mcp_output import MIN_CHARS, compact_mcp_text
from usagetrim.metrics.tokenizer import count_tokens

_BLOCK = re.compile(r"^<untrusted-data-([0-9a-f-]+)>\n(.*?)\n</untrusted-data-\1>$", re.S | re.M)


def _text(body) -> str:
    if isinstance(body, str):
        return body
    return "".join(x.get("text", "") for x in body or [] if isinstance(x, dict))


def _decode_tsv(block: str) -> list[dict]:
    keys, *lines = block.split("\n")[1:]
    keys = keys.split("\t")
    rows = []
    for line in lines:
        row = {}
        for key, cell in zip(keys, line.split("\t"), strict=True):
            try:
                row[key] = json.loads(cell)
            except ValueError:
                row[key] = cell
        rows.append(row)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=float, default=14)
    parser.add_argument("--root", type=Path, default=Path.home() / ".claude" / "projects")
    args = parser.parse_args()
    cutoff = time.time() - args.days * 86400

    before, after = collections.Counter(), collections.Counter()
    calls, rewritten = collections.Counter(), collections.Counter()
    tables = failures = 0
    for path in args.root.glob("*/*.jsonl"):
        if path.stat().st_mtime < cutoff:
            continue
        names: dict[str, str] = {}
        for line in path.open(errors="replace"):
            try:
                content = (json.loads(line).get("message") or {}).get("content")
            except (ValueError, AttributeError):
                continue
            for item in content if isinstance(content, list) else []:
                if not isinstance(item, dict):
                    continue
                if item.get("type") == "tool_use":
                    names[item.get("id")] = item.get("name") or ""
                    continue
                name = names.get(item.get("tool_use_id"), "")
                if item.get("type") != "tool_result" or not name.startswith("mcp__"):
                    continue
                if "usagetrim" in name.split("__")[1]:
                    continue
                tool, text = name.split("__")[-1], _text(item.get("content"))
                raw = count_tokens(text).claude if len(text) >= MIN_CHARS else len(text) // 4
                compact = compact_mcp_text(text)
                calls[tool] += 1
                before[tool] += raw
                after[tool] += count_tokens(compact).claude if compact else raw
                if not compact:
                    continue
                rewritten[tool] += 1
                if "JSON rows as TSV" in compact and "untrusted-data" in text:
                    tables += 1
                    source = json.loads(text).get("result", text)
                    original = [json.loads(body) for _, body in _BLOCK.findall(source)]
                    decoded = [_decode_tsv(body) for _, body in _BLOCK.findall(compact)]
                    failures += original != decoded

    total_before, total_after = sum(before.values()), sum(after.values())
    if not total_before:
        print("No MCP tool results found.")
        return
    print(
        f"{sum(calls.values()):,} MCP results: {total_before:,} -> {total_after:,} tokens "
        f"({1 - total_after / total_before:.1%} cut); SQL tables checked: {tables:,}, "
        f"round-trip failures: {failures}"
    )
    for tool, tokens in before.most_common(12):
        cut = 1 - after[tool] / tokens if tokens else 0
        print(f"  {tool:34} {calls[tool]:6,} calls  {tokens:10,} -> {after[tool]:10,}  {cut:6.1%}")


if __name__ == "__main__":
    main()
