"""Tests for PythonExtractor."""
from __future__ import annotations

from pathlib import Path

import pytest

from rekipedia.extractors.python_extractor import PythonExtractor

FIXTURES = Path(__file__).parent / "fixtures" / "mini-py-repo"


@pytest.fixture()
def extractor():
    return PythonExtractor()


def test_can_handle_py(extractor):
    assert extractor.can_handle(Path("foo.py"))


def test_can_handle_pyw(extractor):
    assert extractor.can_handle(Path("foo.pyw"))


def test_cannot_handle_ts(extractor):
    assert not extractor.can_handle(Path("foo.ts"))


def test_extracts_function(extractor):
    result = extractor.extract(FIXTURES / "main.py", FIXTURES)
    names = [s.name for s in result.symbols]
    assert "greet" in names


def test_function_has_docstring(extractor):
    result = extractor.extract(FIXTURES / "main.py", FIXTURES)
    greet = next(s for s in result.symbols if s.name == "greet")
    assert greet.docstring is not None
    assert "greeting" in greet.docstring.lower()


def test_detects_entry_point(extractor):
    result = extractor.extract(FIXTURES / "main.py", FIXTURES)
    assert "main.py" in result.entry_points


def test_extracts_multiple_functions(extractor):
    result = extractor.extract(FIXTURES / "utils.py", FIXTURES)
    names = {s.name for s in result.symbols}
    assert {"add", "subtract"} <= names


def test_relative_path_in_shard_id(extractor):
    result = extractor.extract(FIXTURES / "utils.py", FIXTURES)
    assert result.shard_id == "utils.py"


def test_files_seen_contains_path(extractor):
    result = extractor.extract(FIXTURES / "main.py", FIXTURES)
    assert "main.py" in result.files_seen


def test_syntax_error_returns_risk(extractor, tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text("def foo(\n  # unclosed paren")
    result = extractor.extract(bad, tmp_path)
    assert any("SyntaxError" in r for r in result.risks)
