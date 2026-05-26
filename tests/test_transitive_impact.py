"""Tests for compute_transitive_impact BFS."""
from rekipedia.analysis.impact import compute_transitive_impact


def _rel(frm, to):
    return {"from_": frm, "to": to, "kind": "calls"}


def _sym(name, file="f.py", line=1):
    return {"name": name, "file": file, "line_start": line}


def test_linear_chain_callers():
    # A -> B -> C (calls). callers of C = B, A
    rels = [_rel("A", "B"), _rel("B", "C")]
    result = compute_transitive_impact("C", rels, [], direction="callers")
    symbols = {r["symbol"] for r in result["results"]}
    assert "B" in symbols
    assert "A" in symbols
    assert result["total"] == 2


def test_linear_chain_callees():
    rels = [_rel("A", "B"), _rel("B", "C")]
    result = compute_transitive_impact("A", rels, [], direction="callees")
    symbols = {r["symbol"] for r in result["results"]}
    assert "B" in symbols
    assert "C" in symbols


def test_diamond_no_duplicates():
    # A->B, A->C, B->D, C->D
    rels = [_rel("A", "B"), _rel("A", "C"), _rel("B", "D"), _rel("C", "D")]
    result = compute_transitive_impact("D", rels, [], direction="callers")
    names = [r["symbol"] for r in result["results"]]
    assert len(names) == len(set(names)), "No duplicates"
    assert set(names) == {"A", "B", "C"}


def test_cycle_no_infinite_loop():
    rels = [_rel("A", "B"), _rel("B", "C"), _rel("C", "A")]
    result = compute_transitive_impact("A", rels, [], direction="callers", depth=10)
    # Should complete without hanging
    assert result["total"] < 100


def test_max_depth_cutoff():
    # chain A->B->C->D->E->F, depth=2 from B (callees)
    rels = [_rel("A", "B"), _rel("B", "C"), _rel("C", "D"), _rel("D", "E"), _rel("E", "F")]
    result = compute_transitive_impact("B", rels, [], direction="callees", depth=2)
    names = {r["symbol"] for r in result["results"]}
    assert "C" in names
    assert "D" in names
    assert "E" not in names


def test_direction_both_union():
    rels = [_rel("X", "target"), _rel("target", "Y")]
    result = compute_transitive_impact("target", rels, [], direction="both")
    names = {r["symbol"] for r in result["results"]}
    assert "X" in names
    assert "Y" in names


def test_empty_graph():
    result = compute_transitive_impact("foo", [], [], direction="callers")
    assert result["total"] == 0
    assert result["results"] == []


def test_target_not_in_graph():
    rels = [_rel("A", "B")]
    result = compute_transitive_impact("Z", rels, [], direction="callers")
    assert result["total"] == 0


def test_file_and_line_populated():
    syms = [_sym("caller", file="src.py", line=10)]
    rels = [_rel("caller", "target")]
    result = compute_transitive_impact("target", rels, syms, direction="callers")
    r = result["results"][0]
    assert r["file"] == "src.py"
    assert r["line"] == 10
