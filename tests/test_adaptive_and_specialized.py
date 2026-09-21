import re

import pytest

from tokencut.core.adaptive import compress_to_budget
from tokencut.core.cache import ContextCache
from tokencut.core.specialized import (
    auto_specialize_command_output,
    filter_cargo_test,
    filter_git_log,
    filter_git_status,
)
from tokencut.metrics.tokenizer import count_tokens

SAMPLE_GIT_LOG = """commit a1b2c3d4e5f67890abcdef1234567890abcdef12
Author: Alice Developer <alice@example.com>
Date:   Mon Sep 15 14:00:00 2026 +0200

    feat(auth): implement JWT verification and token refresh

commit f1e2d3c4b5a67890abcdef1234567890abcdef12
Author: Bob Maintainer <bob@example.com>
Date:   Sun Sep 14 10:00:00 2026 +0200

    fix(db): handle connection pool timeout gracefully
"""

SAMPLE_GIT_STATUS = """On branch main
Changes to be committed:
	modified:   src/main.py

Untracked files:
  (use "git add <file>..." to include in what will be committed)
	tmp/cache/chunk1.json
	tmp/cache/chunk2.json
	tmp/cache/chunk3.json
	tmp/cache/chunk4.json
	single_file.txt
"""


SAMPLE_GIT_LOG_PATCH = """commit a1b2c3d4e5f67890abcdef1234567890abcdef12
Author: Alice Developer <alice@example.com>
Date:   Mon Sep 15 14:00:00 2026 +0200

    fix(api): guard against empty payloads

diff --git a/src/api.py b/src/api.py
index 1111111..2222222 100644
--- a/src/api.py
+++ b/src/api.py
@@ -10,6 +10,8 @@ class Handler:
     def handle(self, payload):
         logger.debug("incoming payload")
+        if not payload:
+            raise ValueError("empty payload")
         return self.process(payload)
"""

SAMPLE_GIT_LOG_STAT = """commit a1b2c3d4e5f67890abcdef1234567890abcdef12
Author: Alice Developer <alice@example.com>
Date:   Mon Sep 15 14:00:00 2026 +0200

    chore(deps): bump pinned versions

 README.md |  4 +-
 uv.lock   | 20 ++++++----
 2 files changed, 16 insertions(+), 8 deletions(-)
"""

SAMPLE_CARGO_PASS = "\n".join(
    [
        "   Compiling acme-core v0.4.1 (/src/acme-core)",
        "     Running unittests src/lib.rs (target/debug/deps/acme_core-3f9a2b1c)",
        "",
        "running 48 tests",
    ]
    + [f"test module{i // 8}::tests::case_{i} ... ok" for i in range(48)]
    + [
        "",
        "test result: ok. 48 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; "
        "finished in 0.31s",
    ]
)

SAMPLE_CARGO_FAIL = """running 6 tests
test config::tests::parses_defaults ... ok
test config::tests::rejects_unknown_keys ... ok
test parser::tests::handles_empty ... ok
test parser::tests::rejects_bad_utf8 ... FAILED
test parser::tests::roundtrip ... ok

failures:

---- parser::tests::rejects_bad_utf8 stdout ----
thread 'parser::tests::rejects_bad_utf8' panicked at src/parser.rs:212:9:
assertion `left == right` failed
  left: Err(InvalidUtf8)
 right: Ok(())

test result: FAILED. 5 passed; 1 failed; 0 ignored; 0 measured; 0 filtered out; \
finished in 0.08s
"""


def test_filter_git_log():
    compact = filter_git_log(SAMPLE_GIT_LOG)
    assert "a1b2c3d" in compact
    assert "[Alice Developer]" in compact
    assert "feat(auth): implement JWT" in compact
    assert "Date:" not in compact
    assert len(compact.splitlines()) < len(SAMPLE_GIT_LOG.splitlines())


def test_filter_git_status():
    compact = filter_git_status(SAMPLE_GIT_STATUS)
    assert "tmp/ (4 untracked files)" in compact
    assert "single_file.txt" in compact


def test_filter_git_log_keeps_patch_body():
    compact = filter_git_log(SAMPLE_GIT_LOG_PATCH)

    # The patch is the point of `git log -p`; it must survive compaction.
    assert "diff --git a/src/api.py b/src/api.py" in compact
    assert 'raise ValueError("empty payload")' in compact
    assert "Date:" not in compact


def test_filter_git_log_does_not_absorb_diff_context_into_message():
    compact = filter_git_log(SAMPLE_GIT_LOG_PATCH)
    subject = compact.splitlines()[0]

    # Context lines are indented like message lines, but are not message text.
    assert subject == "a1b2c3d [Alice Developer] fix(api): guard against empty payloads"
    assert "def handle" not in subject
    assert "logger.debug" not in subject


def test_filter_git_log_keeps_stat_block():
    compact = filter_git_log(SAMPLE_GIT_LOG_STAT)

    assert "a1b2c3d [Alice Developer] chore(deps): bump pinned versions" in compact
    assert "README.md" in compact
    assert "2 files changed, 16 insertions(+), 8 deletions(-)" in compact


def test_filter_git_log_plain_format_stays_dense():
    # The headline one-line-per-commit behaviour must not regress.
    compact = filter_git_log(SAMPLE_GIT_LOG)

    assert len(compact.splitlines()) == 2
    assert "diff --git" not in compact


def test_auto_specialize():
    res_log = auto_specialize_command_output("git log -n 10", SAMPLE_GIT_LOG)
    assert res_log is not None
    assert "a1b2c3d" in res_log

    res_none = auto_specialize_command_output("pytest -v", "some output")
    assert res_none is None


def test_filter_cargo_test_collapses_passing_runs():
    compact = filter_cargo_test(SAMPLE_CARGO_PASS)

    assert "[TokenCut: 48 passing tests, 48 progress records]" in compact
    assert "test module0::tests::case_0 ... ok" not in compact
    # The authoritative summary and the compile banner must survive.
    assert "test result: ok. 48 passed; 0 failed" in compact
    assert "Compiling acme-core v0.4.1" in compact
    assert count_tokens(compact).claude < count_tokens(SAMPLE_CARGO_PASS).claude


def test_filter_cargo_test_keeps_failures_verbatim():
    compact = filter_cargo_test(SAMPLE_CARGO_FAIL)

    # Everything from the first diagnostic onward is reproduced untouched.
    assert "test parser::tests::rejects_bad_utf8 ... FAILED" in compact
    assert "panicked at src/parser.rs:212:9" in compact
    assert "assertion `left == right` failed" in compact
    assert "left: Err(InvalidUtf8)" in compact
    assert "test result: FAILED. 5 passed; 1 failed" in compact
    # Passes before the failure may still collapse; passes after it must not.
    assert "test parser::tests::roundtrip ... ok" in compact


def test_filter_cargo_test_leaves_output_without_passes_unchanged():
    raw = "running 0 tests\n\ntest result: ok. 0 passed; 0 failed; 0 ignored\n"

    assert filter_cargo_test(raw) == raw


def test_auto_specialize_routes_cargo_test():
    compact = auto_specialize_command_output("cargo test --all-features", SAMPLE_CARGO_PASS)

    assert compact is not None
    assert "[TokenCut: 48 passing tests, 48 progress records]" in compact


def test_filter_cargo_test_collapses_tests_named_like_diagnostics():
    raw = "\n".join(
        ["running 3 tests"]
        + [
            "test error::tests::reports_failure ... ok",
            "test warning::tests::timeout_is_logged ... ok",
            "test parser::tests::panicked_input ... ok",
        ]
        + ["", "test result: ok. 3 passed; 0 failed; 0 ignored"]
    )

    compact = filter_cargo_test(raw)

    # "error"/"warning" inside a test name must not stop collapsing.
    assert "[TokenCut: 3 passing tests, 3 progress records]" in compact
    assert "test result: ok. 3 passed; 0 failed" in compact


def test_compress_to_budget():
    large_text = "This is a sentence that has some words and will be repeated many times. " * 80
    initial_tokens = count_tokens(large_text).claude
    assert initial_tokens > 200

    # Request strict budget of 50 tokens
    budget_fitted = compress_to_budget(large_text, max_tokens=60, provider="claude")
    fitted_tokens = count_tokens(budget_fitted).claude

    assert fitted_tokens <= 60
    assert "Ref: tc_" in budget_fitted


@pytest.mark.parametrize("provider", ["claude", "openai", "gemini"])
@pytest.mark.parametrize("budget", [64, 100, 500])
@pytest.mark.parametrize(
    "raw", ["word " * 3000, "漢字🙂é" * 2000, "\n".join(f"step {i}" for i in range(300))]
)
def test_budget_includes_reference_and_suffix(provider, budget, raw):
    output = compress_to_budget(raw, budget, provider, suffix="\n[exit code: 1]")
    assert getattr(count_tokens(output), provider) <= budget
    assert output.endswith("[exit code: 1]")
    ref = re.search(r"tc_[a-f0-9]+", output).group()
    assert ContextCache().retrieve(ref) == raw


def test_budget_redacts_even_when_input_fits():
    secret = "sk-proj-" + "a" * 30
    output = compress_to_budget(f"token={secret}", 100)
    assert secret not in output
    assert "REDACTED" in output


def test_small_budget_cannot_silently_drop_recovery():
    with pytest.raises(ValueError, match="recovery reference"):
        compress_to_budget("long text " * 100, 1)


def test_cleaning_still_returns_recoverable_reference():
    raw = "\x1b[31mred\x1b[0m\n" * 100
    output = compress_to_budget(raw, 100)
    assert count_tokens(output).claude <= 100
    ref = re.search(r"tc_[a-f0-9]+", output).group()
    assert ContextCache().retrieve(ref) == raw
