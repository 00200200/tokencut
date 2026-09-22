"""Context packager for AI coding assistants (local, AST-compacted, secret-scrubbed)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tokencut.core.cache import ContextCache
from tokencut.core.code_index import allowed_file, source_files
from tokencut.core.redactor import redact_secrets
from tokencut.core.skeleton import extract_symbol_or_range
from tokencut.metrics.tokenizer import count_tokens


@dataclass
class PackedFile:
    path: str
    original_tokens: int
    packed_tokens: int
    is_skeleton: bool
    ref_id: str | None
    content: str


@dataclass
class PackResult:
    root: Path
    file_count: int
    original_tokens: int
    packed_tokens: int
    saved_tokens: int
    reduction_pct: float
    files: list[PackedFile]
    bundle_text: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "file_count": self.file_count,
            "original_tokens": self.original_tokens,
            "packed_tokens": self.packed_tokens,
            "saved_tokens": self.saved_tokens,
            "reduction_pct": self.reduction_pct,
            "bundle_text": self.bundle_text,
            "files": [
                {
                    "path": f.path,
                    "original_tokens": f.original_tokens,
                    "packed_tokens": f.packed_tokens,
                    "is_skeleton": f.is_skeleton,
                    "ref_id": f.ref_id,
                }
                for f in self.files
            ],
        }


def _render_bundle(
    root: Path,
    packed_files: list[PackedFile],
    budget: int,
    format_type: str = "markdown",
) -> str:
    total_packed = sum(f.packed_tokens for f in packed_files)
    if format_type.lower() == "xml":
        lines = [
            f'<documents root="{root.name}" file_count="{len(packed_files)}" estimated_tokens="{total_packed}" budget="{budget}">'
        ]
        for idx, pf in enumerate(packed_files, 1):
            is_skel = ' mode="skeleton"' if pf.is_skeleton else ' mode="full"'
            lines.append(
                f'  <document index="{idx}" path="{pf.path}" tokens="{pf.packed_tokens}"{is_skel}>'
            )
            lines.append(f"    <source>{pf.path}</source>")
            lines.append("    <document_content>")
            lines.append(pf.content.strip())
            lines.append("    </document_content>")
            lines.append("  </document>")
        lines.append("</documents>")
        return "\n".join(lines)

    header = [
        f"# TokenCut Context Bundle ({root.name})",
        f"Files: {len(packed_files)} · Estimated tokens: ~{total_packed} (Budget: {budget})",
        "",
        "## File Summary",
        "```text",
    ]
    for pf in packed_files:
        mode_str = "AST Skeleton" if pf.is_skeleton else "Full Source"
        header.append(f"{pf.path:<40} {pf.packed_tokens:>6} tok  [{mode_str}]")
    header.append("```\n")

    sections: list[str] = ["\n".join(header)]
    for pf in packed_files:
        lang = Path(pf.path).suffix.lstrip(".") or "text"
        title_suffix = " (AST Skeleton)" if pf.is_skeleton else ""
        sections.append(f"## {pf.path}{title_suffix}\n```{lang}\n{pf.content.strip()}\n```\n")
    return "\n".join(sections)


def pack_context(
    paths: list[str | Path] | None = None,
    root: Path | None = None,
    budget: int = 4000,
    force_skeleton: bool = False,
    format_type: str = "markdown",
) -> PackResult:
    """Pack repository files into an AI-optimized, token-budgeted prompt context."""
    if root is None:
        root = Path.cwd()
    root = root.resolve()

    selected_files: list[Path] = []
    if paths:
        for p in paths:
            resolved = (root / p).resolve() if not Path(p).is_absolute() else Path(p).resolve()
            if resolved.is_file() and allowed_file(resolved, root):
                selected_files.append(resolved)
            elif resolved.is_dir():
                selected_files.extend(source_files(resolved))
    else:
        selected_files = source_files(root)

    # Deduplicate while preserving order
    seen: set[Path] = set()
    files_to_pack: list[Path] = []
    for f in selected_files:
        if f not in seen and f.is_file():
            seen.add(f)
            files_to_pack.append(f)

    cache = ContextCache()
    packed_files: list[PackedFile] = []
    total_original_tokens = 0
    running_packed_tokens = 0

    # First pass: collect files and compute skeletons
    for path in files_to_pack:
        rel_str = str(path.relative_to(root))
        try:
            raw_text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        cleaned = redact_secrets(raw_text)
        orig_tok = count_tokens(cleaned).openai
        total_original_tokens += orig_tok

        # Determine if we should skeletonize
        use_skeleton = force_skeleton or (orig_tok > 250)
        packed_text = cleaned
        ref_id = None

        if use_skeleton:
            try:
                skel = extract_symbol_or_range(path, skeleton=True)
                skel_tok = count_tokens(skel).openai
                if skel_tok < orig_tok:
                    ref_id = cache.store(cleaned, source=f"pack:{rel_str}")
                    packed_text = (
                        skel
                        + f"\n# [Full implementation omitted; {orig_tok} tokens. Recover: tokencut retrieve {ref_id}]\n"
                    )
            except Exception:
                pass

        p_tok = count_tokens(packed_text).openai
        running_packed_tokens += p_tok
        packed_files.append(
            PackedFile(
                path=rel_str,
                original_tokens=orig_tok,
                packed_tokens=p_tok,
                is_skeleton=use_skeleton and (packed_text != cleaned),
                ref_id=ref_id,
                content=packed_text,
            )
        )

    # Second pass: budget enforcement
    if running_packed_tokens > budget and packed_files:
        budget_per_file = max(20, (budget - len(packed_files) * 25) // len(packed_files))
        for pf in packed_files:
            if pf.packed_tokens > budget_per_file:
                lines = pf.content.splitlines(keepends=True)
                keep_count = min(len(lines), max(4, budget_per_file // 5))
                if len(lines) > keep_count:
                    if not pf.ref_id:
                        full_path = root / pf.path
                        try:
                            orig = redact_secrets(full_path.read_text(errors="replace"))
                            pf.ref_id = cache.store(orig, source=f"pack:{pf.path}")
                        except Exception:
                            pass
                    trunc_note = (
                        f"\n# [... {len(lines) - keep_count} lines omitted. Ref: {pf.ref_id} ...]\n"
                    )
                    pf.content = "".join(lines[:keep_count]) + trunc_note
                    pf.packed_tokens = count_tokens(pf.content).openai

    bundle_text = _render_bundle(root, packed_files, budget, format_type=format_type)
    final_tokens = count_tokens(bundle_text).openai

    # Adaptive loop to strictly satisfy budget ceiling
    while final_tokens > budget and any(len(pf.content.splitlines()) > 5 for pf in packed_files):
        largest = max(packed_files, key=lambda f: f.packed_tokens)
        lines = largest.content.splitlines(keepends=True)
        if len(lines) <= 5:
            break
        new_keep = max(2, int(len(lines) * 0.5))
        if not largest.ref_id:
            try:
                full_path = root / largest.path
                orig = redact_secrets(full_path.read_text(errors="replace"))
                largest.ref_id = cache.store(orig, source=f"pack:{largest.path}")
            except Exception:
                pass
        trunc_note = f"\n# [... {len(lines) - new_keep} lines omitted. Ref: {largest.ref_id} ...]\n"
        largest.content = "".join(lines[:new_keep]) + trunc_note
        largest.packed_tokens = count_tokens(largest.content).openai

        bundle_text = _render_bundle(root, packed_files, budget, format_type=format_type)
        final_tokens = count_tokens(bundle_text).openai

    saved = max(0, total_original_tokens - final_tokens)
    pct = round((saved / total_original_tokens) * 100, 1) if total_original_tokens else 0.0

    return PackResult(
        root=root,
        file_count=len(packed_files),
        original_tokens=total_original_tokens,
        packed_tokens=final_tokens,
        saved_tokens=saved,
        reduction_pct=pct,
        files=packed_files,
        bundle_text=bundle_text,
    )
