"""Local JSON-lines companion service. No sockets, AI calls or transcript access."""

from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import sqlite3
import subprocess
import time
import tomllib
from pathlib import Path
from typing import Any

from tokencut.core.companion_state import settings, state_dir, update_settings
from tokencut.core.engines import TESTED_RTK, rtk_path, rtk_version
from tokencut.core.telemetry import EVENT_COLUMNS, TelemetryStore
from tokencut.core.usage import UsageCollector


def configuration() -> tuple[list[Path], dict, list[str]]:
    """Read only known MCP configuration files, never session transcripts."""
    home = Path.home()
    sources = {Path(os.environ.get("TOKENCUT_CACHE_DIR", str(home / ".tokencut")))}
    sources.add(home / ".tokencut")
    sources.update(Path(p) for p in settings().get("sources", []) if isinstance(p, str))
    clients: dict[str, list[str]] = {"tokencut": [], "serena": []}
    issues = []
    paths = {
        "codex": home / ".codex/config.toml",
        "claude-code": home / ".claude.json",
        "claude-desktop": home / "Library/Application Support/Claude/claude_desktop_config.json",
        "antigravity": home / ".gemini/antigravity/mcp_config.json",
    }
    for client, path in paths.items():
        if not path.exists():
            continue
        try:
            data = (
                tomllib.loads(path.read_text())
                if path.suffix == ".toml"
                else json.loads(path.read_text())
            )
            servers = data.get("mcp_servers" if client == "codex" else "mcpServers", {})
            if not isinstance(servers, dict):
                raise ValueError
            for tool in clients:
                entry = servers.get(tool)
                if (
                    not isinstance(entry, dict)
                    or entry.get("enabled") is False
                    or entry.get("disabled") is True
                ):
                    continue
                clients[tool].append(client)
                if tool == "tokencut":
                    cache = entry.get("env", {}).get("TOKENCUT_CACHE_DIR")
                    if isinstance(cache, str) and Path(cache).is_absolute():
                        sources.add(Path(cache))
        except (OSError, ValueError, TypeError, AttributeError):
            issues.append(f"Nie można odczytać konfiguracji: {client}")
    return sorted(sources), clients, issues


class Monitor:
    def __init__(self, sources: list[Path] | None = None, directory: Path | None = None):
        self.directory = directory or state_dir()
        self.store = TelemetryStore(self.directory / "metrics.db")
        self.sources = sources
        self.fingerprints: dict[str, tuple] = {}
        self.offsets: dict[str, tuple[int, int]] = {}
        self.last_check: dict | None = None
        self.configuration_cache: tuple | None = None
        self.configuration_at = 0.0
        self.usage = UsageCollector()

    def discover(self):
        if time.monotonic() - self.configuration_at >= 30 or self.configuration_cache is None:
            self.configuration_cache = configuration()
            self.configuration_at = time.monotonic()
        return self.configuration_cache

    def collect(self, sources: list[Path]) -> list[str]:
        issues = []
        for directory in sources:
            for name in ("cache.db", "telemetry.db"):
                path = directory / name
                try:
                    stat = path.stat()
                    wal = Path(str(path) + "-wal")
                    fingerprint = (
                        stat.st_ino,
                        stat.st_mtime_ns,
                        stat.st_size,
                        wal.stat().st_mtime_ns if wal.exists() else 0,
                    )
                    if self.fingerprints.get(str(path)) == fingerprint:
                        continue
                    if name == "cache.db":
                        # Only numeric legacy rows; never read output_cache.
                        self.store.import_legacy(path)
                    else:
                        with sqlite3.connect(
                            path.resolve().as_uri() + "?mode=ro", uri=True, timeout=0.1
                        ) as source:
                            inode, offset = self.offsets.get(str(path), (0, 0))
                            if inode != stat.st_ino:
                                offset = 0
                            maximum = (
                                source.execute("SELECT MAX(rowid) FROM events").fetchone()[0] or 0
                            )
                            rows = source.execute(
                                f"SELECT {','.join(EVENT_COLUMNS)} FROM events WHERE rowid > ?",
                                (offset,),
                            ).fetchall()
                        with self.store.connect() as dest:
                            dest.executemany(
                                f"INSERT OR IGNORE INTO events ({','.join(EVENT_COLUMNS)}) VALUES ({','.join('?' for _ in EVENT_COLUMNS)})",
                                rows,
                            )
                        self.offsets[str(path)] = (stat.st_ino, maximum)
                    self.fingerprints[str(path)] = fingerprint
                except FileNotFoundError:
                    continue
                except (OSError, sqlite3.Error):
                    issues.append(f"Źródło niedostępne: {path}")
        return issues

    @staticmethod
    def totals(rows: list[dict]) -> dict | None:
        if not rows:
            return None
        before = sum(r["raw_openai"] or 0 for r in rows)
        after = sum(r["compact_openai"] or 0 for r in rows)
        return {
            "before": before,
            "after": after,
            "net": before - after,
            "recovery": sum(r["compact_openai"] or 0 for r in rows if r["operation"] == "retrieve"),
            "events": len(rows),
        }

    def snapshot(self) -> dict:
        discovered, clients, issues = self.discover()
        sources = self.sources if self.sources is not None else discovered
        issues = list(issues) + self.collect(sources)
        today = dt.datetime.combine(dt.date.today(), dt.time()).astimezone()
        start_date = today.date() - dt.timedelta(days=6)
        start = dt.datetime.combine(start_date, dt.time()).astimezone()
        with self.store.connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM events WHERE timestamp >= ? ORDER BY timestamp",
                    (start.timestamp(),),
                )
            ]
            legacy = conn.execute(
                "SELECT COUNT(*), SUM(raw_openai - compact_openai) FROM events WHERE delivery='legacy'"
            ).fetchone()
            latest = {
                engine: conn.execute(
                    "SELECT MAX(timestamp) FROM events WHERE engine=? AND delivery IN ('returned','prepared')",
                    (engine,),
                ).fetchone()[0]
                for engine in ("tokencut", "rtk")
            }
            latest_code = conn.execute(
                "SELECT MAX(timestamp) FROM events WHERE engine='tokencut' AND operation='code' AND delivery='returned'"
            ).fetchone()[0]
        # Tokenizer methods and prepared hooks never enter the same total.
        measured = [
            r
            for r in rows
            if r["engine"] == "tokencut"
            and r["method"] == "o200k_base"
            and r["delivery"] == "returned"
        ]
        current = [r for r in measured if r["timestamp"] >= today.timestamp()]
        days = []
        for offset in range(7):
            date = start_date + dt.timedelta(days=offset)
            day = dt.datetime.combine(date, dt.time()).astimezone()
            end = dt.datetime.combine(date + dt.timedelta(days=1), dt.time()).astimezone()
            total = self.totals(
                [r for r in measured if day.timestamp() <= r["timestamp"] < end.timestamp()]
            )
            days.append({"date": day.date().isoformat(), "net": total["net"] if total else None})
        breakdown = {}
        for field in ("client", "project", "operation"):
            groups: dict[str, list] = {}
            for row in current:
                groups.setdefault(row[field] or "Nieprzypisane", []).append(row)
            breakdown[field] = [
                {"name": name, **self.totals(group)} for name, group in sorted(groups.items())
            ]
        rtk_today = [
            r
            for r in rows
            if r["engine"] == "rtk"
            and r["method"] == "bytes/4"
            and r["timestamp"] >= today.timestamp()
        ]
        prepared = [
            r
            for r in rows
            if r["delivery"] == "prepared"
            and r["method"] == "o200k_base"
            and r["timestamp"] >= today.timestamp()
        ]
        version = rtk_version()
        return {
            "schema_version": 1,
            "generated_at": time.time(),
            "paused": settings().get("paused") is True,
            "today": self.totals(current),
            "days": days,
            "breakdown": breakdown,
            "prepared": self.totals(prepared),
            "rtk": self.totals(rtk_today),
            "legacy": {"events": legacy[0], "net": legacy[1]},
            "other_method_events": sum(
                r["method"] not in {"o200k_base", "bytes/4", "legacy-estimate"} for r in rows
            ),
            "sources": [str(p) for p in sources],
            "issues": issues,
            "integrations": [
                {
                    "name": "TokenCut",
                    "installed": True,
                    "clients": clients["tokencut"],
                    "last_event": latest["tokencut"],
                    "detail": "CLI + MCP; hook Claude raportuje przygotowaną podmianę.",
                },
                {
                    "name": "TokenCut Code",
                    "installed": True,
                    "clients": clients["tokencut"],
                    "last_event": latest_code,
                    "detail": "Wbudowany indeks ast-grep + SQLite: symbole, mapa i wyszukiwanie. "
                    "Bez wywołań AI. Wystąpienia nazw nie są semantycznymi referencjami LSP.",
                },
                {
                    "name": "Serena",
                    "installed": bool(
                        shutil.which("serena") or (Path.home() / ".local/bin/serena").exists()
                    ),
                    "clients": clients["serena"],
                    "last_event": None,
                    "detail": "Niezależny MCP. Brak pomiaru oszczędności i aktywności sesji.",
                },
                {
                    "name": "RTK",
                    "installed": bool(rtk_path()),
                    "clients": ["TokenCut stdin adapter"] if version in TESTED_RTK else [],
                    "last_event": latest["rtk"],
                    "detail": f"{version or 'Niedostępny'} · bajty / 4 · osobny licznik. "
                    + (
                        "Auto: git status, git diff --stat; kontrola każdego wiersza."
                        if version in TESTED_RTK
                        else "Auto używa TokenCut; wersja RTK nie została zweryfikowana."
                    ),
                },
            ],
            "last_check": self.last_check,
        }

    def check(self) -> dict:
        """Check this executable via an isolated stdio MCP handshake, never change Serena's project."""
        import sys
        import tempfile

        with tempfile.TemporaryDirectory(prefix="tokencut-check-") as directory:
            messages = [
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "companion-check", "version": "1"},
                    },
                },
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {
                        "name": "tokencut_read",
                        "arguments": {"path": str(Path(directory) / "fixture.txt")},
                    },
                },
            ]
            Path(directory, "fixture.txt").write_text("TokenCut — test integracji ✓\n")
            env = os.environ | {
                "TOKENCUT_CACHE_DIR": directory,
                "TOKENCUT_STATE_DIR": directory,
                "TOKENCUT_CLIENT": "cli",
            }
            try:
                result = subprocess.run(
                    [sys.executable, "-m", "tokencut.cli", "mcp"],
                    input="".join(json.dumps(m) + "\n" for m in messages),
                    capture_output=True,
                    text=True,
                    timeout=15,
                    env=env,
                )
                replies = {
                    r.get("id"): r
                    for line in result.stdout.splitlines()
                    if isinstance(r := json.loads(line), dict)
                }
                ok = (
                    result.returncode == 0
                    and "result" in replies.get(1, {})
                    and {"tokencut_code", "tokencut_read", "tokencut_retrieve"}.issubset(
                        tool["name"]
                        for tool in replies.get(2, {}).get("result", {}).get("tools", [])
                    )
                    and "test integracji"
                    in json.dumps(replies.get(3, {}).get("result", {}), ensure_ascii=False)
                )
                self.last_check = {
                    "ok": ok,
                    "timestamp": time.time(),
                    "detail": "Lokalny MCP: initialize, tools/list, odczyt Unicode. Nie potwierdza podłączenia w otwartym kliencie.",
                }
            except (OSError, ValueError, subprocess.TimeoutExpired):
                self.last_check = {
                    "ok": False,
                    "timestamp": time.time(),
                    "detail": "Lokalny MCP nie odpowiedział poprawnie w 15 sekund.",
                }
        self.configuration_at = 0
        return self.last_check

    def dispatch(self, request: dict) -> Any:
        operation = request.get("method")
        if operation in {"usage", "usage-refresh"}:
            return {"providers": self.usage.snapshot(force=operation == "usage-refresh")}
        if operation == "snapshot":
            return self.snapshot()
        if operation == "pause":
            if type(request.get("paused")) is not bool:
                raise ValueError("paused must be boolean")
            update_settings(paused=request["paused"])
            return self.snapshot()
        if operation == "check":
            return self.check()
        if operation == "export":
            # Export only the public aggregate schema; no raw commands or output.
            return self.snapshot()
        raise ValueError("unknown method")

    def serve(self, stream, output):
        while line := stream.readline(65537):
            request = {}
            try:
                if len(line) > 65536:
                    # Drain a malformed overlong line without parsing its fragments.
                    while not line.endswith("\n") and (line := stream.readline(65537)):
                        pass
                    raise ValueError("request too large")
                request = json.loads(line)
                if not isinstance(request, dict):
                    raise ValueError("request must be an object")
                response = {"id": request.get("id"), "result": self.dispatch(request)}
            except Exception as exc:
                response = {
                    "id": request.get("id") if isinstance(request, dict) else None,
                    "error": type(exc).__name__,
                }
            output.write(json.dumps(response, ensure_ascii=False) + "\n")
            output.flush()
