"""Tests for TypeScriptExtractor."""
from __future__ import annotations

from pathlib import Path

import pytest

from rekipedia.extractors.typescript_extractor import TypeScriptExtractor

FIXTURES = Path(__file__).parent / "fixtures" / "mini-ts-repo"


@pytest.fixture()
def extractor():
    return TypeScriptExtractor()


def test_can_handle_ts(extractor):
    assert extractor.can_handle(Path("foo.ts"))


def test_can_handle_tsx(extractor):
    assert extractor.can_handle(Path("foo.tsx"))


def test_can_handle_js(extractor):
    assert extractor.can_handle(Path("foo.js"))


def test_cannot_handle_py(extractor):
    assert not extractor.can_handle(Path("foo.py"))


def test_extracts_exported_function(extractor):
    result = extractor.extract(FIXTURES / "src" / "greet.ts", FIXTURES)
    names = [s.name for s in result.symbols]
    assert "greet" in names


def test_function_kind(extractor):
    result = extractor.extract(FIXTURES / "src" / "greet.ts", FIXTURES)
    greet = next(s for s in result.symbols if s.name == "greet")
    assert greet.kind == "function"


def test_import_relationship(extractor):
    result = extractor.extract(FIXTURES / "src" / "index.ts", FIXTURES)
    import_tos = [r.to for r in result.relationships if r.kind == "import"]
    assert any("greet" in t for t in import_tos)


def test_index_is_entry_point(extractor):
    result = extractor.extract(FIXTURES / "src" / "index.ts", FIXTURES)
    assert len(result.entry_points) > 0


def test_shard_id_is_relative(extractor):
    result = extractor.extract(FIXTURES / "src" / "greet.ts", FIXTURES)
    assert result.shard_id == "src/greet.ts"


def test_class_extraction(extractor, tmp_path):
    ts = tmp_path / "MyClass.ts"
    ts.write_text("export class Dog extends Animal { bark() {} }")
    result = extractor.extract(ts, tmp_path)
    names = [s.name for s in result.symbols]
    assert "Dog" in names


def test_inheritance_relationship(extractor, tmp_path):
    ts = tmp_path / "MyClass.ts"
    ts.write_text("export class Dog extends Animal { bark() {} }")
    result = extractor.extract(ts, tmp_path)
    rels = [r for r in result.relationships if r.kind == "inherits"]
    assert any(r.to == "Animal" for r in rels)
