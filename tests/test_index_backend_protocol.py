"""Tests for Issue #79: IndexBackend protocol and dataclasses."""
from __future__ import annotations

import pytest

from close_wiki.backends import Document, IndexBackend, IndexStats, SearchResult
from close_wiki.backends.protocol import IndexBackend


# ---------------------------------------------------------------------------
# Test dataclasses
# ---------------------------------------------------------------------------


def test_document_defaults():
    doc = Document(id="d1", text="hello")
    assert doc.id == "d1"
    assert doc.text == "hello"
    assert doc.metadata == {}


def test_search_result_defaults():
    r = SearchResult(id="r1", text="found", score=0.9)
    assert r.source_ref is None
    assert r.metadata == {}


def test_index_stats_defaults():
    s = IndexStats(total_documents=10, last_updated_at=None, backend_name="test")
    assert s.extra == {}


# ---------------------------------------------------------------------------
# Test Protocol is runtime_checkable
# ---------------------------------------------------------------------------


class _MinimalBackend:
    """Minimal stub that satisfies the IndexBackend protocol."""

    @property
    def name(self) -> str:
        return "stub"

    def setup(self) -> None: ...
    def teardown(self) -> None: ...
    def destroy(self) -> None: ...
    def upsert(self, documents): ...
    def delete(self, ids): ...
    def update_all(self, source_path=None): ...
    def search(self, query, top_k=5, filters=None): return []
    def get(self, doc_id): return None
    def stats(self): return IndexStats(0, None, "stub")
    def health_check(self): return True


def test_protocol_isinstance_check():
    """A conforming class must pass isinstance(obj, IndexBackend)."""
    backend = _MinimalBackend()
    assert isinstance(backend, IndexBackend)


def test_non_conforming_class_fails_isinstance():
    """An object with missing methods must NOT pass isinstance check."""
    class _Incomplete:
        @property
        def name(self): return "x"

    assert not isinstance(_Incomplete(), IndexBackend)


# ---------------------------------------------------------------------------
# Test Document equality + field mutation
# ---------------------------------------------------------------------------


def test_document_metadata_not_shared():
    """Default metadata dicts must not be shared across instances."""
    d1 = Document(id="a", text="x")
    d2 = Document(id="b", text="y")
    d1.metadata["key"] = "val"
    assert "key" not in d2.metadata


def test_search_result_with_source_ref():
    r = SearchResult(id="x", text="snippet", score=0.85, source_ref="auth.py L12")
    assert r.source_ref == "auth.py L12"
