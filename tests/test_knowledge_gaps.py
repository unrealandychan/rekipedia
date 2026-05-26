"""Tests for _build_knowledge_gaps in graph_analysis."""
from rekipedia.analysis.graph_analysis import _build_knowledge_gaps
from rekipedia.models.contracts import AnalysisResult, Relationship, Symbol


def make_result(symbols, relationships):
    return AnalysisResult(
        shard_id="test",
        files_seen=[],
        entry_points=[],
        symbols=symbols,
        relationships=relationships,
    )


def make_sym(name, kind="function", file="src/module.py"):
    return Symbol(name=name, kind=kind, file=file)


def make_rel(from_, to, kind="calls", file=None):
    data = {"from": from_, "to": to, "kind": kind}
    if file:
        data["file"] = file
    return Relationship(**data)


def test_uncovered_function_appears_in_gaps():
    """Function called 5 times with no test coverage should appear."""
    sym = make_sym("my_func")
    rels = [make_rel(f"caller_{i}", "my_func") for i in range(5)]
    result = make_result([sym], rels)
    gaps = _build_knowledge_gaps(result)
    names = [g["name"] for g in gaps]
    assert "my_func" in names
    gap = next(g for g in gaps if g["name"] == "my_func")
    assert gap["call_count"] == 5
    assert gap["kind"] == "function"


def test_covered_function_not_in_gaps():
    """Function called 5 times WITH test coverage should NOT appear."""
    sym = make_sym("my_func")
    # 5 regular callers + 1 test caller
    rels = [make_rel(f"caller_{i}", "my_func") for i in range(5)]
    rels.append(make_rel("test_something", "my_func"))
    result = make_result([sym], rels)
    gaps = _build_knowledge_gaps(result)
    names = [g["name"] for g in gaps]
    assert "my_func" not in names


def test_low_call_count_not_in_gaps():
    """Function called only once should NOT appear in gaps."""
    sym = make_sym("rare_func")
    rels = [make_rel("some_caller", "rare_func")]
    result = make_result([sym], rels)
    gaps = _build_knowledge_gaps(result)
    names = [g["name"] for g in gaps]
    assert "rare_func" not in names


def test_test_file_coverage_detection():
    """Caller from a file with /test in path should mark function as covered."""
    sym = make_sym("util_func")
    rels = [make_rel(f"caller_{i}", "util_func") for i in range(4)]
    rels.append(make_rel("some_caller", "util_func", file="tests/test_utils.py"))
    result = make_result([sym], rels)
    gaps = _build_knowledge_gaps(result)
    names = [g["name"] for g in gaps]
    assert "util_func" not in names


def test_sorted_by_call_count_desc():
    """Results should be sorted by call_count descending."""
    syms = [make_sym("func_a"), make_sym("func_b"), make_sym("func_c")]
    rels = (
        [make_rel(f"c{i}", "func_a") for i in range(3)]
        + [make_rel(f"d{i}", "func_b") for i in range(7)]
        + [make_rel(f"e{i}", "func_c") for i in range(5)]
    )
    result = make_result(syms, rels)
    gaps = _build_knowledge_gaps(result)
    counts = [g["call_count"] for g in gaps]
    assert counts == sorted(counts, reverse=True)
