"""Tests for PythonExtractor fixes: module symbols, import relationships, calls."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from rekipedia.extractors.python_extractor import PythonExtractor


@pytest.fixture
def extractor():
    return PythonExtractor()


def _extract(extractor, source: str, rel_path: str = "src/mypkg/mod.py", tmp_path=None):
    """Write source to a temp file and extract."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        file_path = td / rel_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(source)
        return extractor.extract(file_path, td)


def test_module_symbol_emitted(extractor):
    source = "x = 1\n"
    result = _extract(extractor, source, "src/mypkg/mod.py")
    module_syms = [s for s in result.symbols if s.kind == "module"]
    assert len(module_syms) == 1
    assert module_syms[0].name == "mypkg.mod"


def test_import_relationship_uses_module_name(extractor):
    source = textwrap.dedent("""\
        import os
        from rekipedia.models.contracts import Symbol
    """)
    result = _extract(extractor, source, "src/mypkg/mod.py")
    import_rels = [r for r in result.relationships if r.kind == "imports"]
    froms = {r.from_ for r in import_rels}
    tos = {r.to for r in import_rels}
    assert "mypkg.mod" in froms
    assert "os" in tos
    assert "rekipedia.models.contracts" in tos
    # must NOT use file path
    assert not any("src/" in f for f in froms)


def test_calls_relationship_extracted(extractor):
    source = textwrap.dedent("""\
        def greet():
            print("hello")
            len([1, 2, 3])
    """)
    result = _extract(extractor, source, "src/mypkg/mod.py")
    calls = [r for r in result.relationships if r.kind == "calls"]
    callees = {r.to for r in calls}
    assert "print" in callees
    assert "len" in callees
    callers = {r.from_ for r in calls}
    assert "greet" in callers


def test_calls_in_method(extractor):
    source = textwrap.dedent("""\
        class Foo:
            def bar(self):
                self.baz()
                helper()
    """)
    result = _extract(extractor, source, "src/mypkg/mod.py")
    calls = [r for r in result.relationships if r.kind == "calls"]
    callers = {r.from_ for r in calls}
    callees = {r.to for r in calls}
    assert "Foo.bar" in callers
    assert "baz" in callees or "helper" in callees


def test_inherits_unaffected(extractor):
    source = textwrap.dedent("""\
        class Base:
            pass

        class Child(Base):
            pass
    """)
    result = _extract(extractor, source, "src/mypkg/mod.py")
    inherits = [r for r in result.relationships if r.kind == "inherits"]
    assert len(inherits) == 1
    assert inherits[0].from_ == "Child"
    assert inherits[0].to == "Base"
