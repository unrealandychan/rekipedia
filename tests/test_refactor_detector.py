"""Tests for refactor_detector — graph-based static analysis metrics."""
from __future__ import annotations

from rekipedia.analysis.refactor_detector import (
    RefactorConfig,
    detect_all,
    detect_circular_deps,
    detect_dead_code,
    detect_deep_inheritance,
    detect_god_nodes,
    detect_high_fan_in,
    detect_high_fan_out,
)
from rekipedia.models.contracts import Relationship, Symbol

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rel(from_: str, to: str, kind: str = "calls") -> Relationship:
    return Relationship(**{"from": from_, "to": to, "kind": kind, "file": None})


def _sym(name: str, file: str = "foo.py", kind: str = "function") -> Symbol:
    return Symbol(name=name, kind=kind, file=file)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# detect_god_nodes
# ---------------------------------------------------------------------------

def test_god_nodes_returns_top_pct() -> None:
    # Create 20 nodes with varying degree; top 5% = 1 node
    rels = [_rel("hub", f"n{i}") for i in range(15)] + [_rel(f"caller{i}", "hub") for i in range(5)]
    issues = detect_god_nodes(rels)
    assert issues, "expected at least one god node"
    assert issues[0].symbol == "hub"
    assert issues[0].kind == "god_class"
    assert issues[0].severity == "high"
    assert "total_degree" in issues[0].metrics


def test_god_nodes_empty_relationships() -> None:
    assert detect_god_nodes([]) == []


def test_god_nodes_metrics_populated() -> None:
    rels = [_rel("a", "b"), _rel("c", "a"), _rel("a", "d")]
    issues = detect_god_nodes(rels, config=RefactorConfig(god_node_top_pct=1.0))
    a_issue = next(i for i in issues if i.symbol == "a")
    assert a_issue.metrics["in_degree"] == 1
    assert a_issue.metrics["out_degree"] == 2
    assert a_issue.metrics["total_degree"] == 3


def test_god_nodes_includes_callers() -> None:
    rels = [_rel("caller1", "god"), _rel("caller2", "god"), _rel("god", "dep")]
    issues = detect_god_nodes(rels, config=RefactorConfig(god_node_top_pct=1.0))
    god_issue = next(i for i in issues if i.symbol == "god")
    assert "caller1" in god_issue.callers
    assert "caller2" in god_issue.callers


def test_god_nodes_file_from_symbol() -> None:
    rels = [_rel("a", "b"), _rel("c", "a")]
    syms = [_sym("a", "a.py")]
    issues = detect_god_nodes(rels, symbols=syms, config=RefactorConfig(god_node_top_pct=1.0))
    a_issue = next(i for i in issues if i.symbol == "a")
    assert a_issue.file == "a.py"


# ---------------------------------------------------------------------------
# detect_circular_deps
# ---------------------------------------------------------------------------

def test_circular_dep_simple_cycle() -> None:
    rels = [_rel("A", "B"), _rel("B", "C"), _rel("C", "A")]
    issues = detect_circular_deps(rels)
    assert len(issues) == 1
    assert issues[0].kind == "circular_dep"
    assert issues[0].severity == "high"
    assert "cycle" in issues[0].metrics
    assert issues[0].metrics["cycle_length"] == 3


def test_circular_dep_no_cycle() -> None:
    rels = [_rel("A", "B"), _rel("B", "C")]
    assert detect_circular_deps(rels) == []


def test_circular_dep_self_loop_excluded() -> None:
    # self-loops (A -> A) are excluded from cycle building
    rels = [_rel("A", "A")]
    assert detect_circular_deps(rels) == []


def test_circular_dep_two_cycles_deduplicated() -> None:
    # A->B->A and B->A->B are the same cycle, should appear once
    rels = [_rel("A", "B"), _rel("B", "A")]
    issues = detect_circular_deps(rels)
    assert len(issues) == 1


def test_circular_dep_callers_contains_cycle_members() -> None:
    rels = [_rel("X", "Y"), _rel("Y", "X")]
    issues = detect_circular_deps(rels)
    assert len(issues) == 1
    # callers = rest of cycle (everything after symbol)
    assert len(issues[0].callers) >= 1


# ---------------------------------------------------------------------------
# detect_dead_code
# ---------------------------------------------------------------------------

def test_dead_code_private_no_callers() -> None:
    syms = [_sym("_helper", "utils.py", "function")]
    issues = detect_dead_code([], syms)
    assert len(issues) == 1
    assert issues[0].symbol == "_helper"
    assert issues[0].kind == "dead_code"
    assert issues[0].severity == "low"


def test_dead_code_public_python_excluded() -> None:
    # public Python function → should not be flagged
    syms = [_sym("helper", "utils.py", "function")]
    issues = detect_dead_code([], syms)
    assert issues == []


def test_dead_code_go_unexported_flagged() -> None:
    syms = [_sym("parseToken", "parser.go", "function")]
    issues = detect_dead_code([], syms)
    assert len(issues) == 1
    assert issues[0].symbol == "parseToken"


def test_dead_code_go_exported_excluded() -> None:
    syms = [_sym("ParseToken", "parser.go", "function")]
    issues = detect_dead_code([], syms)
    assert issues == []


def test_dead_code_symbol_with_callers_excluded() -> None:
    rels = [_rel("caller", "_helper")]
    syms = [_sym("_helper", "utils.py")]
    issues = detect_dead_code(rels, syms)
    assert issues == []


# ---------------------------------------------------------------------------
# detect_high_fan_in
# ---------------------------------------------------------------------------

def test_high_fan_in_detected() -> None:
    cfg = RefactorConfig(high_fan_in=3)
    rels = [_rel(f"c{i}", "hotfunc") for i in range(5)]
    issues = detect_high_fan_in(rels, config=cfg)
    assert len(issues) == 1
    assert issues[0].symbol == "hotfunc"
    assert issues[0].kind == "high_fan_in"
    assert issues[0].severity == "medium"
    assert issues[0].metrics["in_degree"] == 5


def test_high_fan_in_below_threshold() -> None:
    cfg = RefactorConfig(high_fan_in=10)
    rels = [_rel(f"c{i}", "func") for i in range(5)]
    assert detect_high_fan_in(rels, config=cfg) == []


def test_high_fan_in_callers_populated() -> None:
    cfg = RefactorConfig(high_fan_in=2)
    rels = [_rel("c1", "f"), _rel("c2", "f"), _rel("c3", "f")]
    issues = detect_high_fan_in(rels, config=cfg)
    assert "c1" in issues[0].callers
    assert "c2" in issues[0].callers
    assert "c3" in issues[0].callers


# ---------------------------------------------------------------------------
# detect_high_fan_out
# ---------------------------------------------------------------------------

def test_high_fan_out_detected() -> None:
    cfg = RefactorConfig(high_fan_out=3)
    rels = [_rel("bigfunc", f"dep{i}") for i in range(5)]
    issues = detect_high_fan_out(rels, config=cfg)
    assert len(issues) == 1
    assert issues[0].symbol == "bigfunc"
    assert issues[0].kind == "high_fan_out"
    assert issues[0].severity == "medium"
    assert issues[0].metrics["out_degree"] == 5


def test_high_fan_out_below_threshold() -> None:
    cfg = RefactorConfig(high_fan_out=10)
    rels = [_rel("func", f"dep{i}") for i in range(5)]
    assert detect_high_fan_out(rels, config=cfg) == []


def test_high_fan_out_callers_contains_deps() -> None:
    cfg = RefactorConfig(high_fan_out=2)
    rels = [_rel("f", "d1"), _rel("f", "d2"), _rel("f", "d3")]
    issues = detect_high_fan_out(rels, config=cfg)
    assert "d1" in issues[0].callers
    assert "d2" in issues[0].callers
    assert "d3" in issues[0].callers


# ---------------------------------------------------------------------------
# detect_deep_inheritance
# ---------------------------------------------------------------------------

def test_deep_inheritance_detected() -> None:
    # A inherits B, B inherits C, C inherits D → depth=3
    rels = [
        _rel("A", "B", "inherits"),
        _rel("B", "C", "inherits"),
        _rel("C", "D", "inherits"),
    ]
    cfg = RefactorConfig(deep_inheritance_depth=2)
    issues = detect_deep_inheritance(rels, config=cfg)
    assert len(issues) == 1
    assert issues[0].symbol == "A"
    assert issues[0].kind == "deep_inheritance"
    assert issues[0].severity == "medium"
    assert issues[0].metrics["depth"] == 3


def test_deep_inheritance_within_threshold() -> None:
    rels = [_rel("A", "B", "inherits"), _rel("B", "C", "inherits")]
    cfg = RefactorConfig(deep_inheritance_depth=3)
    assert detect_deep_inheritance(rels, config=cfg) == []


def test_deep_inheritance_chain_in_metrics() -> None:
    rels = [
        _rel("A", "B", "inherits"),
        _rel("B", "C", "inherits"),
        _rel("C", "D", "inherits"),
    ]
    cfg = RefactorConfig(deep_inheritance_depth=2)
    issues = detect_deep_inheritance(rels, config=cfg)
    assert "chain" in issues[0].metrics
    chain = issues[0].metrics["chain"]
    assert "A" in chain and "B" in chain


def test_deep_inheritance_non_inherits_ignored() -> None:
    # "calls" relationships should not count for inheritance depth
    rels = [_rel("A", "B", "calls"), _rel("B", "C", "calls"), _rel("C", "D", "calls")]
    cfg = RefactorConfig(deep_inheritance_depth=1)
    assert detect_deep_inheritance(rels, config=cfg) == []


# ---------------------------------------------------------------------------
# detect_all
# ---------------------------------------------------------------------------

def test_detect_all_returns_multiple_kinds() -> None:
    rels = [
        # circular dep
        _rel("X", "Y"),
        _rel("Y", "X"),
        # high fan-in
        *[_rel(f"c{i}", "hotfunc") for i in range(25)],
    ]
    syms = [_sym("_dead", "utils.py")]
    cfg = RefactorConfig(high_fan_in=20, high_fan_out=15, god_node_top_pct=0.5)
    issues = detect_all(rels, syms, cfg)
    kinds = {i.kind for i in issues}
    assert "circular_dep" in kinds
    assert "dead_code" in kinds
    assert "high_fan_in" in kinds


def test_detect_all_empty_input() -> None:
    assert detect_all([], []) == []
