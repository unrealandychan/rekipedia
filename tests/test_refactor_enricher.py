"""Tests for refactor_enricher — static analysis and LLM enrichment."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from rekipedia.analysis.refactor_enricher import (
    RefactorEnricher,
    RefactorIssue,
    _attach_callers,
    _attach_notes,
    _build_prompt,
    _parse_enrichment,
    detect_issues,
)
from rekipedia.models.contracts import AnalysisResult, Relationship, Symbol

# ── Fixtures ──────────────────────────────────────────────────────────────────


def _rel(from_: str, to: str, kind: str = "calls") -> Relationship:
    return Relationship(**{"from": from_, "to": to, "kind": kind, "file": None})


def _sym(name: str, kind: str = "function", file: str = "src/main.py") -> Symbol:
    return Symbol(name=name, kind=kind, file=file, line_start=1)


def _god_class_result() -> AnalysisResult:
    """AnalysisResult where 'GodClass' has degree > 10."""
    syms = [_sym("GodClass", "class")] + [_sym(f"Caller{i}") for i in range(12)]
    rels = [_rel(f"Caller{i}", "GodClass") for i in range(12)]
    return AnalysisResult(
        shard_id="test",
        files_seen=["src/main.py"],
        entry_points=[],
        symbols=syms,
        relationships=rels,
    )


def _dead_code_result() -> AnalysisResult:
    """AnalysisResult where 'OrphanFunc' has no callers (but the file has >=3 symbols)."""
    syms = [
        _sym("OrphanFunc", "function", "src/utils.py"),
        _sym("UsedFunc", "function", "src/utils.py"),
        _sym("AnotherFunc", "function", "src/utils.py"),
    ]
    rels = [_rel("Main", "UsedFunc")]
    return AnalysisResult(
        shard_id="test",
        files_seen=["src/utils.py"],
        entry_points=[],
        symbols=syms,
        relationships=rels,
    )


def _large_file_result() -> AnalysisResult:
    """AnalysisResult where one file has many symbols."""
    syms = [_sym(f"Sym{i}", "function", "src/big.py") for i in range(35)]
    return AnalysisResult(
        shard_id="test",
        files_seen=["src/big.py"],
        entry_points=[],
        symbols=syms,
        relationships=[],
    )


def _high_coupling_result() -> AnalysisResult:
    """AnalysisResult where 'HeavyUser' has >= 10 outbound dependencies."""
    rels = [_rel("HeavyUser", f"Dep{i}", "imports") for i in range(11)]
    syms = [_sym("HeavyUser"), *[_sym(f"Dep{i}") for i in range(11)]]
    return AnalysisResult(
        shard_id="test",
        files_seen=["src/main.py"],
        entry_points=[],
        symbols=syms,
        relationships=rels,
    )


# ── detect_issues ─────────────────────────────────────────────────────────────


def test_detect_god_class():
    result = _god_class_result()
    issues = detect_issues(result)
    kinds = {i.kind for i in issues}
    assert "god_class" in kinds
    god = next(i for i in issues if i.kind == "god_class" and i.symbol == "GodClass")
    assert god.metrics["degree"] >= 10


def test_detect_dead_code():
    result = _dead_code_result()
    issues = detect_issues(result)
    kinds = {i.kind for i in issues}
    assert "dead_code" in kinds
    dead = [i for i in issues if i.kind == "dead_code"]
    symbols = {i.symbol for i in dead}
    assert "OrphanFunc" in symbols
    # UsedFunc should NOT be flagged — it has a caller
    assert "UsedFunc" not in symbols


def test_detect_large_file():
    result = _large_file_result()
    issues = detect_issues(result)
    kinds = {i.kind for i in issues}
    assert "large_file" in kinds
    lf = next(i for i in issues if i.kind == "large_file")
    assert lf.metrics["symbol_count"] >= 30


def test_detect_high_coupling():
    result = _high_coupling_result()
    issues = detect_issues(result)
    kinds = {i.kind for i in issues}
    assert "high_coupling" in kinds


def test_detect_circular_dep():
    # A→B→C→A forms a cycle
    syms = [_sym("A"), _sym("B"), _sym("C")]
    rels = [
        _rel("A", "B", "imports"),
        _rel("B", "C", "imports"),
        _rel("C", "A", "imports"),
    ]
    result = AnalysisResult(
        shard_id="test",
        files_seen=[],
        entry_points=[],
        symbols=syms,
        relationships=rels,
    )
    issues = detect_issues(result)
    kinds = {i.kind for i in issues}
    assert "circular_dep" in kinds


def test_detect_no_issues_empty():
    result = AnalysisResult(shard_id="test", files_seen=[], entry_points=[])
    issues = detect_issues(result)
    assert issues == []


def test_dead_code_skips_test_functions():
    """Functions in test files or named test_* should not be flagged as dead code."""
    syms = [
        _sym("test_something", "function", "tests/test_main.py"),
        _sym("OtherFunc", "function", "tests/test_main.py"),
        _sym("ThirdFunc", "function", "tests/test_main.py"),
    ]
    result = AnalysisResult(
        shard_id="test", files_seen=[], entry_points=[], symbols=syms, relationships=[]
    )
    issues = detect_issues(result)
    dead_symbols = {i.symbol for i in issues if i.kind == "dead_code"}
    assert "test_something" not in dead_symbols


# ── _attach_callers ────────────────────────────────────────────────────────────


def test_attach_callers():
    result = _god_class_result()
    issues = detect_issues(result)
    _attach_callers(issues, result, top_n=5)
    god = next(i for i in issues if i.kind == "god_class" and i.symbol == "GodClass")
    assert len(god.callers) <= 5
    assert all(c.startswith("Caller") for c in god.callers)


def test_attach_callers_no_callers():
    result = AnalysisResult(shard_id="test", files_seen=[], entry_points=[])
    issue = RefactorIssue(kind="god_class", symbol="Unused", file="f.py", metrics={})
    _attach_callers([issue], result)
    assert issue.callers == []


# ── _attach_notes ─────────────────────────────────────────────────────────────


def test_attach_notes_matches_file():
    issue = RefactorIssue(kind="god_class", symbol="X", file="src/main.py", metrics={})
    notes = [
        {"file": "src/main.py", "tag": "HACK", "content": "This is a hack"},
        {"file": "src/other.py", "tag": "NOTE", "content": "Different file"},
    ]
    _attach_notes([issue], notes)
    assert len(issue.notes) == 1
    assert "HACK" in issue.notes[0]


def test_attach_notes_no_match():
    issue = RefactorIssue(kind="god_class", symbol="X", file="src/main.py", metrics={})
    notes = [{"file": "src/totally_different.py", "tag": "NOTE", "content": "Nope"}]
    _attach_notes([issue], notes)
    assert issue.notes == []


# ── _build_prompt ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("kind", ["god_class", "circular_dep", "dead_code", "large_file", "high_coupling"])
def test_build_prompt_contains_symbol(kind: str):
    metrics: dict = {
        "degree": 15, "in_degree": 10, "out_degree": 5,
        "cycle_length": 3, "total_symbols": 40, "symbol_count": 40,
    }
    issue = RefactorIssue(kind=kind, symbol="MySymbol", file="src/x.py", metrics=metrics)
    prompt = _build_prompt(issue)
    assert "MySymbol" in prompt or "src/x.py" in prompt


# ── _parse_enrichment ─────────────────────────────────────────────────────────


def test_parse_enrichment_all_fields():
    raw = (
        "Problem: The class has too many responsibilities.\n"
        "Suggestion: Extract AuthService and BillingService.\n"
        "Start here: src/auth/ — lowest coupling.\n"
        "Risk: Medium — 23 callers need updating."
    )
    issue = RefactorIssue(kind="god_class", symbol="X", file="f.py", metrics={})
    _parse_enrichment(raw, issue)
    assert issue.problem == "The class has too many responsibilities."
    assert issue.suggestion == "Extract AuthService and BillingService."
    assert "src/auth/" in issue.start_here
    assert issue.risk.startswith("Medium")


def test_parse_enrichment_partial():
    raw = "Problem: Something is wrong."
    issue = RefactorIssue(kind="god_class", symbol="X", file="f.py", metrics={})
    _parse_enrichment(raw, issue)
    assert issue.problem == "Something is wrong."
    assert issue.suggestion == ""


# ── RefactorEnricher ──────────────────────────────────────────────────────────


def test_enricher_no_llm_returns_issues_unchanged():
    """When no caller is provided, enrich returns issues with empty explanation fields."""
    enricher = RefactorEnricher(caller=None)
    issues = detect_issues(_god_class_result())
    enriched = enricher.enrich(issues)
    assert enriched is issues
    for i in enriched:
        assert i.problem == ""
        assert i.suggestion == ""


def test_enricher_with_mock_llm():
    mock_caller = MagicMock()
    mock_caller.call.return_value = (
        "Problem: God class handles too many concerns.\n"
        "Suggestion: Extract to smaller services.\n"
        "Start here: src/core/\n"
        "Risk: High — many callers."
    )

    enricher = RefactorEnricher(caller=mock_caller)
    issues = [
        RefactorIssue(
            kind="god_class", symbol="BigClass", file="src/big.py",
            metrics={"degree": 15, "in_degree": 10, "out_degree": 5},
        )
    ]
    enriched = enricher.enrich(issues)
    assert len(enriched) == 1
    assert enriched[0].problem != ""
    assert "Extract" in enriched[0].suggestion
    assert mock_caller.call.call_count == 1


def test_enricher_llm_error_leaves_fields_empty():
    """LLM errors should not propagate — the issue is returned with empty fields."""
    mock_caller = MagicMock()
    mock_caller.call.side_effect = RuntimeError("LLM unavailable")

    enricher = RefactorEnricher(caller=mock_caller)
    issues = [
        RefactorIssue(
            kind="god_class", symbol="BigClass", file="src/big.py",
            metrics={"degree": 15, "in_degree": 10, "out_degree": 5},
        )
    ]
    enriched = enricher.enrich(issues)
    assert len(enriched) == 1
    assert enriched[0].problem == ""  # left empty on error


def test_enrich_all_end_to_end():
    """enrich_all detects issues, attaches callers + notes, and calls LLM."""
    mock_caller = MagicMock()
    mock_caller.call.return_value = (
        "Problem: Test.\nSuggestion: Split it.\nStart here: src/\nRisk: Low — minor."
    )

    enricher = RefactorEnricher(caller=mock_caller)
    result = _god_class_result()
    notes = [{"file": "src/main.py", "tag": "HACK", "content": "Watch out"}]
    enriched = enricher.enrich_all(result, notes=notes)

    assert len(enriched) >= 1
    # At least some issues should be enriched
    enriched_count = sum(1 for i in enriched if i.problem)
    assert enriched_count >= 1


def test_to_dict_serialisable():
    issue = RefactorIssue(
        kind="god_class",
        symbol="MyClass",
        file="src/main.py",
        metrics={"degree": 12},
        callers=["A", "B"],
        notes=["[HACK] watch out"],
        problem="Too large",
        suggestion="Split it",
        start_here="src/auth/",
        risk="Medium",
    )
    d = issue.to_dict()
    assert d["kind"] == "god_class"
    assert d["symbol"] == "MyClass"
    assert d["metrics"]["degree"] == 12
    assert d["callers"] == ["A", "B"]
    assert d["problem"] == "Too large"
