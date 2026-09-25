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
# Claude's adapter can run a 20s usage probe, retry, then enrich with /status.
# Bound the full cycle without cutting off a valid first-run reading at 30s.
CLAUDE_QUOTA_TIMEOUT = 60

CLAUDE_ISSUES = {
    "cli_missing": "The terminal Claude Code CLI was not found. Claude Desktop Code uses a separate bundled installation.",
    "cli_not_signed_in": "Terminal Claude Code is not linked to an account in this environment. Claude Desktop Code uses a separate sign-in. Connect the terminal CLI or view your limits in Claude.",
    "adapter_unavailable": "The quota adapter could not use the selected terminal CLI. Claude Desktop Code is a separate session; its login status was not checked.",
    "adapter_error": "The terminal CLI quota request failed. This does not establish a problem with your Claude Desktop session.",
    "no_windows": "The terminal CLI returned no supported quota windows. Claude Desktop limits are not connected to this reader.",
}


class QuotaUnavailable(Exception):
    """Only allowlisted diagnostics reach the UI, never raw provider output."""

    def __init__(self, issue: str):
        self.issue = issue if issue in CLAUDE_ISSUES else "adapter_error"
        super().__init__(CLAUDE_ISSUES[self.issue])


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
        label = "Weekly"
    elif minutes == 300:
        label = "5 hours"
    elif minutes is not None:
        label = f"{minutes / 60:g} h" if minutes % 60 == 0 else f"{minutes:g} min"
    else:
        label = {
            "primary": "Primary window",
            "secondary": "Secondary window",
            "tertiary": "Additional window",
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
                "params": {"clientInfo": {"name": "usagetrim-usage", "version": "0.2.0"}},
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


def read_cli_json(arguments: list[str], environment: dict, timeout: float = 30):
    """Bounded, read-only child output; stderr and identity data are not retained."""
    process = subprocess.Popen(
        arguments,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        cwd=Path.home(),
        env=environment,
        start_new_session=True,
    )
    data = bytearray()
    try:
        deadline = time.monotonic() + timeout
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
        code = process.wait(timeout=max(0.01, deadline - time.monotonic()))
        return json.loads(data), code
    finally:
        stop_process(process)
        process.stdout.close()


def fetch_claude() -> list[dict]:
    command = executable("codexbar")
    if not command:
        raise FileNotFoundError("codexbar")
    environment = dict(os.environ)
    claude = environment.get("CLAUDE_CLI_PATH") or executable("claude")
    if not claude or not os.access(os.path.expanduser(claude), os.X_OK):
        raise QuotaUnavailable("cli_missing")
    environment["CLAUDE_CLI_PATH"] = os.path.expanduser(claude)
    # Explicit CLI source avoids browser cookies, credential extraction and cost scans.
    payload, code = read_cli_json(
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
        environment,
        timeout=CLAUDE_QUOTA_TIMEOUT,
    )
    entries = payload if isinstance(payload, list) else [payload]
    errors = [
        row.get("error")
        for row in entries
        if isinstance(row, dict) and row.get("provider") == "claude" and row.get("error")
    ]
    for error in errors:
        message = error.get("message", "") if isinstance(error, dict) else ""
        if isinstance(message, str) and "no available fetch strategy" in message.lower():
            # Diagnose only the CLI we selected, never the active Desktop session.
            try:
                auth, _ = read_cli_json(
                    [environment["CLAUDE_CLI_PATH"], "auth", "status", "--json"],
                    environment,
                    timeout=5,
                )
            except Exception:
                auth = None
            if isinstance(auth, dict) and auth.get("loggedIn") is False:
                raise QuotaUnavailable("cli_not_signed_in")
            raise QuotaUnavailable("adapter_unavailable")
    if code or errors:
        raise QuotaUnavailable("adapter_error")
    windows = claude_windows(payload)
    if not windows:
        raise QuotaUnavailable("no_windows")
    return windows


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
                "source": "Codex CLI · CLI account"
                if provider == "codex"
                else "Terminal Claude Code",
                "status": "loading",
                "issue": None,
                "updated_at": None,
                "windows": [],
                "message": "Reading limits…",
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
                self.rows[provider].update(status="loading", windows=[], message="Reading limits…")
                threading.Thread(target=self.refresh, args=(provider,), daemon=True).start()
            result = copy.deepcopy(list(self.rows.values()))
        for row in result:
            # A passed reset is not evidence of a replenished allowance.
            if any(
                w["resets_at"] is not None and w["resets_at"] <= time.time() for w in row["windows"]
            ):
                row.update(
                    status="unavailable",
                    issue="reset_pending",
                    windows=[],
                    message="Reset time has passed; waiting for a fresh reading.",
                )
        return result

    def refresh(self, provider):
        issue = None
        try:
            windows = self.fetchers[provider]()
            status = "ok" if windows else "unavailable"
            message = (
                "Remaining account allowance; separate from text savings."
                if windows
                else "The service did not provide limits for this account."
            )
        except QuotaUnavailable as exc:
            windows, status, issue = [], "unavailable", exc.issue
            message = str(exc)
        except FileNotFoundError:
            windows, status = [], "unavailable"
            issue = "reader_missing"
            message = (
                "Codex CLI is not installed."
                if provider == "codex"
                else "CodexBar CLI adapter is not installed."
            )
        except (TimeoutError, subprocess.TimeoutExpired):
            windows, status = [], "unavailable"
            issue = "timeout"
            message = "The quota reader timed out. Try refreshing later."
        except Exception:
            windows, status = [], "unavailable"
            message = "The quota reader failed. This does not establish a sign-in problem."
        with self.lock:
            self.rows[provider].update(
                windows=windows,
                status=status,
                issue=issue,
                message=message,
                updated_at=time.time() if status == "ok" else None,
            )
            self.running.discard(provider)
