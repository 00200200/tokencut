from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from tokencut.core.cache import DEFAULT_CACHE_DB
from tokencut.metrics.pricing import estimate_savings


@dataclass
class LifetimeStats:
    total_runs: int
    raw_claude_tokens: int
    compact_claude_tokens: int
    raw_openai_tokens: int
    compact_openai_tokens: int
    raw_gemini_tokens: int
    compact_gemini_tokens: int

    @property
    def saved_claude(self) -> int:
        return max(0, self.raw_claude_tokens - self.compact_claude_tokens)

    @property
    def saved_openai(self) -> int:
        return max(0, self.raw_openai_tokens - self.compact_openai_tokens)

    @property
    def saved_gemini(self) -> int:
        return max(0, self.raw_gemini_tokens - self.compact_gemini_tokens)

    @property
    def saved_avg(self) -> int:
        return (self.saved_claude + self.saved_openai + self.saved_gemini) // 3

    @property
    def reduction_pct(self) -> float:
        raw_avg = (self.raw_claude_tokens + self.raw_openai_tokens + self.raw_gemini_tokens) // 3
        if raw_avg == 0:
            return 0.0
        return round((self.saved_avg / raw_avg) * 100.0, 1)

    @property
    def estimated_usd_saved(self) -> float:
        savings = estimate_savings(self.saved_claude, self.saved_openai, self.saved_gemini)
        return savings.avg_saved_usd


class TelemetryStore:
    """Tracks local lifetime token savings in ~/.tokencut/cache.db."""

    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or DEFAULT_CACHE_DB
        self._ensure_table()

    def _ensure_table(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS telemetry_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL,
                    raw_claude INT,
                    compact_claude INT,
                    raw_openai INT,
                    compact_openai INT,
                    raw_gemini INT,
                    compact_gemini INT
                )
                """
            )
            conn.commit()

    def record(
        self,
        raw_claude: int,
        compact_claude: int,
        raw_openai: int,
        compact_openai: int,
        raw_gemini: int,
        compact_gemini: int,
    ):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO telemetry_events (
                    timestamp, raw_claude, compact_claude, raw_openai, compact_openai, raw_gemini, compact_gemini
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    time.time(),
                    raw_claude,
                    compact_claude,
                    raw_openai,
                    compact_openai,
                    raw_gemini,
                    compact_gemini,
                ),
            )
            conn.commit()

    def get_stats(self) -> LifetimeStats:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT
                    COUNT(*),
                    COALESCE(SUM(raw_claude), 0),
                    COALESCE(SUM(compact_claude), 0),
                    COALESCE(SUM(raw_openai), 0),
                    COALESCE(SUM(compact_openai), 0),
                    COALESCE(SUM(raw_gemini), 0),
                    COALESCE(SUM(compact_gemini), 0)
                FROM telemetry_events
                """
            ).fetchone()

        return LifetimeStats(
            total_runs=row[0],
            raw_claude_tokens=row[1],
            compact_claude_tokens=row[2],
            raw_openai_tokens=row[3],
            compact_openai_tokens=row[4],
            raw_gemini_tokens=row[5],
            compact_gemini_tokens=row[6],
        )

    def clear(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM telemetry_events")
            conn.commit()
