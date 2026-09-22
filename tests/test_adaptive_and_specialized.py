import re

import pytest

from tokencut.core.adaptive import compress_to_budget
from tokencut.core.cache import ContextCache
from tokencut.core.specialized import (
    auto_specialize_command_output,
    filter_cargo_build,
    filter_cargo_test,
    filter_git_diff,
    filter_git_log,
    filter_git_status,
    filter_go_test,
    filter_jest_vitest,
    filter_json_output,
    filter_npm_install,
    filter_pip_install,
    filter_ruff,
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


SAMPLE_CARGO_LARGE = "\n".join(
    [
        "   Compiling acme-core v0.4.1 (/src/acme-core)",
        "     Running unittests src/lib.rs (target/debug/deps/acme_core-3f9a2b1c)",
        "",
        "running 201 tests",
    ]
    + [f"test module{i // 10}::tests::case_{i} ... ok" for i in range(200)]
    + [
        "test parser::tests::rejects_bad_utf8 ... FAILED",
        "",
        "failures:",
        "",
        "---- parser::tests::rejects_bad_utf8 stdout ----",
        "thread 'parser::tests::rejects_bad_utf8' panicked at src/parser.rs:212:9:",
        "assertion `left == right` failed",
        "  left: Err(InvalidUtf8)",
        " right: Ok(())",
        "",
        "stack backtrace:",
    ]
    + [f"   {i}: acme_core::parser::parse_{i}" for i in range(48)]
    + [f"             at ./src/parser.rs:{200 + i}:5" for i in range(48)]
    + [
        "note: run with `RUST_BACKTRACE=1` environment variable to display a backtrace",
        "",
        "failures:",
        "    parser::tests::rejects_bad_utf8",
        "",
        "test result: FAILED. 200 passed; 1 failed; 0 ignored; 0 measured; 0 filtered out; "
        "finished in 1.24s",
    ]
)

SAMPLE_GO_LARGE = "\n".join(
    sum(
        ([f"=== RUN   TestOk{i}", f"--- PASS: TestOk{i} (0.00s)"] for i in range(120)),
        [],
    )
    + [
        "=== RUN   TestPanicRecovery",
        "--- FAIL: TestPanicRecovery (0.00s)",
        "panic: unhandled nil pointer dereference [recovered]",
        "\tpanic: runtime error: invalid memory address",
        "goroutine 16 [running]:",
    ]
    + [f"main.helper{i}(0x1400011e1e0)" for i in range(36)]
    + [f"\t/src/server_test.go:{40 + i} +0x28" for i in range(36)]
    + [
        "FAIL",
        "FAIL\tgithub.com/acme/server\t0.018s",
        "FAIL",
    ]
)

SAMPLE_NEXTEST_PASS = "\n".join(
    [
        "    Starting 24 tests across 1 binary",
    ]
    + [f"        PASS [   0.01{i % 10}s] acme tests::case_{i}" for i in range(24)]
    + [
        "     Summary [   0.42s] 24 tests run: 24 passed, 0 skipped",
    ]
)

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

SAMPLE_GIT_DIFF = """diff --git a/src/main.py b/src/main.py
index 1234567..89abcdef 100644
--- a/src/main.py
+++ b/src/main.py
@@ -10,6 +10,7 @@ def process():
     context_line_1
     context_line_2
     context_line_3
+    new_important_logic()
     context_line_4
     context_line_5
diff --git a/uv.lock b/uv.lock
index aaaaaaa..bbbbbbb 100644
--- a/uv.lock
+++ b/uv.lock
@@ -1,500 +1,500 @@
-old_package_version = "1.0.0"
+new_package_version = "1.0.1"
""" + "\n".join([f"+ extra_lock_line_{i}" for i in range(100)])

SAMPLE_RUFF_FULL = """src/auth/session.py:12:8: F401 [*] `os` imported but unused
  |
10 | import sys
11 | import json
12 | import os
   |        ^^
  |
  = help: Remove unused import: `os`

src/auth/session.py:44:5: F841 Local variable `token` is assigned to but never used
  |
42 | def refresh():
43 |     client = Client()
44 |     token = client.issue()
   |     ^^^^^
45 |     return client
  |
  = help: Remove assignment to unused variable `token`

Found 2 errors.
[*] 1 fixable with the `--fix` option.
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


def test_filter_cargo_test_keeps_failure_identity_and_assertion():
    compact = filter_cargo_test(SAMPLE_CARGO_FAIL)

    assert "test parser::tests::rejects_bad_utf8 ... FAILED" in compact
    assert "panicked at src/parser.rs:212:9" in compact
    assert "assertion `left == right` failed" in compact
    assert "left: Err(InvalidUtf8)" in compact
    assert "test result: FAILED. 5 passed; 1 failed" in compact
    # Passes after the failure stay visible; progress before it may collapse.
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


def test_filter_go_test_keeps_failure_identity_and_assertion():
    compact = filter_go_test(SAMPLE_GO_FAIL)

    assert "--- FAIL: TestPanicRecovery" in compact
    assert "panic: unhandled nil pointer dereference" in compact
    assert "runtime error: invalid memory address" in compact
    assert "FAIL\tgithub.com/acme/server" in compact
    # Stack frames are noise once the panic line is kept.
    assert "main.TestPanicRecovery" not in compact


def test_auto_specialize_routes_go_test():
    compact = auto_specialize_command_output("go test -v ./...", SAMPLE_GO_PASS)
    assert compact is not None
    assert "[TokenCut: 3 passing tests, 6 progress records]" in compact


def test_filter_cargo_test_compacts_failures_hard_with_large_savings():
    compact = filter_cargo_test(SAMPLE_CARGO_LARGE)
    raw_tokens = count_tokens(SAMPLE_CARGO_LARGE).openai
    out_tokens = count_tokens(compact).openai
    reduction = 100 * (raw_tokens - out_tokens) / raw_tokens

    # Pass/fail identity, names, assertion — not the 96-line backtrace.
    assert "test parser::tests::rejects_bad_utf8 ... FAILED" in compact
    assert "assertion `left == right` failed" in compact
    assert "left: Err(InvalidUtf8)" in compact
    assert "test result: FAILED. 200 passed; 1 failed" in compact
    assert "[TokenCut: 200 passing tests, 200 progress records]" in compact
    assert "stack backtrace:" not in compact
    assert "acme_core::parser::parse_12" not in compact
    assert reduction >= 85.0, (
        f"expected >=85% savings, got {reduction:.1f}% ({raw_tokens}->{out_tokens})"
    )


def test_filter_go_test_compacts_failures_hard_with_large_savings():
    compact = filter_go_test(SAMPLE_GO_LARGE)
    raw_tokens = count_tokens(SAMPLE_GO_LARGE).openai
    out_tokens = count_tokens(compact).openai
    reduction = 100 * (raw_tokens - out_tokens) / raw_tokens

    assert "--- FAIL: TestPanicRecovery" in compact
    assert "panic: unhandled nil pointer dereference" in compact
    assert "runtime error: invalid memory address" in compact
    assert "FAIL\tgithub.com/acme/server" in compact
    assert "[TokenCut: 120 passing tests, 241 progress records]" in compact
    assert "goroutine 16 [running]:" not in compact
    assert "main.helper12" not in compact
    assert reduction >= 85.0, (
        f"expected >=85% savings, got {reduction:.1f}% ({raw_tokens}->{out_tokens})"
    )


def test_auto_specialize_routes_cargo_toolchain_absolute_and_nextest():
    assert auto_specialize_command_output("cargo +nightly test", SAMPLE_CARGO_PASS) is not None
    assert (
        auto_specialize_command_output("cargo --locked test --all-features", SAMPLE_CARGO_PASS)
        is not None
    )
    assert (
        auto_specialize_command_output("/Users/me/.cargo/bin/cargo test", SAMPLE_CARGO_PASS)
        is not None
    )
    compact = auto_specialize_command_output("cargo nextest run", SAMPLE_NEXTEST_PASS)
    assert compact is not None
    assert "[TokenCut: 24 passing tests, 24 progress records]" in compact
    assert "PASS [   0.010s]" not in compact


def test_auto_specialize_routes_absolute_go_test():
    compact = auto_specialize_command_output("/usr/local/go/bin/go test -v ./...", SAMPLE_GO_PASS)
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


def test_filter_json_output_large_array():
    import json

    raw_items = [
        {"id": i, "name": f"item_{i}", "description": "some long description here " * 5}
        for i in range(25)
    ]
    raw_json = json.dumps(raw_items, indent=2)

    slimmed = filter_json_output(raw_json, command="gh api /repos/owner/repo/issues")
    assert slimmed is not None
    assert "Ref: tc_" in slimmed
    assert "omitted" in slimmed
    assert len(slimmed) < len(raw_json) * 0.5


def test_filter_json_output_small_json_untouched():
    raw_json = '{"status": "healthy", "uptime": 12345}'
    assert filter_json_output(raw_json, command="curl http://localhost/health") is None


def test_auto_specialize_routes_json_command():
    import json

    large_payload = json.dumps({"records": [{"id": i, "data": "val"} for i in range(50)]})
    result = auto_specialize_command_output("docker inspect container-1", large_payload)
    assert result is not None
    assert "omitted" in result
    assert "Ref: tc_" in result


def test_filter_cargo_build_collapses_crates():
    crates = "\n".join([f"   Compiling crate_{i} v0.{i}.0" for i in range(20)])
    raw = f"{crates}\nwarning: unused variable `x`\n --> src/main.rs:5:9\n    Finished dev [unoptimized + debuginfo] in 3.12s\n"
    res = filter_cargo_build(raw)
    assert "[TokenCut: compiled/checked 20 crates]" in res
    assert "warning: unused variable `x`" in res
    assert "Finished dev" in res
    assert "Compiling crate_0" not in res


def test_filter_cargo_build_preserves_error():
    raw = (
        "   Compiling crate_a v0.1.0\n"
        "   Compiling crate_b v0.2.0\n"
        "   Compiling crate_c v0.3.0\n"
        "error[E0425]: cannot find value `foo` in this scope\n"
        "  --> src/main.rs:10:5\n"
        "   |\n"
        "10 |     foo();\n"
        "   |     ^^^ not found\n"
    )
    res = filter_cargo_build(raw)
    assert "[TokenCut: compiled/checked 3 crates]" in res
    assert "error[E0425]: cannot find value `foo` in this scope" in res
    assert "10 |     foo();" in res


def test_filter_pip_install_collapses_progress_and_downloads():
    raw = (
        "Collecting requests>=2.31.0\n"
        "  Downloading requests-2.31.0-py3-none-any.whl (62 kB)\n"
        "     ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 62.6/62.6 kB 8.2 MB/s eta 0:00:00\n"
        "Collecting urllib3<3,>=1.21.1\n"
        "  Downloading urllib3-2.2.1-py3-none-any.whl (121 kB)\n"
        "     ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 121.1/121.1 kB 12.1 MB/s eta 0:00:00\n"
        "Installing collected packages: urllib3, requests\n"
        "Successfully installed requests-2.31.0 urllib3-2.2.1\n"
    )
    res = filter_pip_install(raw)
    assert "[TokenCut: resolved/downloaded 2 packages]" in res
    assert "Successfully installed requests-2.31.0 urllib3-2.2.1" in res
    assert "━━━━━━━━━━━━━━━━" not in res


def test_filter_npm_install_collapses_deprecations():
    deprecations = "\n".join(
        [f"npm warn deprecated pkg_{i}@1.0.0: version is deprecated" for i in range(8)]
    )
    raw = (
        f"{deprecations}\n"
        "added 185 packages, and audited 186 packages in 2s\n"
        "12 packages are looking for funding\n"
        "  run `npm fund`\n"
        "found 0 vulnerabilities\n"
    )
    res = filter_npm_install(raw)
    assert "[TokenCut: 8 package deprecation warnings collapsed]" in res
    assert "added 185 packages, and audited 186 packages in 2s" in res
    assert "found 0 vulnerabilities" in res
    assert "run `npm fund`" not in res


def test_auto_specialize_routes_build_and_package_commands():
    cargo_raw = "   Compiling a v1.0.0\n   Compiling b v1.0.0\n   Compiling c v1.0.0\n"
    res_cargo = auto_specialize_command_output("cargo build --release", cargo_raw)
    assert res_cargo is not None
    assert "[TokenCut: compiled/checked 3 crates]" in res_cargo

    pip_raw = "Collecting foo\nSuccessfully installed foo-1.0.0\n"
    res_pip = auto_specialize_command_output("pip install foo", pip_raw)
    assert res_pip is not None
    assert "Successfully installed foo-1.0.0" in res_pip

    npm_raw = "npm warn deprecated a\nnpm warn deprecated b\nnpm warn deprecated c\nadded 10 pkgs\n"
    res_npm = auto_specialize_command_output("npm install", npm_raw)
    assert res_npm is not None
    assert "[TokenCut: 3 package deprecation warnings collapsed]" in res_npm


def test_filter_git_diff_folds_lockfiles_and_keeps_code_hunks():
    compact = filter_git_diff(SAMPLE_GIT_DIFF)

    assert "diff --git a/src/main.py b/src/main.py" in compact
    assert "+    new_important_logic()" in compact
    assert "diff --git a/uv.lock b/uv.lock" in compact
    assert "lines of lockfile/generated diff omitted by tokencut" in compact
    assert "+ extra_lock_line_50" not in compact
    assert count_tokens(compact).claude < count_tokens(SAMPLE_GIT_DIFF).claude


def test_filter_git_diff_leaves_non_diff_output_unchanged():
    raw = "commit abc123\nAuthor: Alice\n\n    just a message\n"
    assert filter_git_diff(raw) == raw


def test_auto_specialize_routes_git_diff_and_show():
    compact_diff = auto_specialize_command_output("git diff HEAD~1", SAMPLE_GIT_DIFF)
    assert compact_diff is not None
    assert "omitted by tokencut" in compact_diff

    compact_show = auto_specialize_command_output("git show abc1234", SAMPLE_GIT_DIFF)
    assert compact_show is not None
    assert "+    new_important_logic()" in compact_show


def test_filter_ruff_compacts_full_frames_and_keeps_codes():
    compact = filter_ruff(SAMPLE_RUFF_FULL)

    assert "src/auth/session.py:12:8: F401 [*] `os` imported but unused" in compact
    assert "help: Remove unused import: `os`" in compact
    assert (
        "src/auth/session.py:44:5: F841 Local variable `token` is assigned to but never used"
        in compact
    )
    assert "Found 2 errors." in compact
    assert "[*] 1 fixable with the `--fix` option." in compact
    # Source frames and caret underlines are the noise.
    assert "import os" not in compact
    assert "^^^^^" not in compact
    assert count_tokens(compact).claude < count_tokens(SAMPLE_RUFF_FULL).claude


def test_filter_ruff_leaves_clean_output_unchanged():
    clean = "All checks passed!\n"
    assert filter_ruff(clean) == clean


def test_auto_specialize_routes_ruff():
    compact = auto_specialize_command_output("uv run ruff check .", SAMPLE_RUFF_FULL)
    assert compact is not None
    assert "F401" in compact
    assert "import os" not in compact

    compact_direct = auto_specialize_command_output("ruff check src", SAMPLE_RUFF_FULL)
    assert compact_direct is not None
    assert "F841" in compact_direct


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
