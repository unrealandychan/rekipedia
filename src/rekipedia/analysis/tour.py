"""reki tour — build a guided learning walkthrough sorted by dependency depth."""
from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# ── phase definitions ──────────────────────────────────────────────────────
_PHASES = [
    (1, "Foundation",    "Start here — these modules have no internal dependencies.",   (0, 0)),
    (2, "Core Logic",    "Internal library code with minimal dependencies.",            (1, 3)),
    (3, "Services",      "Orchestration and business logic modules.",                   (4, 8)),
    (4, "Entry Points",  "CLI, main modules, and high-level orchestration.",            (9, 10**9)),
]


def _get_description(file_path: str, output_dir: Path) -> str:
    """Try to read description from wiki page, fall back to stem."""
    wiki_dir = output_dir / ".rekipedia" / "wiki"
    # convert file path to likely wiki page name
    stem = Path(file_path).stem
    candidates = list(wiki_dir.glob(f"**/{stem}.md")) if wiki_dir.exists() else []
    if candidates:
        try:
            text = candidates[0].read_text(errors="replace")
        except OSError:
            return stem.replace("_", " ").capitalize()
        # skip frontmatter
        lines = text.splitlines()
        in_front = False
        content_lines: list[str] = []
        i = 0
        if lines and lines[0].strip() == "---":
            in_front = True
            i = 1
        while i < len(lines):
            if in_front and lines[i].strip() == "---":
                in_front = False
                i += 1
                continue
            if not in_front and lines[i].strip():
                content_lines.append(lines[i].strip())
            elif content_lines:
                break
            i += 1
        if content_lines:
            para = " ".join(content_lines)
            # strip markdown headings
            para = para.lstrip("#").strip()
            if para:
                return para[:200]
    return stem.replace("_", " ").capitalize()


def build_tour(store: Any, run_id: str, output_dir: Path) -> dict:
    """Build a guided learning walkthrough from the store."""
    output_dir = Path(output_dir)
    symbols = store.get_all_symbols(run_id)
    relationships: list[dict] = store.get_all_relationships(run_id)

    def _symbol_field(sym: Any, key: str) -> str:
        if isinstance(sym, dict):
            return str(sym.get(key) or "")
        if hasattr(sym, "keys"):
            return str(sym[key] or "")
        if not isinstance(sym, tuple):
            return ""
        # scan_symbols column order:
        # run_id(0), name(1), kind(2), file(3), line_start(4), ...
        if key == "name":
            return str(sym[1]) if len(sym) > 1 and sym[1] is not None else ""
        if key == "kind":
            return str(sym[2]) if len(sym) > 2 and sym[2] is not None else ""
        if key == "file":
            return str(sym[3]) if len(sym) > 3 and sym[3] is not None else ""
        return ""

    # collect all file paths from symbols
    all_files: set[str] = set()
    file_symbols: dict[str, list[Any]] = defaultdict(list)
    for sym in symbols:
        f = _symbol_field(sym, "file")
        if f:
            all_files.add(f)
            file_symbols[f].append(sym)

    # build file-level graph from relationships
    # a relationship from_ -> to means `from_` depends on `to`
    # in-degree = number of files that the file depends on (imports)
    file_deps: dict[str, set[str]] = defaultdict(set)  # file -> files it imports
    sym_to_file: dict[str, str] = {}
    for sym in symbols:
        name = _symbol_field(sym, "name")
        f = _symbol_field(sym, "file")
        if name and f:
            sym_to_file[name] = f

    for rel in relationships:
        kind = rel.get("kind", "")
        if kind not in ("imports", "calls", "uses"):
            continue
        from_sym = rel.get("from_", "")
        to_sym = rel.get("to", "")
        from_file = sym_to_file.get(from_sym) or rel.get("file", "")
        to_file = sym_to_file.get(to_sym, "")
        if from_file and to_file and from_file != to_file:
            all_files.add(from_file)
            all_files.add(to_file)
            file_deps[from_file].add(to_file)

    # compute in-degree = how many unique files this file depends on
    in_degree: dict[str, int] = {f: len(file_deps[f]) for f in all_files}

    # assign phases
    phase_files: dict[int, list[dict]] = defaultdict(list)
    for f in sorted(all_files):
        deg = in_degree.get(f, 0)
        phase_num = 4  # default
        for pnum, pname, pdesc, (lo, hi) in _PHASES:
            if lo <= deg <= hi:
                phase_num = pnum
                break
        # pick top 3 symbols: prefer class/function, then by name length desc
        syms = sorted(
            file_symbols.get(f, []),
            key=lambda s: (
                0 if _symbol_field(s, "kind") in ("class", "function") else 1,
                -len(_symbol_field(s, "name")),
            ),
        )[:3]
        sym_names = [_symbol_field(s, "name") for s in syms if _symbol_field(s, "name")]
        desc = _get_description(f, output_dir)
        phase_files[phase_num].append({"path": f, "symbols": sym_names, "description": desc})

    # build phases list (only non-empty)
    phases_out: list[dict] = []
    for pnum, pname, pdesc, _ in _PHASES:
        files = phase_files.get(pnum, [])
        if files or True:  # always include all phases for completeness
            phases_out.append({
                "phase": pnum,
                "name": pname,
                "description": pdesc,
                "files": files,
            })

    # determine repo root
    repo_root = str(output_dir.resolve())

    return {
        "repo": repo_root,
        "generated_at": datetime.now(UTC).isoformat(),
        "total_files": len(all_files),
        "phases": phases_out,
    }
