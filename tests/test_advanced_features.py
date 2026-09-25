from usagetrim.core.cache import ContextCache
from usagetrim.core.redactor import redact_secrets
from usagetrim.core.tree_scanner import scan_directory


def test_cache_never_persists_or_replays_recognized_secrets(tmp_path):
    import sqlite3

    cache = ContextCache(tmp_path / "cache.db")
    secret = "sk-proj-" + "a" * 30
    ref = cache.store(secret)
    assert secret not in cache.retrieve(ref)
    with sqlite3.connect(cache.db_path) as conn:
        assert secret not in conn.execute("SELECT content FROM output_cache").fetchone()[0]
        conn.execute("UPDATE output_cache SET content = ?", (secret,))
    assert secret not in cache.retrieve(ref)  # Entries from older installations.


def test_invalid_retrieval_range_does_not_dump_entire_cache():
    cache = ContextCache()
    ref = cache.store("large private log " * 2000)
    for invalid in ("bad", "0", "10-2", "-5"):
        output = cache.retrieve(ref, invalid)
        assert output.startswith("Error:")
        assert "large private log" not in output


def test_redact_secrets():
    raw = (
        "Config: OPENAI_API_KEY=sk-proj-1234567890abcdef1234567890\n"
        "ANTHROPIC_KEY=sk-ant-1234567890abcdef1234567890\n"
        "GH_TOKEN=ghp_1234567890abcdefghijklmnopqrstuvwxyz\n"
        "DB=postgres://user:super_secret_pw@localhost:5432/db"
    )
    scrubbed = redact_secrets(raw)
    assert "sk-proj-" not in scrubbed
    assert "[REDACTED_OPENAI_KEY]" in scrubbed
    assert "sk-ant-" not in scrubbed
    assert "[REDACTED_ANTHROPIC_KEY]" in scrubbed
    assert "ghp_" not in scrubbed
    assert "[REDACTED_GITHUB_TOKEN]" in scrubbed
    assert "super_secret_pw" not in scrubbed
    assert "[REDACTED_DB_URL]@" in scrubbed


def test_context_cache_and_retrieval(tmp_path):
    db_file = tmp_path / "test_cache.db"
    cache = ContextCache(db_path=db_file)

    sample_content = "\n".join([f"line_{i}: payload data" for i in range(1, 101)])
    ref_id = cache.store(sample_content, source="pytest")
    assert ref_id.startswith("tc_")

    # Full retrieval
    full = cache.retrieve(ref_id)
    assert "line_1:" in full
    assert "line_100:" in full

    # Slice retrieval
    sliced = cache.retrieve(ref_id, lines_range="10-15")
    assert "line_10:" in sliced
    assert "line_15:" in sliced
    assert "line_25:" not in sliced

    # Idempotent duplicate detection
    dup = cache.check_duplicate(sample_content)
    assert dup == ref_id


def test_tree_scanner(tmp_path):
    # Create sample structure
    src = tmp_path / "src"
    src.mkdir()
    (src / "app.py").write_text("def hello(): pass\n" * 20)
    (src / "util.py").write_text("def util(): pass\n" * 5)

    root_node, all_files = scan_directory(tmp_path)
    assert root_node.tokens > 0
    assert len(all_files) == 2
    assert any("app.py" in f[0] for f in all_files)
