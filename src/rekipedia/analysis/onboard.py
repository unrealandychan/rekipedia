"""
onboard.py — Generate an onboarding guide for new developers.

Builds a structured guide from existing rekipedia data:
- Project overview (from README if found, else from most-connected nodes)
- Architecture summary (from domain layer classification)
- Getting-started steps (entry point files, test commands, build commands)
- Key modules to read first (hub nodes by connectivity)
- Common patterns (top symbol kinds)
- Links to generated wiki pages
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path


def build_onboard_guide(store_path: Path, repo_root: Path) -> dict:
    """
    Returns:
    {
        "repo": str,
        "generated_at": "ISO",
        "overview": str,
        "getting_started": [{"step": 1, "title": "...", "cmd": "..."}, ...],
        "key_modules": [{"path": "...", "description": "Top module", "symbols": [...]}],
        "architecture": {"layers": {"Service": 8, "Utility": 29, ...}},
        "patterns": [{"kind": "function", "count": 142}],
        "wiki_dir": str | None
    }
    """
    from rekipedia.analysis.domain import _classify_file
    from rekipedia.storage.sqlite_store import SqliteStore

    symbol_count = 0
    file_count = 0
    key_modules: list[dict] = []
    patterns: list[dict] = []
    layers: dict[str, int] = {}

    with SqliteStore(store_path) as store:
        run_id = store.get_latest_run_id(str(repo_root))

        if run_id:
            symbols = store.get_all_symbols(run_id)
            symbol_count = len(symbols)

            # Group by file
            by_file: dict[str, list] = {}
            for s in symbols:
                if isinstance(s, dict):
                    f, name, kind = s.get("file"), s.get("name"), s.get("kind")
                elif hasattr(s, "keys"):
                    f, name, kind = s["file"], s["name"], s["kind"]
                else:  # tuple: run_id(0), name(1), kind(2), file(3)
                    name = s[1] if len(s) > 1 else None
                    kind = s[2] if len(s) > 2 else None
                    f = s[3] if len(s) > 3 else None
                if f:
                    by_file.setdefault(f, []).append((name, kind))

            file_count = len(by_file)

            # Top 5 hub modules
            sorted_files = sorted(by_file.items(), key=lambda x: -len(x[1]))
            for f, syms in sorted_files[:5]:
                key_modules.append({
                    "path": f,
                    "description": "Top module",
                    "symbols": [s[0] for s in syms[:5] if s[0]],
                    "count": len(syms),
                })

            # Pattern counts
            kind_counts: dict[str, int] = {}
            for syms in by_file.values():
                for _, k in syms:
                    if k:
                        kind_counts[k] = kind_counts.get(k, 0) + 1
            patterns = [
                {"kind": k, "count": c}
                for k, c in sorted(kind_counts.items(), key=lambda x: -x[1])
            ]

            # Layer classification
            for f in by_file:
                layer = _classify_file(f)
                layers[layer] = layers.get(layer, 0) + 1

    # Overview: try README
    overview = f"{file_count} files, {symbol_count} symbols"
    for readme_name in ("README.md", "README.rst", "README.txt", "readme.md"):
        readme = repo_root / readme_name
        if readme.exists():
            text = readme.read_text(errors="replace")
            for para in text.split("\n\n"):
                stripped = para.strip()
                lines = [l for l in stripped.splitlines() if not l.startswith("#") and l.strip()]
                if lines:
                    overview = " ".join(lines)
                    break
            break

    # Getting-started steps
    steps: list[dict] = []
    step_num = 1

    if (repo_root / "pyproject.toml").exists() or (repo_root / "setup.py").exists():
        steps.append({"step": step_num, "title": "Install deps", "cmd": "pip install -e ."})
        step_num += 1
    elif (repo_root / "package.json").exists():
        steps.append({"step": step_num, "title": "Install deps", "cmd": "npm install"})
        step_num += 1
    elif (repo_root / "Cargo.toml").exists():
        steps.append({"step": step_num, "title": "Build", "cmd": "cargo build"})
        step_num += 1
    elif (repo_root / "go.mod").exists():
        steps.append({"step": step_num, "title": "Build", "cmd": "go build ./..."})
        step_num += 1

    if (repo_root / "pytest.ini").exists() or (repo_root / "pyproject.toml").exists():
        steps.append({"step": step_num, "title": "Run tests", "cmd": "pytest"})
        step_num += 1
    elif (repo_root / "package.json").exists():
        steps.append({"step": step_num, "title": "Run tests", "cmd": "npm test"})
        step_num += 1
    elif (repo_root / "Cargo.toml").exists():
        steps.append({"step": step_num, "title": "Run tests", "cmd": "cargo test"})
        step_num += 1

    steps.append({"step": step_num, "title": "Scan codebase", "cmd": "reki scan ."})
    step_num += 1
    steps.append({"step": step_num, "title": "Explore", "cmd": 'reki ask "how does X work?"'})
    step_num += 1
    steps.append({"step": step_num, "title": "Tour", "cmd": "reki tour ."})

    wiki_dir = repo_root / ".rekipedia" / "wiki"
    wiki_dir_str = str(wiki_dir) if wiki_dir.exists() else None

    return {
        "repo": str(repo_root),
        "generated_at": datetime.now(UTC).isoformat(),
        "overview": overview,
        "getting_started": steps,
        "key_modules": key_modules,
        "architecture": {"layers": layers},
        "patterns": patterns,
        "wiki_dir": wiki_dir_str,
        "_counts": {"files": file_count, "symbols": symbol_count},
    }
