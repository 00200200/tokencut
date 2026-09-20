from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rich.tree import Tree

from tokencut.metrics.tokenizer import count_tokens

IGNORE_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "dist",
    "build",
    ".idea",
    ".vscode",
}

IGNORE_EXTENSIONS = {
    ".pyc",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".svg",
    ".woff",
    ".woff2",
    ".zip",
    ".tar",
    ".gz",
}


@dataclass
class FileTokenNode:
    path: Path
    rel_path: str
    tokens: int
    is_dir: bool
    children: list[FileTokenNode]


def scan_directory(root: Path, max_depth: int = 3) -> tuple[FileTokenNode, list[tuple[str, int]]]:
    all_files: list[tuple[str, int]] = []

    def _walk(curr: Path, depth: int) -> FileTokenNode:
        rel = str(curr.relative_to(root)) if curr != root else "."
        if curr.is_file():
            if curr.suffix in IGNORE_EXTENSIONS or curr.name.startswith("."):
                return FileTokenNode(curr, rel, 0, False, [])
            try:
                # Cap file read at 1MB to keep scan instant
                if curr.stat().st_size > 1_000_000:
                    tok = curr.stat().st_size // 4
                else:
                    text = curr.read_text(encoding="utf-8", errors="replace")
                    tok = count_tokens(text).avg
            except Exception:
                tok = 0
            all_files.append((rel, tok))
            return FileTokenNode(curr, rel, tok, False, [])

        # Directory
        children: list[FileTokenNode] = []
        dir_tokens = 0
        if depth <= max_depth:
            try:
                entries = sorted(curr.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
                for entry in entries:
                    if entry.name in IGNORE_DIRS or entry.name.startswith("."):
                        continue
                    child_node = _walk(entry, depth + 1)
                    if child_node.tokens > 0:
                        children.append(child_node)
                        dir_tokens += child_node.tokens
            except PermissionError:
                pass

        return FileTokenNode(curr, rel, dir_tokens, True, children)

    tree_root = _walk(root, 0)
    all_files.sort(key=lambda x: x[1], reverse=True)
    return tree_root, all_files


def format_token_badge(tokens: int, total_tokens: int) -> str:
    pct = (tokens / total_tokens * 100) if total_tokens > 0 else 0
    if tokens > 5000:
        return f"[bold red]{tokens:,} tok ({pct:.1f}%)[/bold red]"
    elif tokens > 1500:
        return f"[yellow]{tokens:,} tok ({pct:.1f}%)[/yellow]"
    else:
        return f"[green]{tokens:,} tok ({pct:.1f}%)[/green]"


def render_tree(node: FileTokenNode, total_tokens: int, rich_tree: Tree | None = None) -> Tree:
    label = f"{node.path.name}/ " if node.is_dir else f"{node.path.name} "
    badge = format_token_badge(node.tokens, total_tokens)

    if rich_tree is None:
        tree = Tree(f"[bold cyan]{label}[/bold cyan] · {badge}")
    else:
        tree = rich_tree.add(f"{label}· {badge}")

    for child in node.children:
        if child.is_dir:
            render_tree(child, total_tokens, tree)
        else:
            c_badge = format_token_badge(child.tokens, total_tokens)
            tree.add(f"[dim]{child.path.name}[/dim] · {c_badge}")

    return tree
