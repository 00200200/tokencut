import re
import sqlite3

import pytest

from tokencut.core import safe_filter
from tokencut.core.cache import ContextCache
from tokencut.core.redactor import redact_secrets
from tokencut.core.safe_filter import safe_compact_output
from tokencut.metrics.tokenizer import count_tokens


def _passes(count=80):
    return "".join(f"tests/test_api.py::test_endpoint_{i} PASSED [ 80%]\n" for i in range(count))


def _cached(output):
    ref = re.search(r"tc_[0-9a-f]{16}", output)
    assert ref, "Filtered output must carry a recovery reference"
    return ContextCache().retrieve(ref[0])


@pytest.mark.parametrize(
    "command", ["pytest -vv", "python3 -m pytest", "/tmp/.venv/bin/pytest", "uv run pytest"]
)
def test_passing_records_compact_with_recovery_and_net_savings(command):
    original = _passes() + "================== 80 passed in 0.2s ==================\n"
    result = safe_compact_output(original, command=command, exit_code=0)
    assert "80 passing tests" in result
    assert "80 passed in 0.2s" in result
    assert count_tokens(result).openai < count_tokens(original).openai
    assert _cached(result) == original


def test_recognized_session_without_command():
    original = (
        "===================== test session starts =====================\n"
        "platform linux -- Python 3.12, pytest-8.3.0\n"
        "collected 80 items\n\n"
        + _passes()
        + "===================== 80 passed in 0.12s =====================\n"
    )
    result = safe_compact_output(original)
    assert "80 passing tests" in result
    assert _cached(result) == original


@pytest.mark.parametrize("position", ["beginning", "middle", "end"])
def test_entire_failure_and_traceback_are_preserved_at_every_position(position):
    diagnostic = (
        "====================== FAILURES ======================\n"
        "_____________________ test_crash _____________________\n"
        "Traceback (most recent call last):\n"
        + '  File "recursive.py", line 24, in walk\n' * 40
        + "tests/test_embedded.py::test_example PASSED [100%]\n"
        + "AssertionError: missing sentinel at inner cause\n"
    )
    leading = "" if position == "beginning" else _passes()
    trailing = "" if position == "end" else _passes()
    original = leading + diagnostic + trailing
    result = safe_compact_output(original, command="pytest -vv", exit_code=1)
    assert diagnostic + trailing in result
    if result != original:
        assert _cached(result) == original


def test_nonroutine_order_and_exact_content_survive_between_pass_groups():
    first = "Captured custom output: order #358 uses price 4.25 EUR\r\n"
    second = "Nonroutine: backend switched to read-only for this operation\n"
    original = _passes() + first + _passes() + second + _passes()
    result = safe_compact_output(original, command="pytest")
    assert first in result
    assert second in result
    assert result.index(first) < result.index(second)
    assert _cached(result) == original


@pytest.mark.parametrize(
    "command",
    [
        "",
        "cat fixture.py",
        "python fixture.py",
        "pytest && cat fixture.py",
        "pytest | cat",
        "pytest;cat fixture.py",
    ],
)
def test_code_and_unrecognized_commands_do_not_filter_pass_looking_lines(command):
    original = 'expected_log = """\n' + _passes() + '"""\n'
    assert safe_compact_output(original, command=command) == original


def test_unknown_unique_output_is_not_truncated():
    original = "".join(f"unrecognized payload {i}: {'x' * 100}\n" for i in range(1000))
    assert safe_compact_output(original) == original


def test_exact_contiguous_duplicates_include_count_and_full_original():
    line = "Downloaded package artifact for the linux x86_64 development target\n"
    original = "Start\n" + line * 70 + "Distinct checkpoint\n" + line * 30 + "Done\n"
    result = safe_compact_output(original, command="custom-tool")
    assert result.count(line) == 2
    assert "70 times total" in result
    assert "30 times total" in result
    assert result.index("70 times total") < result.index("Distinct checkpoint")
    assert result.index("Distinct checkpoint") < result.index("30 times total")
    assert _cached(result) == original


def test_noncontiguous_duplicates_remain_in_place():
    original = "".join(f"common record\nunique record {i}\n" for i in range(100))
    assert safe_compact_output(original) == original


def test_pytest_dots_count_and_color_records_compact_but_mixed_failures_remain():
    original = (
        "tests/test_api.py "
        + "." * 80
        + " [ 40%]\n"
        + "\x1b[32m"
        + _passes()
        + "\x1b[0m"
        + "tests/test_db.py ...F..s. [100%]\n"
    )
    result = safe_compact_output(original, command="pytest")
    assert "160 passing tests" in result
    assert "tests/test_db.py ...F..s. [100%]" in result
    assert _cached(result) == original


@pytest.mark.parametrize("text", ["", "ok\n", "same\n" * 2, "tests/a.py::test_a PASSED [100%]\n"])
def test_short_results_are_unchanged(text):
    assert safe_compact_output(text, command="pytest", exit_code=0) == text


def test_recovery_notice_is_included_when_testing_net_savings():
    # A single unusually long pass line can save a few tokens on replacement,
    # but cannot pay for a cache notice. Unrelated text pushes it above cutoff.
    header = "".join(f"custom metadata entry {i}\n" for i in range(100))
    original = header + "tests/test_api.py::test_abcdefghijklmno PASSED [100%]\n"
    result = safe_compact_output(original, command="pytest")
    assert result == original


def test_secrets_are_redacted_in_filtered_output_and_persistent_cache():
    secret = "sk-proj-" + "a" * 40
    original = f"credential = {secret}\n" + _passes()
    result = safe_compact_output(original, command="pytest")
    assert secret not in result
    assert "[REDACTED_OPENAI_KEY]" in result
    assert _cached(result) == redact_secrets(original)
    with sqlite3.connect(ContextCache().db_path) as connection:
        assert secret not in connection.execute("SELECT content FROM output_cache").fetchone()[0]


def test_secrets_are_redacted_on_short_passthrough():
    secret = "sk-proj-" + "b" * 40
    assert safe_compact_output(secret) == "[REDACTED_OPENAI_KEY]"


@pytest.mark.parametrize("failure_point", ["init", "store"])
def test_cache_failure_keeps_full_redacted_output(monkeypatch, failure_point):
    def fail(*args, **kwargs):
        raise OSError("cache unavailable")

    if failure_point == "init":
        monkeypatch.setattr(safe_filter, "ContextCache", fail)
    else:
        monkeypatch.setattr(ContextCache, "store", fail)
    original = "sk-proj-" + "c" * 40 + "\n" + _passes()
    assert safe_compact_output(original, command="pytest") == redact_secrets(original)


def test_tokenizer_failure_keeps_full_output(monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("tokenizer unavailable")

    monkeypatch.setattr(safe_filter, "count_tokens", fail)
    original = _passes()
    assert safe_compact_output(original, command="pytest") == original


def test_output_is_deterministic():
    original = _passes()
    assert safe_compact_output(original, command="pytest") == safe_compact_output(
        original, command="pytest"
    )
