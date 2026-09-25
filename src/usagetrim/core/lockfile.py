"""Intelligent lockfile parser, summarizer, package inspector, and diff delta extractor.

Provides ~90-98% token reduction when reading lockfiles by summarizing direct dependencies,
total packages, and supporting targeted package queries without loading entire lockfile ASTs.
"""

from __future__ import annotations

import json
import re

LOCKFILE_NAMES = frozenset(
    {
        "package-lock.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "cargo.lock",
        "uv.lock",
        "poetry.lock",
        "gemfile.lock",
        "composer.lock",
        "go.sum",
    }
)

LOCKFILE_REGEX = re.compile(
    r"(?:package-lock\.json|yarn\.lock|pnpm-lock\.yaml|uv\.lock|poetry\.lock|Cargo\.lock|Gemfile\.lock|composer\.lock|go\.sum)$",
    re.IGNORECASE,
)


def is_lockfile(filename_or_path: str) -> bool:
    """Return True if the given path or filename is a recognized package manager lockfile."""
    clean = filename_or_path.replace("\\", "/").rstrip("/").split("/")[-1].lower()
    return clean in LOCKFILE_NAMES or bool(LOCKFILE_REGEX.search(clean))


def summarize_lockfile(
    content: str,
    filename: str,
    query_package: str | None = None,
    max_direct: int = 40,
) -> str:
    """Produce a concise, token-efficient summary of a lockfile or query a specific package."""
    clean_name = filename.replace("\\", "/").rstrip("/").split("/")[-1].lower()

    if clean_name == "package-lock.json":
        return _summarize_npm_lock(content, query_package, max_direct)
    elif clean_name == "cargo.lock":
        return _summarize_cargo_lock(content, query_package, max_direct)
    elif clean_name in {"uv.lock", "poetry.lock"}:
        return _summarize_python_lock(content, clean_name, query_package, max_direct)
    elif clean_name == "yarn.lock":
        return _summarize_yarn_lock(content, query_package, max_direct)
    elif clean_name == "pnpm-lock.yaml":
        return _summarize_pnpm_lock(content, query_package, max_direct)
    elif clean_name == "go.sum":
        return _summarize_go_sum(content, query_package, max_direct)
    else:
        return _summarize_generic_lock(content, clean_name, query_package, max_direct)


def _summarize_npm_lock(content: str, query: str | None, max_direct: int) -> str:
    try:
        data = json.loads(content)
    except Exception:
        return _summarize_generic_lock(content, "package-lock.json", query, max_direct)

    # If query specified, locate package
    if query:
        clean_q = query.strip().lower()
        # npm v2/v3 packages map
        packages = data.get("packages", {})
        matched_key = None
        matched_val = None

        for k, v in packages.items():
            pkg_name = k.replace("node_modules/", "").strip().lower()
            if pkg_name == clean_q:
                matched_key = k
                matched_val = v
                break

        if not matched_val:
            # Fallback to dependencies map
            deps = data.get("dependencies", {})
            for k, v in deps.items():
                if k.strip().lower() == clean_q:
                    matched_key = k
                    matched_val = v
                    break

        if matched_val:
            body = json.dumps({matched_key: matched_val}, indent=2)
            return f"# [usagetrim: package-lock.json -> package '{query}']\n{body}"
        return f"# [usagetrim: package '{query}' not found in package-lock.json]"

    # General summary
    total_packages = 0
    direct_deps: dict[str, str] = {}

    packages = data.get("packages", {})
    if packages:
        # npm v2 / v3
        root_pkg = packages.get("", {})
        root_deps = {**root_pkg.get("dependencies", {}), **root_pkg.get("devDependencies", {})}
        total_packages = sum(1 for k in packages if k)

        for dep_name in sorted(root_deps.keys()):
            # Find version in packages
            sub_key = f"node_modules/{dep_name}"
            if sub_key in packages:
                version = packages[sub_key].get("version", root_deps[dep_name])
            else:
                version = root_deps[dep_name]
            direct_deps[dep_name] = version
    else:
        # npm v1 format
        deps = data.get("dependencies", {})
        total_packages = len(deps)
        for dep_name, dep_info in sorted(deps.items()):
            direct_deps[dep_name] = dep_info.get("version", "unknown")

    lines = [
        f"# [usagetrim: Lockfile 'package-lock.json' - {len(direct_deps)} direct, {total_packages} total packages]",
        "# Direct dependencies:",
    ]
    for name, ver in list(direct_deps.items())[:max_direct]:
        lines.append(f"  {name}: {ver}")

    if len(direct_deps) > max_direct:
        lines.append(
            f"  [... {len(direct_deps) - max_direct} more direct dependencies omitted ...]"
        )

    lines.append(
        "# (Use symbol='<name>' to view package details or usagetrim_retrieve for full lockfile)"
    )
    return "\n".join(lines)


def _summarize_cargo_lock(content: str, query: str | None, max_direct: int) -> str:
    # Cargo.lock format: [[package]]\nname = "..."\nversion = "..."
    pkg_blocks = re.findall(
        r'\[\[package\]\]\nname\s*=\s*"([^"]+)"\nversion\s*=\s*"([^"]+)"((?:(?!\n\[\[package\]\]).)*)',
        content,
        re.DOTALL,
    )

    if not pkg_blocks:
        return _summarize_generic_lock(content, "Cargo.lock", query, max_direct)

    if query:
        clean_q = query.strip().lower()
        for name, version, rest in pkg_blocks:
            if name.lower() == clean_q:
                block_text = f'[[package]]\nname = "{name}"\nversion = "{version}"{rest}'.strip()
                return f"# [usagetrim: Cargo.lock -> package '{name}']\n{block_text}"
        return f"# [usagetrim: package '{query}' not found in Cargo.lock]"

    packages: dict[str, str] = {}
    for name, version, _ in pkg_blocks:
        packages[name] = version

    lines = [
        f"# [usagetrim: Lockfile 'Cargo.lock' - {len(packages)} packages locked]",
        "# Packages (sample):",
    ]
    for name, ver in list(packages.items())[:max_direct]:
        lines.append(f"  {name}: {ver}")

    if len(packages) > max_direct:
        lines.append(f"  [... {len(packages) - max_direct} more packages omitted ...]")

    lines.append(
        "# (Use symbol='<name>' to view package details or usagetrim_retrieve for full lockfile)"
    )
    return "\n".join(lines)


def _summarize_python_lock(content: str, filename: str, query: str | None, max_direct: int) -> str:
    # uv.lock and poetry.lock TOML style: [[package]] name = "..." version = "..."
    pkg_blocks = re.findall(
        r'\[\[package\]\]\s*\nname\s*=\s*"([^"]+)"\s*\nversion\s*=\s*"([^"]+)"((?:(?!\n\[\[package\]\]).)*)',
        content,
        re.DOTALL,
    )

    if not pkg_blocks:
        # Fallback to key-value scanning
        pkg_blocks_simple = re.findall(
            r'name\s*=\s*"([^"]+)"\s*\nversion\s*=\s*"([^"]+)"',
            content,
        )
        pkg_blocks = [(name, ver, "") for name, ver in pkg_blocks_simple]

    if not pkg_blocks:
        return _summarize_generic_lock(content, filename, query, max_direct)

    if query:
        clean_q = query.strip().lower()
        for name, version, rest in pkg_blocks:
            if name.lower() == clean_q:
                block_text = f'[[package]]\nname = "{name}"\nversion = "{version}"{rest}'.strip()
                return f"# [usagetrim: {filename} -> package '{name}']\n{block_text}"
        return f"# [usagetrim: package '{query}' not found in {filename}]"

    packages: dict[str, str] = {}
    for name, version, _ in pkg_blocks:
        packages[name] = version

    lines = [
        f"# [usagetrim: Lockfile '{filename}' - {len(packages)} packages locked]",
        "# Packages:",
    ]
    for name, ver in list(packages.items())[:max_direct]:
        lines.append(f"  {name}: {ver}")

    if len(packages) > max_direct:
        lines.append(f"  [... {len(packages) - max_direct} more packages omitted ...]")

    lines.append(
        "# (Use symbol='<name>' to view package details or usagetrim_retrieve for full lockfile)"
    )
    return "\n".join(lines)


def _summarize_yarn_lock(content: str, query: str | None, max_direct: int) -> str:
    entries = re.findall(
        r'(?:^|\n)("?([^"\n@:]+)[^:\n]*"?):\s*\n\s+version(?::|\s+)["\']?([^"\'\n]+)["\']?',
        content,
    )
    if not entries:
        return _summarize_generic_lock(content, "yarn.lock", query, max_direct)

    if query:
        query = query.strip()
        section = re.search(
            rf'(?:^|\n)(("?{re.escape(query)}@[^:\n]*"?):.*?\n(?=\S|$))',
            content,
            re.DOTALL | re.IGNORECASE,
        )
        if section:
            return f"# [usagetrim: yarn.lock -> package '{query}']\n{section.group(1).strip()}"
        return f"# [usagetrim: package '{query}' not found in yarn.lock]"

    packages: dict[str, str] = {}
    for _, name, ver in entries:
        if name not in packages:
            packages[name] = ver

    lines = [
        f"# [usagetrim: Lockfile 'yarn.lock' - {len(packages)} packages locked]",
        "# Packages:",
    ]
    for name, ver in list(packages.items())[:max_direct]:
        lines.append(f"  {name}: {ver}")

    if len(packages) > max_direct:
        lines.append(f"  [... {len(packages) - max_direct} more packages omitted ...]")

    lines.append(
        "# (Use symbol='<name>' to view package details or usagetrim_retrieve for full lockfile)"
    )
    return "\n".join(lines)


def _summarize_pnpm_lock(content: str, query: str | None, max_direct: int) -> str:
    pkgs = re.findall(r"['\"]?(/[^@'\"]+@[^:'\"]+)['\"]?:", content)
    if not pkgs:
        pkgs_simple = re.findall(r"['\"]?([^@'\":\s]+)@([^:'\"\s]+)['\"]?:", content)
        pkgs = [f"{n}@{v}" for n, v in pkgs_simple]

    if query:
        query = query.strip()
        section = re.search(
            rf'(?:^|\n)([\s\'"-]*{re.escape(query)}@.*?\n(?=(?:  \S|\S)|$))',
            content,
            re.DOTALL | re.IGNORECASE,
        )
        if section:
            return f"# [usagetrim: pnpm-lock.yaml -> package '{query}']\n{section.group(1).strip()}"
        return f"# [usagetrim: package '{query}' not found in pnpm-lock.yaml]"

    lines = [
        f"# [usagetrim: Lockfile 'pnpm-lock.yaml' - {len(pkgs)} packages locked]",
        "# Packages (sample):",
    ]
    for p in pkgs[:max_direct]:
        clean_p = p.lstrip("/").replace("@", ": ", 1)
        lines.append(f"  {clean_p}")

    if len(pkgs) > max_direct:
        lines.append(f"  [... {len(pkgs) - max_direct} more packages omitted ...]")

    lines.append(
        "# (Use symbol='<name>' to view package details or usagetrim_retrieve for full lockfile)"
    )
    return "\n".join(lines)


def _summarize_go_sum(content: str, query: str | None, max_direct: int) -> str:
    modules: dict[str, set[str]] = {}
    for line in content.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2:
            mod, ver = parts[0], parts[1].split("/")[0]
            modules.setdefault(mod, set()).add(ver)

    if query:
        clean_q = query.strip().lower()
        matched = [
            line
            for line in content.splitlines()
            if line.strip().lower().startswith(clean_q) or clean_q in line.lower()
        ]
        if matched:
            return f"# [usagetrim: go.sum -> module '{query}']\n" + "\n".join(matched[:30])
        return f"# [usagetrim: module '{query}' not found in go.sum]"

    lines = [
        f"# [usagetrim: Lockfile 'go.sum' - {len(modules)} modules locked]",
        "# Modules:",
    ]
    for mod, vers in sorted(modules.items())[:max_direct]:
        lines.append(f"  {mod}: {', '.join(sorted(vers))}")

    if len(modules) > max_direct:
        lines.append(f"  [... {len(modules) - max_direct} more modules omitted ...]")

    lines.append(
        "# (Use symbol='<name>' to view module details or usagetrim_retrieve for full lockfile)"
    )
    return "\n".join(lines)


def _summarize_generic_lock(content: str, filename: str, query: str | None, max_direct: int) -> str:
    lines = content.splitlines()
    if query:
        clean_q = query.strip().lower()
        matches = [line for line in lines if clean_q in line.lower()]
        if matches:
            return f"# [usagetrim: {filename} -> match for '{query}']\n" + "\n".join(matches[:25])
        return f"# [usagetrim: '{query}' not found in {filename}]"

    head = lines[:max_direct]
    return (
        f"# [usagetrim: Lockfile '{filename}' - {len(lines)} lines locked]\n"
        + "\n".join(head)
        + f"\n  [... {len(lines) - len(head)} lines omitted by usagetrim; use symbol='<name>' or usagetrim_retrieve ...]"
    )


def extract_lockfile_diff_delta(diff_lines: list[str], filename: str) -> str:
    """Analyze unified diff lines of a lockfile and summarize added/bumped/removed packages."""
    added: dict[str, str] = {}
    removed: dict[str, str] = {}

    clean_name = filename.replace("\\", "/").rstrip("/").split("/")[-1].lower()

    if clean_name == "package-lock.json":
        pkg_pattern = re.compile(r'^[+-]\s*"node_modules/([^"]+)":')
        ver_pattern = re.compile(r'^[+-]\s*"version":\s*"([^"]+)"')
        current_pkg = ""

        for line in diff_lines:
            m_pkg = pkg_pattern.match(line)
            if m_pkg:
                current_pkg = m_pkg.group(1)
                continue
            m_ver = ver_pattern.match(line)
            if m_ver and current_pkg:
                ver = m_ver.group(1)
                if line.startswith("+"):
                    added[current_pkg] = ver
                elif line.startswith("-"):
                    removed[current_pkg] = ver
                current_pkg = ""
    elif clean_name in {"cargo.lock", "uv.lock", "poetry.lock"}:
        name_pat = re.compile(r'^[+-]\s*name\s*=\s*"([^"]+)"')
        ver_pat = re.compile(r'^[+-]\s*version\s*=\s*"([^"]+)"')
        cur_name = ""
        for line in diff_lines:
            m_name = name_pat.match(line)
            if m_name:
                cur_name = m_name.group(1)
                continue
            m_ver = ver_pat.match(line)
            if m_ver and cur_name:
                ver = m_ver.group(1)
                if line.startswith("+"):
                    added[cur_name] = ver
                elif line.startswith("-"):
                    removed[cur_name] = ver
                cur_name = ""
    else:
        for line in diff_lines:
            if line.startswith("+") and not line.startswith("+++"):
                m = re.search(
                    r'["\']?([a-zA-Z0-9_\-./@]+)["\']?\s*[:=]\s*["\']?v?([0-9]+\.[0-9]+[^"\'\s,]*?)["\']?',
                    line,
                )
                if m and len(added) < 20:
                    added[m.group(1)] = m.group(2)
            elif line.startswith("-") and not line.startswith("---"):
                m = re.search(
                    r'["\']?([a-zA-Z0-9_\-./@]+)["\']?\s*[:=]\s*["\']?v?([0-9]+\.[0-9]+[^"\'\s,]*?)["\']?',
                    line,
                )
                if m and len(removed) < 20:
                    removed[m.group(1)] = m.group(2)

    changes: list[str] = []
    common = set(added.keys()) & set(removed.keys())
    for pkg in sorted(common):
        changes.append(f"~ {pkg} ({removed[pkg]} -> {added[pkg]})")
    for pkg in sorted(set(added.keys()) - common):
        changes.append(f"+ {pkg}@{added[pkg]}")
    for pkg in sorted(set(removed.keys()) - common):
        changes.append(f"- {pkg}@{removed[pkg]}")

    if not changes:
        return ""

    if len(changes) > 8:
        extra = len(changes) - 8
        changes = changes[:8] + [f"... +{extra} more"]

    return ", ".join(changes)
