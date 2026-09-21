from __future__ import annotations

import json

from tokencut.core.cache import ContextCache
from tokencut.core.optimizer import optimize_context


def test_optimize_intra_fence_json_to_toon():
    users = [{"id": i, "name": f"User_{i}", "role": "developer", "active": True} for i in range(25)]
    prompt = f"""You are a senior data analyst.
Please review these active employee records:

```json
{json.dumps(users, indent=2)}
```

Highlight any anomalies or unexpected permissions.
"""
    res = optimize_context(prompt, budget=2000)
    assert res.primary_mode == "intra_fence_hybrid"
    assert "fence:toon" in res.pipeline_stages
    assert "You are a senior data analyst." in res.text
    assert "Highlight any anomalies" in res.text
    assert "[id | name | role | active]" in res.text
    assert res.optimized_tokens < res.original_tokens
    assert res.saved_tokens > 0


def test_optimize_intra_fence_diff():
    # Lockfiles are collapsed by slim_git_diff
    diff_payload = """diff --git a/package-lock.json b/package-lock.json
index 1234567..89abcdef 100644
--- a/package-lock.json
+++ b/package-lock.json
@@ -1,50 +1,50 @@
+ "name": "super-huge-lockfile",
+ "version": "1.0.0",
""" + "\n".join(f'+ "entry_{i}": {{ "version": "0.{i}.0" }}' for i in range(200))

    prompt = f"""Review the following dependency update patch:

```diff
{diff_payload}
```

Is this package upgrade safe?
"""
    res = optimize_context(prompt, budget=2000)
    assert res.primary_mode == "intra_fence_hybrid"
    assert "fence:diff" in res.pipeline_stages
    assert "Review the following dependency update patch:" in res.text
    assert "Is this package upgrade safe?" in res.text
    assert "lockfile/generated diff omitted by tokencut" in res.text
    assert res.optimized_tokens < res.original_tokens


def test_optimize_intra_fence_traceback():
    traceback_payload = """Traceback (most recent call last):
  File "server.py", line 142, in handle_request
    response = router.dispatch(path)
  File "router.py", line 55, in dispatch
    raise KeyError("Route '/api/v2/users' not registered")
KeyError: "Route '/api/v2/users' not registered"
"""
    prompt = f"""An unexpected exception occurred:

```text
{traceback_payload}
```

What is causing this failure?
"""
    res = optimize_context(prompt, budget=2000)
    assert "An unexpected exception occurred:" in res.text
    assert "What is causing this failure?" in res.text
    assert "KeyError" in res.text


def test_optimize_whole_document_table():
    data = json.dumps([{"col_a": i, "col_b": f"val_{i}"} for i in range(30)])
    res = optimize_context(data, budget=1000)
    assert res.primary_mode == "table_toon"
    assert "table_compression" in res.pipeline_stages
    assert "[col_a | col_b]" in res.text


def test_optimize_whole_document_conversation():
    transcript = """User: Can you check the build status for the backend service?
Assistant: I inspected the test suite and all 400 unit tests passed successfully on commit aed2393. Here is the full breakdown of every test run across our 15 microservices: service auth passed with 40 tests, service payment passed with 80 tests, service data passed with 120 tests, service worker passed with 90 tests, service notifications passed with 70 tests.
User: Should we use SQLite or PostgreSQL for local developer caching?
Assistant: We decided to use SQLite with WAL mode for the local context cache because it requires zero daemon setup. Setting up PostgreSQL would require docker containers and background daemons which slows down developer onboarding and introduces extra memory overhead.
User: Great. Which files need to be updated for this change?
Assistant: We modified src/tokencut/core/cache.py and src/tokencut/cli.py to support the new cache schema and ensure connection pooling works correctly across threads.
User: What are the next steps before opening the pull request?
Assistant: We must run ruff format, verify all tests pass, and generate the pull request description detailing the benchmark results and memory footprint.
User: Go ahead and run the checks now.
Assistant: All checks passed cleanly with 100% test success rate. Ready for review.
"""
    res = optimize_context(transcript, budget=500)
    assert res.primary_mode == "conversation_distill"
    assert "conversation_distillation" in res.pipeline_stages
    assert "Distilled Conversation Context" in res.text
    assert "src/tokencut/core/cache.py" in res.text


def test_optimize_whole_document_prompt_alignment():
    raw_prompt = """Today is Monday, September 21, 2026. Current time: 14:00:00 UTC.
Request ID: req_98723498234

You are an expert Python systems architect.
Always write clean, typed, modular code.
Follow PEP 8 conventions.
"""
    res = optimize_context(raw_prompt, budget=1000)
    assert res.primary_mode == "prompt_cache_align"
    assert "prompt_cache_alignment" in res.pipeline_stages
    assert "You are an expert Python systems architect." in res.text


def test_optimize_strict_budget_ceiling_and_ccr_recovery():
    long_text = "\n".join(
        f"Log line {i}: process worker heartbeat ping received ok" for i in range(500)
    )
    res = optimize_context(long_text, budget=120)
    assert res.optimized_tokens <= 120
    assert res.ref_id.startswith("tc_")
    assert f"Ref: {res.ref_id}" in res.text
    recovered = ContextCache().retrieve(res.ref_id)
    assert recovered == long_text


def test_optimize_budget_ceiling_stage_trigger():
    # Intra-fence hybrid with large instructions that exceed budget after fence compaction
    users = [{"id": i, "name": f"User_{i}", "role": "developer"} for i in range(20)]
    instructions = "\n".join(
        f"Instruction {i}: ensure all safety guidelines are followed strictly." for i in range(80)
    )
    prompt = f"{instructions}\n\n```json\n{json.dumps(users)}\n```\n\nFinal review step."
    res = optimize_context(prompt, budget=150)
    assert res.optimized_tokens <= 150
    assert "intra_fence_hybrid" == res.primary_mode
    assert "fence:toon" in res.pipeline_stages
    assert "budget_ceiling_enforcement" in res.pipeline_stages


def test_optimize_short_passthrough():
    short = "Hello world"
    res = optimize_context(short, budget=2000)
    assert res.primary_mode == "passthrough"
    assert res.text == short
    assert res.saved_tokens == 0


def test_optimize_secret_redaction():
    secret_text = "Deploying with access key AKIAIOSFODNN7EXAMPLE to production"
    res = optimize_context(secret_text, budget=2000)
    assert "AKIAIOSFODNN7EXAMPLE" not in res.text
    assert "[REDACTED_AWS_KEY]" in res.text
    assert ContextCache().retrieve(res.ref_id) == res.text
