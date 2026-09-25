from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class UsagetrimConfig:
    max_lines: int = 80
    default_budget: int | None = None
    custom_secrets: list[str] = field(default_factory=list)
    ignore_dirs: list[str] = field(default_factory=list)
    max_token_delta: int | None = None


def load_config(root_dir: Path | None = None) -> UsagetrimConfig:
    """Load configuration from usagetrim.toml or pyproject.toml [tool.usagetrim]."""
    root = root_dir or Path.cwd()

    # 1. Check usagetrim.toml
    custom_cfg = root / "usagetrim.toml"
    if custom_cfg.exists():
        try:
            with open(custom_cfg, "rb") as f:
                data = tomllib.load(f)
            return _parse_config_dict(data)
        except Exception:
            pass

    # 2. Check pyproject.toml
    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        try:
            with open(pyproject, "rb") as f:
                data = tomllib.load(f)
            tool_section = data.get("tool", {}).get("usagetrim", {})
            if tool_section:
                return _parse_config_dict(tool_section)
        except Exception:
            pass

    return UsagetrimConfig()


def _parse_config_dict(d: dict) -> UsagetrimConfig:
    return UsagetrimConfig(
        max_lines=d.get("max_lines", 80),
        default_budget=d.get("default_budget"),
        custom_secrets=d.get("custom_secrets", []),
        ignore_dirs=d.get("ignore_dirs", []),
        max_token_delta=d.get("max_token_delta"),
    )
