import tempfile
from pathlib import Path

from tokencut.core.skeleton import (
    extract_symbol_or_range,
    skeletonize_json,
    skeletonize_python,
)

SAMPLE_PYTHON = """\"\"\"Module docstring for auth service.\"\"\"

import os
from typing import Optional

API_KEY = "secret"

class AuthService:
    \"\"\"Handles user authentication and JWT generation.\"\"\"
    realm: str = "default"

    def __init__(self, secret: str):
        self.secret = secret
        self.cache = {}
        # 50 lines of complex setup
        for i in range(50):
            self.cache[i] = i * 2

    def verify_token(self, token: str, expiry: Optional[int] = None) -> bool:
        \"\"\"Verify token validity.\"\"\"
        if not token:
            return False
        # 20 lines of signature math
        return True

def standalone_helper(x: int) -> int:
    \"\"\"Helper calculation.\"\"\"
    return x * 42
"""


def test_skeletonize_python():
    skeleton = skeletonize_python(SAMPLE_PYTHON)
    assert "Module docstring for auth service." in skeleton
    assert "class AuthService:" in skeleton
    assert "Handles user authentication" in skeleton
    assert "def verify_token" in skeleton
    assert "expiry: Optional[int]" in skeleton
    assert "-> bool:" in skeleton
    assert "def standalone_helper(x: int) -> int:" in skeleton
    # Implementation body should be replaced with ...
    assert "self.cache = {}" not in skeleton
    assert "return x * 42" not in skeleton
    assert "..." in skeleton


def test_skeletonize_json():
    huge_json = '{"name": "app", "dependencies": ["a", "b", "c", "d", "e", "f", "g", "h"]}'
    res = skeletonize_json(huge_json, max_array_items=2)
    assert '"name": "app"' in res
    assert '"a"' in res
    assert '"b"' in res
    assert "more items omitted by tokencut" in res


def test_extract_symbol_and_range():
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(SAMPLE_PYTHON)
        tmp_path = f.name

    try:
        # Extract lines 8-12 (which contains class AuthService)
        range_res = extract_symbol_or_range(tmp_path, lines_range="8-12")
        assert "class AuthService:" in range_res
        assert "lines 8-12" in range_res

        # Extract symbol
        sym_res = extract_symbol_or_range(tmp_path, symbol="verify_token")
        assert "def verify_token" in sym_res
        assert "return True" in sym_res

        # Skeleton mode
        skel_res = extract_symbol_or_range(tmp_path, skeleton=True)
        assert "class AuthService:" in skel_res
        assert "..." in skel_res
    finally:
        Path(tmp_path).unlink()
