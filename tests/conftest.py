import pytest


@pytest.fixture(autouse=True)
def isolated_context_cache(tmp_path, monkeypatch):
    """Tests must neither read nor persist the developer's cached command output."""
    monkeypatch.setenv("TOKENCUT_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("TOKENCUT_STATE_DIR", str(tmp_path / "state"))
