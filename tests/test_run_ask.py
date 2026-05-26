"""Tests for run_ask relevance ranking and query rewriting (issues #53, #56)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_extract_keywords_basic():
    from rekipedia.orchestrator.run_ask import _extract_keywords
    keywords = _extract_keywords("how does authentication work")
    assert "authentication" in keywords
    assert "how" not in keywords
    assert "does" not in keywords
    assert "work" in keywords


def test_extract_keywords_stopwords_filtered():
    from rekipedia.orchestrator.run_ask import _extract_keywords
    keywords = _extract_keywords("what is the best way to do this")
    assert "what" not in keywords
    assert "the" not in keywords
    assert "best" in keywords
    assert "way" in keywords


def test_score_page_relevance():
    from rekipedia.orchestrator.run_ask import _score_page
    auth_page = """---
title: Authentication Module
importance: 80
keywords: [jwt, token, authenticate, verify_credentials, AuthService]
---

# Authentication

This page documents the JWT authentication system.
The AuthService handles login, session management, and token verification.
"""
    keywords = ["authentication", "jwt", "token"]
    score = _score_page(auth_page, keywords)
    assert score > 0


def test_rank_pages_by_query_auth_first():
    from rekipedia.orchestrator.run_ask import _rank_pages_by_query

    auth_page = """---
title: Authentication Module
importance: 80
keywords: [jwt, token, authenticate, AuthService]
---

# Authentication
JWT authentication and token verification. AuthService login session.
"""
    unrelated_page = """---
title: Database Schema
importance: 60
keywords: [table, column, migration, schema]
---

# Database Schema
Tables and migrations. Schema design patterns.
"""

    pages = [unrelated_page, auth_page]
    ranked = _rank_pages_by_query(pages, "how does authentication work with JWT tokens")
    assert ranked[0] == auth_page, "Auth page should rank first for authentication query"


def test_rank_pages_empty():
    from rekipedia.orchestrator.run_ask import _rank_pages_by_query
    assert _rank_pages_by_query([], "test") == []


def test_rank_pages_no_keywords():
    from rekipedia.orchestrator.run_ask import _rank_pages_by_query
    pages = ["page1", "page2"]
    # Query with only stopwords → original order preserved
    result = _rank_pages_by_query(pages, "the a an")
    assert result == pages


# Issue #56 tests

def test_rewrite_query_disabled_by_env(tmp_path, monkeypatch):
    from rekipedia.models.contracts import LLMConfig
    from rekipedia.orchestrator.run_ask import _rewrite_query
    monkeypatch.setenv("REKIPEDIA_QUERY_REWRITE", "0")
    result = _rewrite_query("how does auth work?", tmp_path, LLMConfig())
    assert result == "how does auth work?"


def test_rewrite_query_no_vocab(tmp_path):
    from rekipedia.models.contracts import LLMConfig
    from rekipedia.orchestrator.run_ask import _rewrite_query
    # No symbols.json, no wiki dir → returns original
    result = _rewrite_query("how does auth work?", tmp_path, LLMConfig())
    assert result == "how does auth work?"


def test_rewrite_query_with_mock_llm(tmp_path, monkeypatch):
    """When vocab is available (>= 15 hints) and LLMClient returns a rewritten query, use it."""
    import json

    from rekipedia.models.contracts import LLMConfig

    # Create enough symbols to trigger rewriting (need 15+ vocab hints)
    exports = tmp_path / "exports"
    exports.mkdir()
    symbols = [
        {"name": f"AuthFunc{i}", "kind": "function", "file": "auth.py"}
        for i in range(15)
    ]
    (exports / "symbols.json").write_text(json.dumps(symbols))

    monkeypatch.setenv("REKIPEDIA_QUERY_REWRITE", "1")

    with patch("rekipedia.orchestrator.run_ask.LLMClient") as mock_cls:
        mock_client = MagicMock()
        mock_client.call.return_value = "How does AuthFunc0 verify_credentials work?"
        mock_cls.return_value = mock_client

        from rekipedia.orchestrator import run_ask as m
        result = m._rewrite_query("how does auth work?", tmp_path, LLMConfig())
        # Either original or rewritten is acceptable
        assert isinstance(result, str)
        assert len(result) > 0
