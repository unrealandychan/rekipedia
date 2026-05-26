"""Tests for rekipedia.analysis.refactor_writer."""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

from rekipedia.analysis.refactor_writer import (
    _build_markdown,
    detect_issues,
    write_refactor_outputs,
)
from rekipedia.models.contracts import AnalysisResult, Relationship, Symbol

# ── Helpers ────────────────────────────────────────────────────────────────


def _rel(from_: str, to: str, kind: str = "calls") -> Relationship:
    return Relationship(from_=from_, to=to, kind=kind, file=None)  # type: ignore[arg-type]


def _sym(name: str, kind: str = "function", file: str = "src/app.py") -> Symbol:
    return Symbol(name=name, kind=kind, file=file)  # type: ignore[arg-type]


def _analysis(**kwargs) -> AnalysisResult:
    defaults: dict = {
        "shard_id": "test",
        "files_seen": ["src/app.py"],
        "entry_points": [],
        "symbols": [],
        "relationships": [],
    }
    defaults.update(kwargs)
    return AnalysisResult(**defaults)


# ── detect_issues: god class ───────────────────────────────────────────────


def test_detect_god_class_above_threshold() -> None:
    # Create a class symbol with degree >= 10
    sym = Symbol(name="BigClass", kind="class", file="src/big.py")
    # 6 callers + 5 callees = 11 degrees
    rels = (
        [_rel(f"caller{i}", "BigClass") for i in range(6)]
        + [_rel("BigClass", f"dep{i}") for i in range(5)]
    )
    combined = _analysis(symbols=[sym], relationships=rels)
    issues = detect_issues(combined)

    assert len(issues) == 1
    issue = issues[0]
    assert issue["kind"] == "god_class"
    assert issue["symbol"] == "BigClass"
    assert issue["severity"] == "high"
    assert issue["metrics"]["fan_in"] == 6
    assert issue["metrics"]["fan_out"] == 5


def test_detect_god_class_below_threshold() -> None:
    sym = Symbol(name="SmallClass", kind="class", file="src/small.py")
    # Only 3 degrees — below threshold
    rels = [_rel("A", "SmallClass"), _rel("SmallClass", "B"), _rel("SmallClass", "C")]
    combined = _analysis(symbols=[sym], relationships=rels)
    issues = detect_issues(combined)
    god_class_issues = [i for i in issues if i["kind"] == "god_class"]
    assert god_class_issues == []


def test_detect_god_class_callers_capped() -> None:
    """Callers list in the issue is capped at 20."""
    sym = Symbol(name="HugClass", kind="class", file="src/huge.py")
    rels = [_rel(f"c{i}", "HugClass") for i in range(30)]
    combined = _analysis(symbols=[sym], relationships=rels)
    issues = detect_issues(combined)
    god_issues = [i for i in issues if i["kind"] == "god_class"]
    assert len(god_issues) == 1
    assert len(god_issues[0]["callers"]) <= 20


# ── detect_issues: dead code ───────────────────────────────────────────────


def test_detect_dead_code_zero_callers() -> None:
    sym = _sym("orphaned_func")
    combined = _analysis(symbols=[sym], relationships=[])
    issues = detect_issues(combined)
    dead = [i for i in issues if i["kind"] == "dead_code"]
    assert any(i["symbol"] == "orphaned_func" for i in dead)


def test_detect_dead_code_with_callers_excluded() -> None:
    sym = _sym("live_func")
    rels = [_rel("some_caller", "live_func")]
    combined = _analysis(symbols=[sym], relationships=rels)
    issues = detect_issues(combined)
    dead = [i for i in issues if i["kind"] == "dead_code"]
    assert not any(i["symbol"] == "live_func" for i in dead)


def test_detect_dead_code_skips_entry_points() -> None:
    sym = _sym("main_func")
    combined = _analysis(symbols=[sym], entry_points=["main_func"])
    issues = detect_issues(combined)
    dead = [i for i in issues if i["symbol"] == "main_func"]
    assert dead == []


def test_detect_dead_code_skips_dunder() -> None:
    sym = _sym("__init__", kind="function")
    combined = _analysis(symbols=[sym])
    issues = detect_issues(combined)
    dead = [i for i in issues if i["symbol"] == "__init__"]
    assert dead == []


def test_detect_dead_code_skips_test_helpers() -> None:
    sym = _sym("test_something")
    combined = _analysis(symbols=[sym])
    issues = detect_issues(combined)
    dead = [i for i in issues if i["symbol"] == "test_something"]
    assert dead == []


def test_detect_dead_code_skips_test_file_symbols() -> None:
    sym = Symbol(name="helper", kind="function", file="tests/test_util.py")
    combined = _analysis(symbols=[sym])
    issues = detect_issues(combined)
    dead = [i for i in issues if i["symbol"] == "helper"]
    assert dead == []


# ── detect_issues: severity ordering ──────────────────────────────────────


def test_issues_sorted_high_before_low() -> None:
    god_sym = Symbol(name="GodClass", kind="class", file="src/god.py")
    dead_sym = _sym("dead_fn")
    rels = [_rel(f"x{i}", "GodClass") for i in range(6)] + [
        _rel("GodClass", f"d{i}") for i in range(5)
    ]
    combined = _analysis(symbols=[god_sym, dead_sym], relationships=rels)
    issues = detect_issues(combined)
    sev_order = [i["severity"] for i in issues]
    # All "high" before all "low"
    seen_low = False
    for s in sev_order:
        if s == "low":
            seen_low = True
        if seen_low and s == "high":
            pytest.fail("high severity appeared after low severity")


# ── _build_markdown ────────────────────────────────────────────────────────


def test_build_markdown_header() -> None:
    md = _build_markdown([], file_count=42)
    assert "# Refactoring Guide" in md
    assert "0 issues" in md
    assert "42 files" in md


def test_build_markdown_high_section() -> None:
    issue = {
        "kind": "god_class",
        "symbol": "BigClass",
        "file": "src/big.py",
        "severity": "high",
        "metrics": {"lines": 300, "fan_in": 10, "fan_out": 5},
        "suggestion": "Split BigClass",
        "callers": ["a", "b"],
    }
    md = _build_markdown([issue], file_count=5)
    assert "🔴" in md
    assert "High Priority" in md
    assert "BigClass" in md
    assert "300 lines" in md


def test_build_markdown_low_section() -> None:
    issue = {
        "kind": "dead_code",
        "symbol": "old_fn",
        "file": "src/utils.py",
        "severity": "low",
        "metrics": {"fan_in": 0, "fan_out": 0},
        "suggestion": "Remove `old_fn` — 0 callers detected",
        "callers": [],
    }
    md = _build_markdown([issue], file_count=3)
    assert "🟢" in md
    assert "Quick Wins" in md
    assert "old_fn" in md


def test_build_markdown_no_empty_sections() -> None:
    """Sections with no issues should not appear."""
    issue = {
        "kind": "dead_code",
        "symbol": "stale_fn",
        "file": "src/old.py",
        "severity": "low",
        "metrics": {"fan_in": 0, "fan_out": 0},
        "suggestion": "Remove `stale_fn` — 0 callers detected",
        "callers": [],
    }
    md = _build_markdown([issue], file_count=1)
    assert "🔴" not in md  # no high-priority issues
    assert "🟡" not in md  # no medium-priority issues


# ── write_refactor_outputs ─────────────────────────────────────────────────


def test_write_refactor_outputs_creates_files(tmp_path: Path) -> None:
    combined = _analysis(files_seen=["a.py", "b.py"])
    md_path, json_path = write_refactor_outputs(combined, tmp_path)

    assert md_path.exists()
    assert json_path.exists()
    assert md_path.name == "REFACTOR.md"
    assert json_path.name == "refactor_report.json"


def test_write_refactor_outputs_json_structure(tmp_path: Path) -> None:
    sym = Symbol(name="GodClass", kind="class", file="src/x.py")
    rels = [_rel(f"c{i}", "GodClass") for i in range(6)] + [
        _rel("GodClass", f"d{i}") for i in range(5)
    ]
    combined = _analysis(symbols=[sym], relationships=rels, files_seen=["src/x.py"])
    _, json_path = write_refactor_outputs(combined, tmp_path)

    data = json.loads(json_path.read_text())
    assert "generated_at" in data
    assert "rekipedia_version" in data
    assert "summary" in data
    assert "issues" in data
    assert isinstance(data["summary"]["high"], int)
    assert isinstance(data["issues"], list)


def test_write_refactor_outputs_summary_counts(tmp_path: Path) -> None:
    sym = Symbol(name="GodClass", kind="class", file="src/x.py")
    dead_sym = _sym("dead_fn")
    rels = [_rel(f"c{i}", "GodClass") for i in range(6)] + [
        _rel("GodClass", f"d{i}") for i in range(5)
    ]
    combined = _analysis(
        symbols=[sym, dead_sym], relationships=rels, files_seen=["src/x.py"]
    )
    _, json_path = write_refactor_outputs(combined, tmp_path)

    data = json.loads(json_path.read_text())
    assert data["summary"]["high"] >= 1
    assert data["summary"]["low"] >= 1


def test_write_refactor_outputs_stdout(tmp_path: Path) -> None:
    combined = _analysis(files_seen=["a.py"])
    captured = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = captured
    try:
        write_refactor_outputs(combined, tmp_path, stdout=True)
    finally:
        sys.stdout = old_stdout
    output = captured.getvalue()
    assert "# Refactoring Guide" in output


def test_write_refactor_outputs_no_stdout_by_default(tmp_path: Path) -> None:
    combined = _analysis(files_seen=["a.py"])
    captured = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = captured
    try:
        write_refactor_outputs(combined, tmp_path, stdout=False)
    finally:
        sys.stdout = old_stdout
    assert captured.getvalue() == ""


def test_write_refactor_outputs_creates_output_dir(tmp_path: Path) -> None:
    nested = tmp_path / "deep" / "output"
    combined = _analysis()
    write_refactor_outputs(combined, nested)
    assert nested.exists()


def test_write_refactor_outputs_empty_result(tmp_path: Path) -> None:
    combined = _analysis()
    md_path, json_path = write_refactor_outputs(combined, tmp_path)

    md = md_path.read_text()
    assert "0 issues" in md

    data = json.loads(json_path.read_text())
    assert data["issues"] == []
    assert data["summary"] == {"high": 0, "medium": 0, "low": 0}
