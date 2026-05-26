"""Tests for symbol resolution pass."""
from rekipedia.analysis.resolution import resolve_relationships
from rekipedia.models.contracts import AnalysisResult, Relationship, Symbol


def _make_result(symbols, relationships):
    return AnalysisResult(
        shard_id="test",
        files_seen=[],
        entry_points=[],
        symbols=symbols,
        relationships=relationships,
    )


def _sym(name, file, line):
    return Symbol(name=name, kind="function", file=file, line_start=line, line_end=line)


def _rel(from_, to, file=None):
    return Relationship(**{"from": from_, "to": to, "kind": "calls", "file": file})


def test_same_file_resolution():
    syms = [_sym("foo", "a.py", 10), _sym("foo", "b.py", 20)]
    rels = [_rel("bar", "foo", file="a.py")]
    result = resolve_relationships(_make_result(syms, rels))
    r = result.relationships[0]
    assert r.resolved_to_file == "a.py"
    assert r.resolved_to_line == 10


def test_cross_file_unique_resolution():
    syms = [_sym("foo", "a.py", 5)]
    rels = [_rel("bar", "foo", file="b.py")]
    result = resolve_relationships(_make_result(syms, rels))
    r = result.relationships[0]
    assert r.resolved_to_file == "a.py"
    assert r.resolved_to_line == 5


def test_ambiguous_no_same_file():
    syms = [_sym("foo", "a.py", 1), _sym("foo", "b.py", 2)]
    rels = [_rel("bar", "foo", file="c.py")]
    result = resolve_relationships(_make_result(syms, rels))
    r = result.relationships[0]
    assert r.resolved_to_file is None
    assert r.resolved_to_line is None


def test_unresolvable_name():
    syms = [_sym("other", "a.py", 1)]
    rels = [_rel("bar", "unknown")]
    result = resolve_relationships(_make_result(syms, rels))
    r = result.relationships[0]
    assert r.resolved_to_file is None


def test_resolved_to_line_correct():
    syms = [_sym("myfunc", "utils.py", 42)]
    rels = [_rel("caller", "myfunc")]
    result = resolve_relationships(_make_result(syms, rels))
    assert result.relationships[0].resolved_to_line == 42
