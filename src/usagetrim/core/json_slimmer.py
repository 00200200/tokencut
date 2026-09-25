from __future__ import annotations

import json
from typing import Any

from usagetrim.core.cache import ContextCache


def slim_json_data(
    data: Any,
    max_array_items: int = 3,
    max_string_len: int = 120,
    max_depth: int = 6,
    current_depth: int = 0,
) -> Any:
    """Recursively slim JSON structures by collapsing large arrays and long strings."""
    if current_depth >= max_depth:
        if isinstance(data, (dict, list)):
            return f"... [{len(data)} items omitted at max depth]"
        return data

    if isinstance(data, dict):
        result = {}
        for k, v in data.items():
            result[k] = slim_json_data(
                v,
                max_array_items=max_array_items,
                max_string_len=max_string_len,
                max_depth=max_depth,
                current_depth=current_depth + 1,
            )
        return result

    if isinstance(data, list):
        if len(data) <= max_array_items:
            return [
                slim_json_data(
                    item,
                    max_array_items=max_array_items,
                    max_string_len=max_string_len,
                    max_depth=max_depth,
                    current_depth=current_depth + 1,
                )
                for item in data
            ]

        kept = [
            slim_json_data(
                item,
                max_array_items=max_array_items,
                max_string_len=max_string_len,
                max_depth=max_depth,
                current_depth=current_depth + 1,
            )
            for item in data[:max_array_items]
        ]
        omitted_count = len(data) - max_array_items
        sample_item = data[0] if data else None
        hint = ""
        if isinstance(sample_item, dict):
            keys = list(sample_item.keys())[:4]
            hint = f" (sample keys: {keys})"
        kept.append(f"... {omitted_count} array items omitted by usagetrim{hint} ...")
        return kept

    if isinstance(data, str):
        if len(data) > max_string_len:
            omitted = len(data) - max_string_len
            return data[:max_string_len] + f"... [{omitted} chars omitted]"
        return data

    return data


def slim_json(
    text: str,
    max_array_items: int = 3,
    max_string_len: int = 120,
    max_depth: int = 6,
    cache_full: bool = True,
) -> str:
    """Parse and slim JSON text, caching full uncompressed data in SQLite CCR."""
    trimmed = text.strip()
    if not trimmed:
        return text

    try:
        parsed = json.loads(trimmed)
    except json.JSONDecodeError:
        return text

    slimmed = slim_json_data(
        parsed,
        max_array_items=max_array_items,
        max_string_len=max_string_len,
        max_depth=max_depth,
    )
    result_str = json.dumps(slimmed, indent=2)

    # If significant reduction, cache raw in CCR and inject reference
    if cache_full and len(text) > len(result_str) * 1.3:
        cache = ContextCache()
        ref_id = cache.store(text, source="json_slimmer")
        header = f"// [usagetrim: raw JSON ({len(text):,} bytes) compacted. Ref: {ref_id}]\n"
        return header + result_str

    return result_str
