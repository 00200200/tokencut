import concurrent.futures
import re
import subprocess
from pathlib import Path

import pytest

from usagetrim.core.cache import ContextCache
from usagetrim.core.code_index import CodeIndex, digest, parse_source, read_symbol
from usagetrim.core.skeleton import extract_symbol_or_range
from usagetrim.core.symbol_edit import replace_symbol
from usagetrim.mcp import server
from usagetrim.metrics.tokenizer import count_tokens


def test_qualified_symbol_preserves_source_and_rejects_ambiguity(tmp_path):
    path = tmp_path / "sample.py"
    source = 'class A:\n    def run(self):\n        return "first"\n\nclass B:\n    @staticmethod\n    def run():\n        # ważny komentarz 🐍\n        return "żółć"\n'
    path.write_text(source)
    result = extract_symbol_or_range(path, symbol="B.run")
    assert result.split("\n", 1)[1] == source[source.index("    @staticmethod") :].rstrip("\n")
    assert f"sha256={digest(source)}" in result
    with pytest.raises(ValueError, match="Ambiguous"):
        read_symbol(path, "run")
    assert '"first"' in read_symbol(path, "run@2")
    with pytest.raises(ValueError, match="not found"):
        read_symbol(path, "C.run")


@pytest.mark.parametrize(
    "extension,language,source,selector,fragment",
    [
        (
            ".ts",
            "typescript",
            'export class A { run(): string { return "🦊"; } }',
            "A.run",
            "run(): string",
        ),
        (
            ".tsx",
            "tsx",
            "export function View() { return <div>Hi</div>; }",
            "View",
            "export function",
        ),
        (".js", "javascript", "const square = (x) => x * x;", "square", "square = (x)"),
        (".rs", "rust", "struct A {}\nimpl A { fn run(&self) -> i32 { 42 } }", "A.run", "fn run"),
        (
            ".go",
            "go",
            "package main\ntype A struct {}\nfunc (a *A) Run() int { return 42 }",
            "A.Run",
            "func (a *A)",
        ),
        (".swift", "swift", "struct A { func run() -> Int { return 42 } }", "A.run", "func run"),
        (".java", "java", "class A { int run() { return 42; } }", "A.run", "int run"),
        (".c", "c", "int run(void) { return 42; }", "run", "int run"),
        (".cpp", "cpp", "int run() { return 42; }", "run", "int run"),
    ],
)
def test_multilanguage_exact_symbols(tmp_path, extension, language, source, selector, fragment):
    path = tmp_path / ("sample" + extension)
    path.write_text(source)
    symbols, _ = parse_source(source, language)
    assert selector in {s.qualified for s in symbols}
    assert fragment in read_symbol(path, selector)


def test_index_respects_git_ignores_symlinks_and_incremental_updates(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / ".gitignore").write_text("ignored.py\n")
    (root / "ignored.py").write_text("def secret_ignored(): pass\n")
    (root / ".env.py").write_text("def secret_env(): pass\n")
    (root / "linked.py").symlink_to(root / "ignored.py")
    good = root / "good.py"
    good.write_text("def visible(): pass\nvisible()\n")
    index = CodeIndex(root)
    first = index.query()
    assert "1 files, 1 reindexed" in first and "visible" in first
    assert "secret" not in first
    original = Path.read_bytes
    with monkeypatch.context() as patch:
        patch.setattr(
            Path,
            "read_bytes",
            lambda path: (_ for _ in ()).throw(AssertionError("warm index reread source")),
        )
        assert "0 reindexed" in index.query("occurrences", "visible")
    good.write_text("def changed(): pass\n")
    assert "changed" in index.query() and "visible" not in index.query()
    assert original(good)
    good.unlink()
    assert "No matches" in index.query()


def test_search_patterns_redaction_bounds_and_incomplete_index(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "good.py").write_text('def action():\n    print("żółć")\n    print("hello")\n')
    secret = "ghp_" + "a" * 36
    (root / "notes.md").write_text(
        f"deployment failed because authentication timed out\n{secret}\n"
    )
    (root / "broken.py").write_text("def broken(:\n")
    index = CodeIndex(root)
    assert "notes.md:chunk-start=1" in index.query("search", "authentication timed out")
    patterns = index.query("pattern", "print($A)", file="good.py", limit=1)
    assert 'print("żółć")' in patterns and "More results omitted" in patterns
    assert "Incomplete index" in patterns
    with index.connect() as db:
        chunks = str(db.execute("SELECT body FROM chunks").fetchall())
    assert secret not in chunks
    with pytest.raises(ValueError):
        index.query("search", "***")
    with pytest.raises(ValueError, match="inside root"):
        index.query(file="../outside.py")
    with pytest.raises(ValueError):
        index.query(limit=True)


def test_parallel_queries_share_consistent_index(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "sample.py").write_text("def work(): return 42\n")
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: CodeIndex(root).query(), range(8)))
    assert all("sample.py:1" in result for result in results)
    with CodeIndex(root).connect() as db:
        assert db.execute("SELECT COUNT(*) FROM symbols").fetchone()[0] == 1


def test_edit_preview_hash_syntax_crlf_and_surrounding_bytes(tmp_path):
    path = tmp_path / "sample.py"
    source = (
        "# before 🦊\r\nclass A:\r\n    def run(self):\r\n        return 1\r\n\r\n# untouched\r\n"
    )
    path.write_bytes(source.encode())
    path.chmod(0o640)
    replacement = "    def run(self):\n        # preserve me\n        return 2\n"
    preview = replace_symbol(path, "A.run", replacement, digest(source))
    assert "Preview only" in preview and path.read_bytes() == source.encode()
    with pytest.raises(ValueError, match="changed"):
        replace_symbol(path, "A.run", replacement, "outdated", apply=True)
    with pytest.raises((SyntaxError, ValueError)):
        replace_symbol(path, "A.run", "    def run(:", digest(source), apply=True)
    with pytest.raises(ValueError):
        replace_symbol(path, "A.run", "    def other(self): return 2", digest(source), apply=True)
    assert path.read_bytes() == source.encode()
    replace_symbol(path, "A.run", replacement, digest(source), apply=True)
    expected = source.replace("        return 1", "        # preserve me\r\n        return 2")
    assert path.read_bytes() == expected.encode()
    assert path.stat().st_mode & 0o777 == 0o640


def test_edit_aborts_concurrent_change(tmp_path, monkeypatch):
    from usagetrim.core import symbol_edit

    path = tmp_path / "sample.py"
    source = "def run(): return 1\n"
    path.write_text(source)
    original = symbol_edit.select_symbol
    calls = 0

    def changed_during_parse(*args):
        nonlocal calls
        result = original(*args)
        calls += 1
        if calls == 2:
            path.write_text("def run(): return 999\n")
        return result

    monkeypatch.setattr(symbol_edit, "select_symbol", changed_during_parse)
    with pytest.raises(ValueError, match="changed while"):
        replace_symbol(path, "run", "def run(): return 2", digest(source), apply=True)
    assert "999" in path.read_text()
    assert not list(tmp_path.glob(".usagetrim-edit-*"))


def test_native_cli_code_and_guarded_edit(tmp_path):
    from typer.testing import CliRunner

    from usagetrim.cli import app

    root = tmp_path / "project"
    root.mkdir()
    source = "class A:\n    def run(self): return 1\nclass B:\n    def run(self): return 2\n"
    path = root / "sample.py"
    path.write_text(source)
    replacement = tmp_path / "replacement.py"
    replacement.write_text("    def run(self): return 3\n")
    runner = CliRunner()
    result = runner.invoke(app, ["code", str(root), "--mode", "symbols", "--query", "B.run"])
    assert result.exit_code == 0 and "B.run" in result.output
    result = runner.invoke(app, ["cat", str(path), "--symbol", "run"])
    assert (
        result.exit_code != 0 and "Ambiguous" in result.output and "Traceback" not in result.output
    )
    arguments = [
        "edit-symbol",
        str(path),
        "B.run",
        "--replacement-file",
        str(replacement),
        "--expected-hash",
        digest(source),
    ]
    assert runner.invoke(app, arguments).exit_code == 0 and path.read_text() == source
    assert runner.invoke(app, [*arguments, "--apply"]).exit_code == 0
    assert path.read_text() == source.replace("return 2", "return 3")
    assert runner.invoke(app, [*arguments, "--apply"]).exit_code != 0


def test_cache_search_scope_and_clear():
    cache = ContextCache()
    secret = "ghp_" + "b" * 36
    first = cache.store(
        "\n".join(["normal log"] * 90 + [f"timeout żółć {secret}"] + ["normal log"] * 90)
    )
    other = cache.store("timeout from unrelated project")
    result = cache.search(first, "timeout")
    assert "timeout żółć" in result and "unrelated" not in result and secret not in result
    assert "lines 91-120" in result
    assert "No matches" in cache.search(first, "nonexistent")
    assert "not found" in cache.search("tc_missing", "timeout")
    with pytest.raises(ValueError):
        cache.search(other, "***")
    cache.clear()
    assert "not found" in cache.search(first, "timeout")


def test_cache_search_does_not_mistake_error_output_for_missing_ref():
    cache = ContextCache()
    ref = cache.store("Error: authentication failed\n" + "irrelevant\n" * 100)
    assert "No matches" in cache.search(ref, "nonexistent")
    result = cache.search(ref, "authentication")
    assert "lines 1-30" in result and result.count("irrelevant") == 29


def test_code_events_have_no_source_or_query_in_telemetry(tmp_path):
    from usagetrim.core.monitor import Monitor
    from usagetrim.core.telemetry import TelemetryStore

    root = tmp_path / "project"
    root.mkdir()
    (root / "sample.py").write_text('def PRIVATE_SYMBOL(): return "PRIVATE_CONTENT"\n')
    server.handle_usagetrim_code({"root": str(root), "query": "PRIVATE_SYMBOL"})
    store = TelemetryStore()
    with store.connect() as db:
        rows = db.execute("SELECT * FROM events").fetchall()
    assert "PRIVATE_" not in str(rows)
    assert b"PRIVATE_" not in store.db_path.read_bytes()
    snapshot = Monitor([store.db_path.parent], tmp_path / "collector").snapshot()
    card = next(item for item in snapshot["integrations"] if item["name"] == "UsageTrim Code")
    assert card["last_event"] is not None


def test_mcp_code_and_search_recovery_obey_output_budget(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "sample.py").write_text(
        "\n".join(f"def function_{i}(): return {i}" for i in range(100))
    )
    response = server._respond(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "usagetrim_code",
                "arguments": {"root": str(root), "limit": 100, "max_tokens": 128},
            },
        }
    )
    assert not response["result"].get("isError")
    text = response["result"]["content"][0]["text"]
    assert count_tokens(text).claude <= 128
    ref = re.search(r"tc_[a-f0-9]+", text).group()
    recovered = server.handle_usagetrim_retrieve(
        {"ref_id": ref, "query": "function_99", "max_tokens": 256}
    )
    assert "function_99" in recovered and count_tokens(recovered).claude <= 256
    with pytest.raises(ValueError):
        server.handle_usagetrim_retrieve({"ref_id": ref, "query": "function_99", "lines": "1-2"})


def test_code_index_outline_mode(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    source = (
        "class AuthService:\n"
        "    def __init__(self, key: str) -> None:\n"
        "        self.key = key\n\n"
        "    def authenticate(self, user: str) -> bool:\n"
        "        return True\n\n"
        "def helper() -> None:\n"
        "    pass\n"
    )
    (root / "auth.py").write_text(source)
    index = CodeIndex(root)

    # Query outline with file param
    outline = index.query(mode="outline", file="auth.py")
    assert "# outline:" in outline
    assert "auth.py:1-6 [class_definition] AuthService" in outline
    assert "auth.py:2-3 [function_definition] AuthService.__init__" in outline
    assert (
        "auth.py:5-6 [function_definition] AuthService.authenticate | def authenticate(self, user: str) -> bool:"
        in outline
    )
    assert "auth.py:8-9 [function_definition] helper | def helper() -> None:" in outline

    # Query outline via MCP server
    mcp_res = server.handle_usagetrim_code(
        {"root": str(root), "mode": "outline", "file": "auth.py"}
    )
    assert "AuthService.authenticate" in mcp_res


def test_code_index_references_and_callers_mode(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    auth = (
        "class AuthService:\n    def verify_token(self, token: str) -> bool:\n        return True\n"
    )
    api = (
        "from auth import AuthService\n\n"
        "def login_endpoint(token: str) -> bool:\n"
        "    auth = AuthService()\n"
        "    return auth.verify_token(token)\n"
    )
    (root / "auth.py").write_text(auth)
    (root / "api.py").write_text(api)
    index = CodeIndex(root)

    # Query callers
    res = index.query(mode="callers", query="verify_token")
    assert "# callers:" in res
    assert "api.py:5:" in res
    assert "in login_endpoint [function_definition]" in res
    assert "auth.verify_token(token)" in res
    # Should not list verify_token's own declaration line in auth.py
    assert "def verify_token" not in res

    # Query references alias via MCP
    mcp_res = server.handle_usagetrim_code(
        {"root": str(root), "mode": "references", "query": "AuthService.verify_token"}
    )
    assert "login_endpoint" in mcp_res
