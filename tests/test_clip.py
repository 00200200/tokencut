from __future__ import annotations

import json
from unittest.mock import patch

from tokencut.core.cache import ContextCache
from tokencut.core.clip import compact_text, get_clipboard, set_clipboard


def test_compact_text_short_passthrough():
    short = "Just a short message"
    res = compact_text(short)
    assert res.text == short
    assert res.original_tokens == res.compacted_tokens
    assert res.reduction_pct == 0.0
    assert res.content_type == "plain"
    assert res.ref_id is None


def test_compact_text_json():
    data = {
        "items": [{"id": i, "name": f"item_{i}", "details": "x" * 50} for i in range(20)],
        "metadata": {"total": 20, "page": 1},
    }
    raw = json.dumps(data)
    res = compact_text(raw, budget=1000)
    assert res.content_type == "json"
    assert res.compacted_tokens < res.original_tokens
    assert res.saved_tokens > 0
    assert res.ref_id is not None
    cache = ContextCache()
    assert cache.retrieve(res.ref_id) == raw


def test_compact_text_diff():
    diff_lines = [
        "diff --git a/uv.lock b/uv.lock",
        "index 1234567..89abcde 100644",
        "--- a/uv.lock",
        "+++ b/uv.lock",
        "@@ -1,5 +1,6 @@",
    ] + [f"-line_{i} = {i}" for i in range(100)]
    raw = "\n".join(diff_lines)
    res = compact_text(raw, budget=1000)
    assert res.content_type == "diff"
    assert "uv.lock" in res.text
    assert res.ref_id is not None


def test_compact_text_pytest():
    noisy = (
        "============================= test session starts ==============================\n"
        "collected 39 items\n\n"
        + "\n".join(f"tests/test_file_{i}.py::test_pass PASSED [ {i}%]" for i in range(1, 40))
        + "\n=========================== short test summary info ============================\n"
        + "============================== 39 passed in 0.5s ===============================\n"
    )
    res = compact_text(noisy, budget=1000)
    assert res.content_type == "pytest"
    assert res.compacted_tokens < res.original_tokens


def test_compact_text_traceback_recursion():
    lines = [
        "Traceback (most recent call last):\n",
        '  File "runner.py", line 10, in run\n',
        "    recurse(0)\n",
    ]
    for _ in range(20):
        lines.append('  File "runner.py", line 5, in recurse\n')
        lines.append("    return recurse(n + 1)\n")
    lines.append("RecursionError: maximum recursion depth exceeded\n")
    raw = "".join(lines)

    res = compact_text(raw, budget=1000)
    assert res.content_type == "traceback"
    assert "identical recursive frame repeated" in res.text
    assert "RecursionError" in res.text


def test_compact_text_repeated_lines():
    noisy = ("INFO: processing item\n" * 50) + "DONE\n"
    res = compact_text(noisy, budget=1000)
    assert "preceding line repeated" in res.text
    assert "DONE" in res.text


def test_compact_text_secret_scrubbing():
    secret = "ghp_" + "A" * 36
    noisy = f"API_KEY={secret}\n" + ("line of padding text to make it past threshold\n" * 30)
    res = compact_text(noisy, budget=1000)
    assert secret not in res.text
    assert "[REDACTED_API_KEY]" in res.text or "[REDACTED" in res.text


def test_compact_text_budget_truncation():
    huge = "".join(f"Unique diagnostic row {i} with payload data {i * 7}\n" for i in range(400))
    res = compact_text(huge, budget=200)
    assert res.compacted_tokens <= 200
    assert "lines omitted by TokenCut to fit 200 token budget" in res.text
    assert res.ref_id is not None
    recovered = ContextCache().retrieve(res.ref_id)
    assert "Unique diagnostic row 0" in recovered
    assert "Unique diagnostic row 399" in recovered


def test_clipboard_darwin_mock():
    with patch("platform.system", return_value="Darwin"):
        with patch("subprocess.check_output", return_value="copied content"):
            assert get_clipboard() == "copied content"

        with patch("subprocess.Popen") as mock_popen:
            mock_proc = mock_popen.return_value
            mock_proc.communicate.return_value = ("", "")
            mock_proc.returncode = 0
            assert set_clipboard("new content") is True


def test_clipboard_non_darwin():
    with patch("platform.system", return_value="Linux"):
        assert get_clipboard() == ""
        assert set_clipboard("test") is False
