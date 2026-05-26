"""Tests for _build_hub_nodes in graph_analysis."""
from rekipedia.analysis.graph_analysis import _build_hub_nodes


def test_high_degree_node_appears():
    rels = [
        {"from_": "hub", "to": "a"},
        {"from_": "hub", "to": "b"},
        {"from_": "hub", "to": "c"},
        {"from_": "x", "to": "hub"},
        {"from_": "y", "to": "hub"},
    ]
    result = _build_hub_nodes(rels)
    names = [r["name"] for r in result]
    assert "hub" in names
    assert result[0]["name"] == "hub"


def test_is_bridge_true():
    rels = [
        {"from_": "bridge", "to": "a"},
        {"from_": "bridge", "to": "b"},
        {"from_": "x", "to": "bridge"},
        {"from_": "y", "to": "bridge"},
    ]
    result = _build_hub_nodes(rels)
    bridge_node = next(r for r in result if r["name"] == "bridge")
    assert bridge_node["is_bridge"] is True


def test_is_bridge_false_for_leaf():
    rels = [
        {"from_": "leaf", "to": "a"},
        {"from_": "leaf", "to": "b"},
        {"from_": "leaf", "to": "c"},
    ]
    result = _build_hub_nodes(rels)
    leaf_node = next(r for r in result if r["name"] == "leaf")
    assert leaf_node["is_bridge"] is False


def test_sorted_by_score_descending():
    rels = [
        {"from_": "a", "to": "b"},
        {"from_": "a", "to": "c"},
        {"from_": "b", "to": "c"},
        {"from_": "d", "to": "a"},
        {"from_": "e", "to": "a"},
        {"from_": "f", "to": "a"},
    ]
    result = _build_hub_nodes(rels)
    scores = [r["score"] for r in result]
    assert scores == sorted(scores, reverse=True)


def test_top_n_limits_results():
    rels = [{"from_": f"n{i}", "to": f"n{i+1}"} for i in range(50)]
    result = _build_hub_nodes(rels, top_n=5)
    assert len(result) <= 5


def test_symbol_enrichment():
    rels = [{"from_": "foo", "to": "bar"}, {"from_": "baz", "to": "foo"}]
    symbols = [{"name": "foo", "file": "foo.py", "kind": "function"}]
    result = _build_hub_nodes(rels, symbols=symbols)
    foo_node = next(r for r in result if r["name"] == "foo")
    assert foo_node["file"] == "foo.py"
    assert foo_node["kind"] == "function"
