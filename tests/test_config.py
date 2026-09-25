from __future__ import annotations

from usagetrim.core.config import UsagetrimConfig, load_config


def test_default_config(tmp_path):
    cfg = load_config(root_dir=tmp_path)
    assert isinstance(cfg, UsagetrimConfig)
    assert cfg.max_lines == 80
    assert cfg.default_budget is None


def test_load_config_from_pyproject(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("""
[tool.usagetrim]
max_lines = 50
default_budget = 1000
custom_secrets = ["CUSTOM_[0-9]+"]
""")
    cfg = load_config(root_dir=tmp_path)
    assert cfg.max_lines == 50
    assert cfg.default_budget == 1000
    assert cfg.custom_secrets == ["CUSTOM_[0-9]+"]


def test_load_config_from_usagetrim_toml(tmp_path):
    cfg_file = tmp_path / "usagetrim.toml"
    cfg_file.write_text("""
max_lines = 120
max_token_delta = 25000
""")
    cfg = load_config(root_dir=tmp_path)
    assert cfg.max_lines == 120
    assert cfg.max_token_delta == 25000
