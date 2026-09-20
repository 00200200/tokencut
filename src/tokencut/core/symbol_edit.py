"""Guarded symbol replacement for use through the client's native shell tool."""

from __future__ import annotations

import difflib
import os
import stat
import tempfile
from pathlib import Path

from tokencut.core.code_index import digest, select_symbol


def replace_symbol(
    path: Path, selector: str, replacement: str, expected_hash: str, *, apply=False
) -> str:
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise ValueError("Use an absolute, regular, non-symlink file path")
    source = path.read_bytes().decode("utf-8")
    if digest(source) != expected_hash:
        raise ValueError(
            "File changed: expected_hash does not match. Read the current symbol first."
        )
    original_stat = path.stat()
    symbol = select_symbol(source, path, selector)
    # A replacement covers exactly the displayed declaration including indentation;
    # preserve the original file's newline convention and surrounding bytes.
    newline = "\r\n" if "\r\n" in source else "\n"
    replacement = replacement.replace("\r\n", "\n").rstrip("\n").replace("\n", newline)
    updated = source[: symbol.start] + replacement + source[symbol.end :]
    updated_symbol = select_symbol(updated, path, symbol.qualified + "@" + str(symbol.line))
    if updated_symbol.qualified != symbol.qualified:
        raise ValueError("Replacement must preserve the symbol name and scope")
    diff = "".join(
        difflib.unified_diff(
            source.splitlines(keepends=True),
            updated.splitlines(keepends=True),
            fromfile=str(path),
            tofile=str(path),
        )
    )
    if not apply:
        return "# Preview only; use --apply with the same expected hash to write.\n" + diff
    if updated == source:
        return "Unchanged."
    fd, temporary = tempfile.mkstemp(prefix=".tokencut-edit-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(updated.encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, stat.S_IMODE(original_stat.st_mode))
        # Detect a concurrent editor change after parsing/preparing the patch.
        if (
            path.is_symlink()
            or path.stat().st_ino != original_stat.st_ino
            or digest(path.read_bytes().decode("utf-8")) != expected_hash
        ):
            raise ValueError("File changed while preparing replacement; no write performed")
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return (
        f"Updated {path.name}:{symbol.line} {symbol.qualified}; sha256={digest(updated)}\n" + diff
    )
