"""Read-only quota adapters. No prompts, transcript scans or credential parsing.

Codex owns its authentication through app-server; CodexBar queries Claude CLI.
Only normalized quota counters live in memory, separate from savings telemetry.
"""

from __future__ import annotations

import copy
import datetime as dt
import json
import math
import os
import selectors
import shutil
import signal
import subprocess
import threading
import time
from pathlib import Path

MAX_RESPONSE = 1024 * 1024


def executable(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    for folder in (Path.home() / ".local/bin", Path("/opt/homebrew/bin"), Path("/usr/local/bin")):
        candidate = folder / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def number(value):
    return value if type(value) in (int, float) and math.isfinite(value) else None


def timestamp(value):
    if number(value) is not None:
        return float(value)
    if isinstance(value, str):
        try:
            parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.timestamp() if parsed.tzinfo else None
        except ValueError:
            pass
    return None


def window(value, key: str, bucket: str = "") -> dict | None:
    if not isinstance(value, dict) or number(value.get("usedPercent")) is None:
        return None
    used = max(0.0, min(100.0, float(value["usedPercent"])))
    minutes = number(value.get("windowDurationMins", value.get("windowMinutes")))
    if minutes is not None and minutes <= 0:
        minutes = None
    if minutes == 10080:
        label = "Tydzień"
    elif minutes == 300:
        label = "5 godzin"
    elif minutes is not None:
        label = f"{minutes / 60:g} h" if minutes % 60 == 0 else f"{minutes:g} min"
    else:
        label = {
            "primary": "Główne okno",
            "secondary": "Drugie okno",
            "tertiary": "Dodatkowe okno",
        }.get(key, key)
    if bucket:
        label = f"{bucket[:60]} · {label}"
    return {
        "id": f"{bucket}:{key}",
        "label": label,
        "used_percent": used,
        "remaining_percent": 100.0 - used,
        "window_minutes": minutes,
        "resets_at": timestamp(value.get("resetsAt")),
    }


def codex_windows(payload: dict) -> list[dict]:
    buckets = payload.get("rateLimitsByLimitId")
    if not isinstance(buckets, dict) or not buckets:
        legacy = payload.get("rateLimits")
        buckets = {"codex": legacy} if isinstance(legacy, dict) else {}
    result = []
    for name, bucket in buckets.items():
        if not isinstance(bucket, dict):
            continue
        label = str(bucket.get("limitName") or name) if name != "codex" else ""
        for key in ("primary", "secondary"):
            item = window(bucket.get(key), key, label)
            if item:
                result.append(item)
    return result


def stop_process(process):
    # All subprocesses have their own group. Never signal the user's other clients.
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    except PermissionError:
        process.terminate()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except PermissionError:
            process.kill()
        process.wait(timeout=2)


class JsonPipe:
    def __init__(self, process, timeout=15):
        self.process = process
        self.deadline = time.monotonic() + timeout
        self.buffer = b""
        self.total = 0

    def send(self, value):
        self.process.stdin.write((json.dumps(value) + "\n").encode())
        self.process.stdin.flush()

    def response(self, identity):
        with selectors.DefaultSelector() as selector:
            selector.register(self.process.stdout, selectors.EVENT_READ)
            while True:
                while b"\n" in self.buffer:
                    line, self.buffer = self.buffer.split(b"\n", 1)
                    message = json.loads(line)
                    if isinstance(message, dict) and message.get("id") == identity:
                        if "error" in message or not isinstance(message.get("result"), dict):
                            raise ValueError("Quota request failed")
                        return message["result"]
                remaining = self.deadline - time.monotonic()
                if remaining <= 0 or not selector.select(remaining):
                    raise TimeoutError("Quota timeout")
                chunk = os.read(self.process.stdout.fileno(), 65536)
                if not chunk:
                    raise ValueError("Quota process ended")
                self.total += len(chunk)
                if self.total > MAX_RESPONSE:
                    raise ValueError("Quota response too large")
                self.buffer += chunk


def fetch_codex() -> list[dict]:
    command = executable("codex")
    if not command:
        raise FileNotFoundError("codex")
    process = subprocess.Popen(
        [command, "app-server", "--listen", "stdio://"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        cwd=Path.home(),
        start_new_session=True,
    )
    try:
        pipe = JsonPipe(process)
        pipe.send(
            {
                "id": 1,
                "method": "initialize",
                "params": {"clientInfo": {"name": "tokencut-usage", "version": "0.1.0"}},
            }
        )
        pipe.response(1)
        pipe.send({"method": "initialized", "params": {}})
        pipe.send({"id": 2, "method": "account/rateLimits/read", "params": {}})
        return codex_windows(pipe.response(2))
    finally:
        stop_process(process)
        process.stdin.close()
        process.stdout.close()


def claude_windows(payload) -> list[dict]:
    entries = payload if isinstance(payload, list) else [payload]
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("provider") != "claude" or entry.get("error"):
            continue
        usage = entry.get("usage")
        if not isinstance(usage, dict):
            continue
        return [
            item
            for key in ("primary", "secondary", "tertiary")
            if (item := window(usage.get(key), key)) is not None
        ]
    return []


def fetch_claude() -> list[dict]:
    command = executable("codexbar")
    if not command:
        raise FileNotFoundError("codexbar")
    environment = dict(os.environ)
    if claude := executable("claude"):
        environment.setdefault("CLAUDE_CLI_PATH", claude)
    # Explicit CLI source avoids browser cookie import and foreign Keychain reads.
    # Never invoke `cost`, which scans session transcripts, or any model prompt.
    process = subprocess.Popen(
        [
            command,
            "usage",
            "--provider",
            "claude",
            "--source",
            "cli",
            "--format",
            "json",
            "--json-only",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        cwd=Path.home(),
        env=environment,
        start_new_session=True,
    )
    data = bytearray()
    try:
        deadline = time.monotonic() + 30
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not selector.select(remaining):
                    raise TimeoutError("Claude quota timeout")
                chunk = os.read(process.stdout.fileno(), 65536)
                if not chunk:
                    break
                data.extend(chunk)
                if len(data) > MAX_RESPONSE:
                    raise ValueError("Quota response too large")
        return claude_windows(json.loads(data))
    finally:
        stop_process(process)
        process.stdout.close()


class UsageCollector:
    """Refresh each provider independently, no more than every five minutes.

    Manual refresh has a 30-second floor. No disk cache: old account data is not
    silently restored at launch. Failed refreshes clear percentages immediately.
    """

    def __init__(self, fetchers=None, clock=time.monotonic):
        self.fetchers = (
            fetchers if fetchers is not None else {"codex": fetch_codex, "claude": fetch_claude}
        )
        self.clock = clock
        self.lock = threading.Lock()
        self.last_attempt = {}
        self.running = set()
        self.rows = {
            provider: {
                "provider": provider,
                "name": {"codex": "Codex", "claude": "Claude"}.get(provider, provider),
                "source": "Codex CLI · konto CLI"
                if provider == "codex"
                else "CodexBar → Claude CLI",
                "status": "loading",
                "updated_at": None,
                "windows": [],
                "message": "Odczyt limitów…",
            }
            for provider in self.fetchers
        }

    def snapshot(self, force=False):
        with self.lock:
            now = self.clock()
            for provider in self.fetchers:
                interval = 30 if force else 300
                if (
                    provider in self.running
                    or now - self.last_attempt.get(provider, -math.inf) < interval
                ):
                    continue
                self.running.add(provider)
                self.last_attempt[provider] = now
                self.rows[provider].update(status="loading", windows=[], message="Odczyt limitów…")
                threading.Thread(target=self.refresh, args=(provider,), daemon=True).start()
            result = copy.deepcopy(list(self.rows.values()))
        for row in result:
            # A passed reset is not evidence of a replenished allowance.
            if any(
                w["resets_at"] is not None and w["resets_at"] <= time.time() for w in row["windows"]
            ):
                row.update(
                    status="unavailable",
                    windows=[],
                    message="Minął termin resetu; oczekiwanie na aktualny odczyt.",
                )
        return result

    def refresh(self, provider):
        try:
            windows = self.fetchers[provider]()
            status = "ok" if windows else "unavailable"
            message = (
                "Pozostały limit konta; osobno od oszczędności tekstu."
                if windows
                else "Usługa nie udostępniła limitów dla tego konta."
            )
        except FileNotFoundError:
            windows, status = [], "unavailable"
            message = "Brak Codex CLI." if provider == "codex" else "Brak adaptera CodexBar CLI."
        except Exception:
            windows, status = [], "unavailable"
            message = "Odczyt niedostępny. Sprawdź logowanie w CLI lub połączenie."
        with self.lock:
            self.rows[provider].update(
                windows=windows,
                status=status,
                message=message,
                updated_at=time.time() if status == "ok" else None,
            )
            self.running.discard(provider)
