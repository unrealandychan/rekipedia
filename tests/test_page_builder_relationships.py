"""Tests for cross-module summary and relationship fields in _build_payload."""
from __future__ import annotations

from rekipedia.models.contracts import AnalysisResult, Relationship, Symbol
from rekipedia.synthesis.page_builder import _build_cross_module_summary, _build_payload


def _make_result(relationships=None, symbols=None, files_seen=None):
    """Helper to build a minimal AnalysisResult."""
    return AnalysisResult(
        shard_id="all",
        files_seen=files_seen or [],
        entry_points=[],
        symbols=symbols or [],
        relationships=relationships or [],
        build_commands=[],
        test_commands=[],
        risks=[],
    )


def _make_rel(from_, to, kind):
    """Create a Relationship object."""
    return Relationship(from_=from_, to=to, kind=kind)


def _make_sym(name, file=None, kind="function"):
    return Symbol(name=name, file=file or f"src/{name}.py", kind=kind)


# ── test _build_cross_module_summary ──────────────────────────────────────────

def test_cross_module_summary_computed():
    rels = [
        {"from_": "modA", "to": "modB", "kind": "imports"},
        {"from_": "modA", "to": "modC", "kind": "calls"},
    ]
    result = _build_cross_module_summary(rels, [], [])
    assert isinstance(result, dict)
    assert "modA" in result
    entry = result["modA"]
    assert set(entry.keys()) == {"imports", "imported_by", "calls", "called_by", "inherits", "inherited_by"}


def test_cross_module_summary_imports_correct():
    rels = [
        {"from_": "modA", "to": "modB", "kind": "imports"},
        {"from_": "modA", "to": "modB", "kind": "imports"},  # duplicate — should not double-add
        {"from_": "modC", "to": "modB", "kind": "import"},
    ]
    result = _build_cross_module_summary(rels, [], [])
    assert "modB" in result["modA"]["imports"]
    assert len(result["modA"]["imports"]) == 1  # deduplicated
    assert "modA" in result["modB"]["imported_by"]
    assert "modC" in result["modB"]["imported_by"]


def test_cross_module_summary_calls_correct():
    rels = [
        {"from_": "cli", "to": "orchestrator", "kind": "calls"},
        {"from_": "orchestrator", "to": "llm_client", "kind": "calls"},
    ]
    result = _build_cross_module_summary(rels, [], [])
    assert "orchestrator" in result["cli"]["calls"]
    assert "cli" in result["orchestrator"]["called_by"]
    assert "llm_client" in result["orchestrator"]["calls"]
    assert "orchestrator" in result["llm_client"]["called_by"]


def test_cross_module_summary_top100_limit():
    # Create 150 unique module pairs
    rels = [
        {"from_": f"modA_{i}", "to": f"modB_{i}", "kind": "imports"}
        for i in range(150)
    ]
    result = _build_cross_module_summary(rels, [], [])
    assert len(result) <= 100


def test_cross_module_summary_inherits():
    rels = [
        {"from_": "ChildClass", "to": "BaseClass", "kind": "inherits"},
    ]
    result = _build_cross_module_summary(rels, [], [])
    assert "BaseClass" in result["ChildClass"]["inherits"]
    assert "ChildClass" in result["BaseClass"]["inherited_by"]


# ── test _build_payload ────────────────────────────────────────────────────────

def test_relationship_stats_in_payload():
    rels = [
        _make_rel("modA", "modB", "imports"),
        _make_rel("modA", "modC", "calls"),
        _make_rel("modB", "modC", "imports"),
    ]
    combined = _make_result(relationships=rels)
    payload = _build_payload(combined)
    assert "relationship_stats" in payload
    stats = payload["relationship_stats"]
    assert "total" in stats
    assert "by_kind" in stats
    assert stats["total"] == 3
    assert stats["by_kind"].get("imports") == 2
    assert stats["by_kind"].get("calls") == 1


def test_cross_module_summary_in_payload():
    rels = [
        _make_rel("modA", "modB", "imports"),
    ]
    combined = _make_result(relationships=rels)
    payload = _build_payload(combined)
    assert "cross_module_summary" in payload
    cms = payload["cross_module_summary"]
    assert isinstance(cms, dict)


def test_internal_relationships_filtered():
    rels = [
        _make_rel("mymodule", "anothermodule", "imports"),
        _make_rel("os.path", "somemod", "imports"),  # stdlib-like — should be filtered
        _make_rel("mymodule", "thirdmod", "calls"),
    ]
    combined = _make_result(relationships=rels)
    payload = _build_payload(combined)
    assert "internal_relationships" in payload
    internal = payload["internal_relationships"]
    # os.path should be filtered out
    from_names = [r.get("from_") or r.get("from", "") for r in internal]
    assert "os.path" not in from_names
    assert "mymodule" in from_names


def test_relationships_limit_increased():
    """Payload relationships list should include up to 1500 items."""
    rels = [_make_rel(f"mod{i}", f"mod{i+1}", "imports") for i in range(2000)]
    combined = _make_result(relationships=rels)
    payload = _build_payload(combined)
    assert len(payload["relationships"]) == 1500


def test_internal_relationships_limit_800():
    """internal_relationships should be capped at 800."""
    rels = [_make_rel(f"modA{i}", f"modB{i}", "calls") for i in range(1000)]
    combined = _make_result(relationships=rels)
    payload = _build_payload(combined)
    assert len(payload["internal_relationships"]) == 800
