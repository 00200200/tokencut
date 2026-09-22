import re

import pytest

from tokencut.core.adaptive import compress_to_budget
from tokencut.core.cache import ContextCache
from tokencut.core.specialized import (
    auto_specialize_command_output,
    filter_cargo_test,
    filter_git_log,
    filter_git_status,
    filter_go_test,
    filter_jest_vitest,
    filter_tsc,
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

SAMPLE_GO_PASS = "\n".join(
    [
        "=== RUN   TestServerStart",
        "--- PASS: TestServerStart (0.01s)",
        "=== RUN   TestRouteMatch",
        "--- PASS: TestRouteMatch (0.00s)",
        "=== RUN   TestMiddlewareAuth",
        "--- PASS: TestMiddlewareAuth (0.00s)",
        "PASS",
        "ok  \tgithub.com/acme/server\t0.034s",
    ]
)

SAMPLE_GO_FAIL = """=== RUN   TestDatabaseQuery
--- PASS: TestDatabaseQuery (0.01s)
=== RUN   TestPanicRecovery
--- FAIL: TestPanicRecovery (0.00s)
panic: unhandled nil pointer dereference [recovered]
	panic: runtime error: invalid memory address
goroutine 16 [running]:
main.TestPanicRecovery(0x1400011e1e0)
	/src/server_test.go:42 +0x28
FAIL
FAIL	github.com/acme/server	0.018s
FAIL
"""

SAMPLE_VITEST_PASS = """ ✓ src/utils/format.test.ts (4 tests) 12ms
   ✓ formats currency correctly (2ms)
   ✓ parses date string (1ms)
   ✓ handles empty input (1ms)
   ✓ escapes html entities (1ms)
 ✓ src/components/Button.test.tsx (3 tests) 20ms
   ✓ renders button label (3ms)
   ✓ triggers click handler (2ms)
   ✓ respects disabled state (2ms)

 Test Files  2 passed (2)
      Tests  7 passed (7)
   Start at  08:00:00
   Duration  45ms
"""

SAMPLE_JEST_FAIL = """PASS src/utils/math.test.js
  ✓ calculates sum (2 ms)

FAIL src/utils/parser.test.js
  ● Parser › rejects malformed input

    expect(received).toThrow()

    Expected substring: "invalid token"
    Received message:   "unexpected EOF"

      18 |   test('rejects malformed input', () => {
    > 19 |     expect(() => parse(raw)).toThrow('invalid token');
         |                              ^
      20 |   });

Test Suites: 1 failed, 1 passed, 2 total
Tests:       1 failed, 1 passed, 2 total
Snapshots:   0 total
Time:        0.85 s
"""

SAMPLE_TSC_ERRORS = """src/auth/jwt.ts:45:12 - error TS2345: Argument of type 'string | undefined' is not assignable to parameter of type 'string'.
  Type 'undefined' is not assignable to type 'string'.

45   verifyToken(headerToken);
                 ~~~~~~~~~~~

src/models/user.ts:18:7 - error TS2741: Property 'email' is missing in type '{ id: number; name: string; }'.

18 const u: User = { id: 1, name: "Alice" };
         ~

Found 2 errors in 2 files.
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


def test_filter_go_test_collapses_passing_runs():
    compact = filter_go_test(SAMPLE_GO_PASS)

    assert "[TokenCut: 3 passing tests, 6 progress records]" in compact
    assert "=== RUN   TestServerStart" not in compact
    assert "--- PASS: TestServerStart" not in compact
    assert "ok  \tgithub.com/acme/server\t0.034s" in compact
    assert count_tokens(compact).claude < count_tokens(SAMPLE_GO_PASS).claude


def test_filter_go_test_keeps_failures_and_panics_verbatim():
    compact = filter_go_test(SAMPLE_GO_FAIL)

    assert "--- FAIL: TestPanicRecovery" in compact
    assert "panic: unhandled nil pointer dereference" in compact
    assert "runtime error: invalid memory address" in compact
    assert "main.TestPanicRecovery" in compact
    assert "FAIL\tgithub.com/acme/server" in compact


def test_auto_specialize_routes_go_test():
    compact = auto_specialize_command_output("go test -v ./...", SAMPLE_GO_PASS)
    assert compact is not None
    assert "[TokenCut: 3 passing tests, 6 progress records]" in compact


def test_filter_jest_vitest_collapses_passing_runs():
    compact = filter_jest_vitest(SAMPLE_VITEST_PASS)

    assert "[TokenCut: 9 passing tests, 9 progress records]" in compact
    assert "formats currency correctly" not in compact
    assert "Test Files  2 passed (2)" in compact
    assert "Tests  7 passed (7)" in compact
    assert count_tokens(compact).claude < count_tokens(SAMPLE_VITEST_PASS).claude


def test_filter_jest_vitest_keeps_failures_and_diffs_verbatim():
    compact = filter_jest_vitest(SAMPLE_JEST_FAIL)

    assert "FAIL src/utils/parser.test.js" in compact
    assert "expect(received).toThrow()" in compact
    assert "Expected substring:" in compact
    assert "Test Suites: 1 failed, 1 passed, 2 total" in compact


def test_filter_jest_vitest_collapses_tests_named_with_diagnostic_words():
    raw = "\n".join(
        [
            " ✓ src/errors.test.ts (2 tests) 5ms",
            "   ✓ handles timeout error properly (2ms)",
            "   ✓ reports warning on failure code (1ms)",
            "",
            "Tests  2 passed (2)",
        ]
    )
    compact = filter_jest_vitest(raw)
    assert "[TokenCut: 3 passing tests, 3 progress records]" in compact
    assert "Tests  2 passed (2)" in compact


def test_auto_specialize_routes_jest_and_vitest():
    compact_vitest = auto_specialize_command_output("npx vitest run", SAMPLE_VITEST_PASS)
    assert compact_vitest is not None
    assert "[TokenCut: 9 passing tests, 9 progress records]" in compact_vitest

    compact_npm = auto_specialize_command_output("npm test -- --coverage", SAMPLE_VITEST_PASS)
    assert compact_npm is not None
    assert "[TokenCut: 9 passing tests, 9 progress records]" in compact_npm


def test_filter_tsc_compacts_errors_and_strips_squiggles():
    compact = filter_tsc(SAMPLE_TSC_ERRORS)

    assert "~~~~~" not in compact
    assert "src/auth/jwt.ts:45:12 - error TS2345" in compact
    assert "TS2741" in compact
    assert "Found 2 errors in 2 files." in compact
    assert "verifyToken(headerToken);" in compact
    assert count_tokens(compact).claude < count_tokens(SAMPLE_TSC_ERRORS).claude


def test_filter_tsc_clean_output_untouched():
    clean = "✨ Done in 1.42s"
    assert filter_tsc(clean) == clean


def test_auto_specialize_routes_tsc():
    compact = auto_specialize_command_output("npx tsc --noEmit", SAMPLE_TSC_ERRORS)
    assert compact is not None
    assert "~~~~~" not in compact
    assert "error TS2345" in compact


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
