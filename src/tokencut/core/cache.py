from __future__ import annotations

import hashlib
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

from tokencut.core.redactor import redact_secrets

DEFAULT_CACHE_DIR = Path.home() / ".tokencut"
DEFAULT_CACHE_DB = DEFAULT_CACHE_DIR / "cache.db"


class ContextCache:
    """Local SQLite-backed cache for Compress-Cache-Retrieve (CCR) architecture.

    Stored content is recoverable after recognized secrets have been redacted.
    An agent or developer can retrieve slices using the generated ref ID.
    """

    def __init__(self, db_path: Path | None = None):
        cache_dir = os.environ.get("TOKENCUT_CACHE_DIR")
        self.db_path = db_path or (Path(cache_dir) / "cache.db" if cache_dir else DEFAULT_CACHE_DB)
        self._ensure_db()

    def _ensure_db(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS output_cache (
                    ref_id TEXT PRIMARY KEY,
                    content_hash TEXT,
                    source TEXT,
                    content TEXT,
                    created_at REAL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_hash ON output_cache(content_hash)")
            conn.commit()

    def store(self, content: str, source: str = "exec", *, namespace: str = "") -> str:
        """Store redacted content and return a human-readable reference ID."""
        content = redact_secrets(content)
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        # Separate measurement owners without breaking existing stable refs.
        # Hash the digest, not a raw-text prefix (which could alias another log).
        ref_hash = (
            hashlib.sha256(f"{namespace}:{content_hash}".encode()).hexdigest()
            if namespace
            else content_hash
        )
        ref_id = f"tc_{ref_hash[:16]}"

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO output_cache (ref_id, content_hash, source, content, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (ref_id, content_hash, source, content, time.time()),
            )
            conn.commit()
        return ref_id

    def retrieve(self, ref_id: str, lines_range: str | None = None) -> str:
        """Retrieve stored content by ref ID, optionally slicing a line range."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT content, source FROM output_cache WHERE ref_id = ?",
                (ref_id,),
            ).fetchone()

        if not row:
            return f"Error: ref ID '{ref_id}' not found in tokencut cache."

        # Also protect entries written by older versions before cache redaction.
        content, source = redact_secrets(row[0]), row[1]
        if not lines_range:
            return content

        all_lines = content.splitlines()
        try:
            if "-" in lines_range:
                start_s, end_s = lines_range.split("-", 1)
                start, end = int(start_s), int(end_s)
            else:
                start = int(lines_range)
                end = start
            if start < 1 or end < start:
                raise ValueError
            end = min(len(all_lines), end)
            selected = all_lines[start - 1 : end]
            return (
                f"# [Retrieved {ref_id} ({source}) lines {start}-{end} of {len(all_lines)}]\n"
                + "\n".join(selected)
            )
        except ValueError:
            return "Error: lines must be a positive line number or an ascending range (e.g. 10-40)."

    def check_duplicate(self, content: str) -> str | None:
        """Check if identical content was cached recently within last 15 minutes."""
        content_hash = hashlib.sha256(redact_secrets(content).encode("utf-8")).hexdigest()
        cutoff = time.time() - 900  # 15 mins
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT ref_id FROM output_cache WHERE content_hash = ? AND created_at > ? ORDER BY created_at DESC LIMIT 1",
                (content_hash, cutoff),
            ).fetchone()
        return row[0] if row else None

    def clear(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM output_cache")
            conn.commit()

    def get_stats(self) -> dict[str, Any]:
        with sqlite3.connect(self.db_path) as conn:
            count = conn.execute("SELECT COUNT(*) FROM output_cache").fetchone()[0]
        size_kb = self.db_path.stat().st_size / 1024 if self.db_path.exists() else 0
        return {"count": count, "size_kb": size_kb, "path": str(self.db_path)}
