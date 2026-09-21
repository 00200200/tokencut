"""Columnar and TOON (Token-Optimized Object Notation) table compressor for API and DB payloads."""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from typing import Any

from tokencut.core.cache import ContextCache
from tokencut.core.redactor import redact_secrets
from tokencut.metrics.tokenizer import count_tokens


@dataclass
class TableResult:
    original_tokens: int
    compacted_tokens: int
    saved_tokens: int
    reduction_pct: float
    ref_id: str | None
    row_count: int
    column_count: int
    columns: list[str]
    text: str
    format_type: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "original_tokens": self.original_tokens,
            "compacted_tokens": self.compacted_tokens,
            "saved_tokens": self.saved_tokens,
            "reduction_pct": self.reduction_pct,
            "ref_id": self.ref_id,
            "row_count": self.row_count,
            "column_count": self.column_count,
            "columns": self.columns,
            "text": self.text,
            "format_type": self.format_type,
        }


def _parse_tabular_input(raw: str) -> tuple[list[str], list[list[str]]]:
    """Parse JSON or CSV/TSV into headers and row values."""
    trimmed = raw.strip()

    # 1. Try parsing JSON
    if (trimmed.startswith("[") and trimmed.endswith("]")) or (
        trimmed.startswith("{") and trimmed.endswith("}")
    ):
        try:
            parsed = json.loads(trimmed)
            records: list[dict[str, Any]] = []
            if isinstance(parsed, list):
                if all(isinstance(x, dict) for x in parsed):
                    records = parsed
            elif isinstance(parsed, dict):
                # Search for primary list attribute (e.g. "items", "data", "results", "users")
                for key in ("items", "data", "results", "rows", "records", "users", "entries"):
                    val = parsed.get(key)
                    if isinstance(val, list) and val and all(isinstance(x, dict) for x in val):
                        records = val
                        break
                if not records:
                    for val in parsed.values():
                        if isinstance(val, list) and val and all(isinstance(x, dict) for x in val):
                            records = val
                            break

            if records:
                # Collect unified ordered keys
                keys: list[str] = []
                for rec in records:
                    for k in rec.keys():
                        if k not in keys:
                            keys.append(str(k))
                rows: list[list[str]] = []
                for rec in records:
                    rows.append([str(rec.get(k, "")) for k in keys])
                return keys, rows
        except Exception:
            pass

    # 2. Try parsing CSV / TSV
    delimiter = "\t" if "\t" in trimmed and "," not in trimmed else ","
    try:
        reader = csv.reader(io.StringIO(trimmed), delimiter=delimiter)
        csv_rows = list(reader)
        if len(csv_rows) >= 2 and all(len(r) == len(csv_rows[0]) for r in csv_rows[:10]):
            headers = [h.strip() for h in csv_rows[0]]
            data_rows = [[c.strip() for c in r] for r in csv_rows[1:]]
            return headers, data_rows
    except Exception:
        pass

    return [], []


def compact_table(
    raw_input: str,
    budget: int = 2000,
    format_type: str = "toon",
) -> TableResult:
    """Convert JSON object arrays or CSV data into token-efficient TOON or markdown table."""
    redacted = redact_secrets(raw_input)
    original_tokens = count_tokens(redacted).openai

    headers, rows = _parse_tabular_input(redacted)
    if not headers or not rows:
        # Fallback to returning original text if tabular parsing fails
        return TableResult(
            original_tokens=original_tokens,
            compacted_tokens=original_tokens,
            saved_tokens=0,
            reduction_pct=0.0,
            ref_id=None,
            row_count=0,
            column_count=0,
            columns=[],
            text=redacted,
            format_type="raw",
        )

    cache = ContextCache()
    ref_id = cache.store(redacted, source="table-compaction")

    # Format into TOON or Markdown
    def _render(kept_rows: list[list[str]], omitted: int = 0) -> str:
        lines: list[str] = []
        if format_type.lower() == "markdown":
            lines.append("| " + " | ".join(headers) + " |")
            lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
            for r in kept_rows:
                lines.append("| " + " | ".join(r) + " |")
        else:
            # TOON (Token-Optimized Object Notation)
            lines.append("[" + " | ".join(headers) + "]")
            for r in kept_rows:
                lines.append(" | ".join(r))

        if omitted > 0:
            lines.append(
                f"\n[... {omitted} rows omitted to fit token budget. Ref: {ref_id} - tokencut retrieve {ref_id} ...]"
            )
        return "\n".join(lines)

    full_rendered = _render(rows)
    current_tokens = count_tokens(full_rendered).openai

    # Budget enforcement loop
    kept_rows = list(rows)
    omitted = 0
    if current_tokens > budget and len(rows) > 4:
        target_rows = max(4, int(len(rows) * (budget / current_tokens) * 0.8))
        head_count = target_rows // 2
        tail_count = target_rows - head_count
        head = rows[:head_count]
        tail = rows[-tail_count:] if tail_count > 0 else []
        omitted = len(rows) - len(head) - len(tail)
        kept_rows = head + tail
        full_rendered = _render(kept_rows, omitted=omitted)
        current_tokens = count_tokens(full_rendered).openai

        while current_tokens > budget and len(kept_rows) > 4:
            if len(head) >= len(tail) and head:
                head.pop()
            elif tail:
                tail.pop(0)
            omitted = len(rows) - len(head) - len(tail)
            kept_rows = head + tail
            full_rendered = _render(kept_rows, omitted=omitted)
            current_tokens = count_tokens(full_rendered).openai

    saved = max(0, original_tokens - current_tokens)
    pct = round((saved / original_tokens) * 100, 1) if original_tokens else 0.0

    return TableResult(
        original_tokens=original_tokens,
        compacted_tokens=current_tokens,
        saved_tokens=saved,
        reduction_pct=pct,
        ref_id=ref_id,
        row_count=len(rows),
        column_count=len(headers),
        columns=headers,
        text=full_rendered,
        format_type=format_type,
    )
