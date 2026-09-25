"""Local savings analytics — what RTK calls ``gain``, without inventing billing claims."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from usagetrim.core.telemetry import TelemetryStore


@dataclass(frozen=True)
class OperationGain:
    operation: str
    events: int
    raw_openai: int
    compact_openai: int
    saved_openai: int
    reduction_pct: float
    passthrough: bool


@dataclass(frozen=True)
class GainEvent:
    timestamp: float
    operation: str
    raw_openai: int
    compact_openai: int
    saved_openai: int
    reduction_pct: float
    delivery: str


@dataclass(frozen=True)
class GainReport:
    total_events: int
    raw_openai: int
    compact_openai: int
    saved_openai: int
    reduction_pct: float
    by_operation: list[OperationGain]
    passthrough: list[OperationGain]
    history: list[GainEvent]

    def to_dict(self) -> dict:
        return {
            "total_events": self.total_events,
            "raw_openai": self.raw_openai,
            "compact_openai": self.compact_openai,
            "saved_openai": self.saved_openai,
            "reduction_pct": self.reduction_pct,
            "by_operation": [asdict(row) for row in self.by_operation],
            "passthrough": [asdict(row) for row in self.passthrough],
            "history": [asdict(row) for row in self.history],
            "measurement": "local output estimates, not model billing or subscription quota",
        }


def _pct(raw: int, compact: int) -> float:
    if raw <= 0:
        return 0.0
    return round(max(0.0, (raw - compact) / raw) * 100.0, 1)


def build_gain_report(
    store: TelemetryStore | None = None,
    *,
    history_limit: int = 20,
    passthrough_max_pct: float = 5.0,
) -> GainReport:
    """Aggregate telemetry into a gain report.

    ``passthrough`` means almost no reduction (≤ ``passthrough_max_pct``) —
    candidates for a new specialized cutter, like RTK's unchopped list.
    """
    store = store or TelemetryStore()
    with store.connect() as conn:
        rows = conn.execute(
            """
            SELECT operation,
                   COUNT(*),
                   COALESCE(SUM(raw_openai), 0),
                   COALESCE(SUM(compact_openai), 0)
            FROM events
            WHERE engine = 'usagetrim' AND delivery != 'prepared'
            GROUP BY operation
            ORDER BY (COALESCE(SUM(raw_openai), 0) - COALESCE(SUM(compact_openai), 0)) DESC,
                     operation ASC
            """
        ).fetchall()
        history_rows = conn.execute(
            """
            SELECT timestamp, operation,
                   COALESCE(raw_openai, 0), COALESCE(compact_openai, 0), delivery
            FROM events
            WHERE engine = 'usagetrim' AND delivery != 'prepared'
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (max(1, history_limit),),
        ).fetchall()

    by_operation: list[OperationGain] = []
    passthrough: list[OperationGain] = []
    total_raw = total_compact = total_events = 0
    for operation, events, raw, compact in rows:
        saved = max(0, int(raw) - int(compact))
        reduction = _pct(int(raw), int(compact))
        row = OperationGain(
            operation=operation or "unknown",
            events=int(events),
            raw_openai=int(raw),
            compact_openai=int(compact),
            saved_openai=saved,
            reduction_pct=reduction,
            passthrough=reduction <= passthrough_max_pct,
        )
        by_operation.append(row)
        if row.passthrough:
            passthrough.append(row)
        total_raw += int(raw)
        total_compact += int(compact)
        total_events += int(events)

    history = [
        GainEvent(
            timestamp=float(ts or 0),
            operation=op or "unknown",
            raw_openai=int(raw),
            compact_openai=int(compact),
            saved_openai=max(0, int(raw) - int(compact)),
            reduction_pct=_pct(int(raw), int(compact)),
            delivery=delivery or "returned",
        )
        for ts, op, raw, compact, delivery in history_rows
    ]

    return GainReport(
        total_events=total_events,
        raw_openai=total_raw,
        compact_openai=total_compact,
        saved_openai=max(0, total_raw - total_compact),
        reduction_pct=_pct(total_raw, total_compact),
        by_operation=by_operation,
        passthrough=passthrough,
        history=history,
    )
