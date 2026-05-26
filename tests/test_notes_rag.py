"""Tests for notes RAG injection in run_ask."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from rekipedia.models.contracts import LLMConfig
from rekipedia.storage.sqlite_store import SqliteStore


def test_notes_injected_in_context(tmp_path: Path):
    """Notes should appear in assembled system context."""
    output_dir = tmp_path / ".rekipedia"
    output_dir.mkdir()
    db_path = output_dir / "store.db"
    with SqliteStore(db_path) as store:
        store.upsert_note(content="We use Redis for session caching", tags="arch,redis")

    from rekipedia.orchestrator.run_ask import _build_full_system

    llm_config = LLMConfig(provider="openai", model="gpt-4o-mini", api_key="test")

    with patch("rekipedia.orchestrator.run_ask._rewrite_query", side_effect=lambda q, *a, **kw: q):
        with patch("rekipedia.orchestrator.run_ask._rag_chunks", return_value=[]):
            system = _build_full_system("How do we handle sessions?", output_dir, llm_config)

    assert "Tech Lead Notes" in system
    assert "Redis" in system


def test_notes_not_injected_when_empty(tmp_path: Path):
    """If no notes, context should not have the notes section."""
    output_dir = tmp_path / ".rekipedia"
    output_dir.mkdir()
    db_path = output_dir / "store.db"
    with SqliteStore(db_path) as store:
        pass  # no notes

    from rekipedia.orchestrator.run_ask import _build_full_system

    llm_config = LLMConfig(provider="openai", model="gpt-4o-mini", api_key="test")

    with patch("rekipedia.orchestrator.run_ask._rewrite_query", side_effect=lambda q, *a, **kw: q):
        with patch("rekipedia.orchestrator.run_ask._rag_chunks", return_value=[]):
            system = _build_full_system("How does auth work?", output_dir, llm_config)

    assert "Tech Lead Notes" not in system
