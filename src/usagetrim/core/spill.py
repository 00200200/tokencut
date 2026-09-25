"""Spill oversized command output to disk and return a short preview + recovery ref.

Mirrors the Copilot CLI pattern: large tool results become a file path + preview
instead of flooding the context window.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path

from usagetrim.core.cache import ContextCache
from usagetrim.core.redactor import redact_secrets

# Copilot CLI defaults to ~20 KiB for large tool output externalization.
DEFAULT_SPILL_BYTES = 20 * 1024
_PREVIEW_HEAD = 24
_PREVIEW_TAIL = 24


@dataclass(frozen=True)
class SpillResult:
    path: Path
    ref_id: str
    preview: str
    bytes_written: int


def spill_threshold_bytes() -> int:
    raw = os.environ.get("USAGETRIM_SPILL_BYTES", str(DEFAULT_SPILL_BYTES))
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_SPILL_BYTES
    return value if value > 0 else DEFAULT_SPILL_BYTES


def spill_large_output(
    text: str,
    *,
    spill_dir: Path | None = None,
    threshold: int | None = None,
    source: str = "spill",
    cache: ContextCache | None = None,
) -> SpillResult | None:
    """If ``text`` exceeds the byte threshold, write it and return a compact preview.

    Returns ``None`` when the payload is small enough to keep inline.
    """
    if not text:
        return None
    limit = spill_threshold_bytes() if threshold is None else threshold
    if limit <= 0:
        return None
    raw_bytes = text.encode("utf-8", errors="replace")
    if len(raw_bytes) < limit:
        return None

    redacted = redact_secrets(text)
    cache = cache or ContextCache()
    ref_id = cache.store(redacted, source=source)

    base = spill_dir
    if base is None:
        cache_dir = Path(os.environ.get("USAGETRIM_CACHE_DIR", str(Path.home() / ".usagetrim")))
        base = cache_dir / "spill"
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"{ref_id}_{int(time.time())}.txt"
    path.write_text(redacted, encoding="utf-8")

    lines = redacted.splitlines(keepends=True)
    if len(lines) <= _PREVIEW_HEAD + _PREVIEW_TAIL:
        body = redacted
    else:
        body = "".join(lines[:_PREVIEW_HEAD] + lines[-_PREVIEW_TAIL:])
    preview = (
        f"[UsageTrim spill: {len(raw_bytes):,} bytes → {path}]\n"
        f"[UsageTrim: full redacted output: usagetrim retrieve {ref_id}]\n"
        f"{body}"
    )
    if not preview.endswith("\n"):
        preview += "\n"
    return SpillResult(
        path=path,
        ref_id=ref_id,
        preview=preview,
        bytes_written=len(raw_bytes),
    )
