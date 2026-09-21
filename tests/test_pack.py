from __future__ import annotations

from pathlib import Path

from tokencut.core.cache import ContextCache
from tokencut.core.pack import pack_context


def test_pack_context_basic(tmp_path: Path):
    # Setup a mock project
    (tmp_path / "src").mkdir()
    py_file = tmp_path / "src" / "app.py"
    py_file.write_text(
        "class App:\n"
        "    def run(self):\n"
        "        # long implementation\n"
        "        print('hello')\n"
        "        return 1\n"
    )

    readme = tmp_path / "README.md"
    readme.write_text("# My Project\nA cool project.\n")

    res = pack_context(root=tmp_path, budget=4000)
    assert res.file_count >= 2
    assert "app.py" in res.bundle_text
    assert "README.md" in res.bundle_text
    assert "# TokenCut Context Bundle" in res.bundle_text
    assert res.packed_tokens <= 4000


def test_pack_context_force_skeleton(tmp_path: Path):
    code_file = tmp_path / "math_utils.py"
    code_file.write_text(
        "def compute_sum(a: int, b: int) -> int:\n"
        "    result = a + b\n"
        "    return result\n\n"
        "def compute_mul(a: int, b: int) -> int:\n"
        "    result = a * b\n"
        "    return result\n"
    )

    res = pack_context(root=tmp_path, budget=4000, force_skeleton=True)
    assert res.file_count == 1
    file_entry = res.files[0]
    assert file_entry.is_skeleton
    assert "def compute_sum" in file_entry.content
    assert "..." in file_entry.content
    assert "Recover: tokencut retrieve" in file_entry.content
    assert file_entry.ref_id is not None
    assert "compute_sum" in ContextCache().retrieve(file_entry.ref_id)


def test_pack_context_secret_scrubbing(tmp_path: Path):
    secret_key = "ghp_" + "B" * 36
    env_file = tmp_path / "config.py"
    env_file.write_text(f"API_SECRET = '{secret_key}'\n")

    res = pack_context(root=tmp_path, budget=4000)
    assert secret_key not in res.bundle_text
    assert "[REDACTED" in res.bundle_text


def test_pack_context_budget_ceiling(tmp_path: Path):
    # Create several files with substantial content
    for i in range(5):
        f = tmp_path / f"module_{i}.py"
        lines = [f"def func_{i}_{j}():\n    return {j * 10}\n" for j in range(50)]
        f.write_text("".join(lines))

    # Restrict budget to small amount
    res = pack_context(root=tmp_path, budget=300)
    assert res.file_count == 5
    # Token ceiling is respected
    assert res.packed_tokens < 600
    assert any("lines omitted" in f.content for f in res.files)
    assert any(f.ref_id is not None for f in res.files)


def test_pack_context_specific_paths(tmp_path: Path):
    f1 = tmp_path / "wanted.py"
    f1.write_text("print('wanted')")
    f2 = tmp_path / "unwanted.py"
    f2.write_text("print('unwanted')")

    res = pack_context(paths=["wanted.py"], root=tmp_path, budget=1000)
    assert res.file_count == 1
    assert "wanted.py" in res.bundle_text
    assert "unwanted.py" not in res.bundle_text


def test_pack_context_to_dict(tmp_path: Path):
    f = tmp_path / "hello.py"
    f.write_text("print('world')")

    res = pack_context(root=tmp_path, budget=1000)
    d = res.to_dict()
    assert d["file_count"] == 1
    assert "bundle_text" in d
    assert len(d["files"]) == 1
    assert d["files"][0]["path"] == "hello.py"
