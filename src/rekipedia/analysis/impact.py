"""Blast-radius / impact analysis for rekipedia."""
from __future__ import annotations
from collections import deque

# Relationship kinds that represent a dependency — changing the target
# may affect the source. Extend this set to widen the blast radius.
_IMPACT_EDGE_KINDS: frozenset[str] = frozenset({"calls", "imports", "inherits", "uses"})


def compute_impact(
    target_file: str,
    relationships: list,
    symbols: list,
    depth: int = 2,
) -> dict:
    """BFS from target_file through reverse dependency graph.
    Returns affected_files, affected_symbols, related_tests.
    """
    # Build maps
    sym_by_file: dict[str, list[str]] = {}
    sym_file: dict[str, str] = {}
    for s in symbols:
        name = s.name if hasattr(s, "name") else s.get("name", "")
        file = s.file if hasattr(s, "file") else s.get("file", "")
        sym_file[name] = file
        sym_by_file.setdefault(file, []).append(name)

    # Build reverse call graph: sym -> list of syms that call it
    reverse: dict[str, list[str]] = {}
    for rel in relationships:
        frm = rel.from_ if hasattr(rel, "from_") else rel.get("from_", "") or rel.get("from", "")
        to = rel.to if hasattr(rel, "to") else rel.get("to", "")
        kind = rel.kind if hasattr(rel, "kind") else rel.get("kind", "")
        if kind in _IMPACT_EDGE_KINDS and frm and to:
            reverse.setdefault(to, []).append(frm)

    # Seed: all symbols in target_file
    seeds = set(sym_by_file.get(target_file, []))

    # BFS
    visited: set[str] = set(seeds)
    queue: deque[tuple[str, int]] = deque((s, 0) for s in seeds)
    while queue:
        sym, d = queue.popleft()
        if d >= depth:
            continue
        for caller in reverse.get(sym, []):
            if caller not in visited:
                visited.add(caller)
                queue.append((caller, d + 1))

    affected_symbols = sorted(visited - seeds)
    affected_files = sorted({sym_file[s] for s in affected_symbols if s in sym_file})
    related_tests = sorted({f for f in affected_files if "test" in f.lower()})

    return {
        "target_file": target_file,
        "depth": depth,
        "seed_symbols": sorted(seeds),
        "affected_symbols": affected_symbols,
        "affected_files": affected_files,
        "related_tests": related_tests,
        "total_affected": len(affected_symbols),
    }
