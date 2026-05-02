"""Tests for qa_history table and SqliteStore Q&A methods."""
import tempfile
from pathlib import Path

from rekipedia.storage.sqlite_store import SqliteStore


def test_qa_history_table_exists():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "store.db"
        with SqliteStore(db) as store:
            rows = store._c.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='qa_history'"
            ).fetchall()
            assert rows, "qa_history table missing"


def test_save_and_retrieve_qa():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "store.db"
        with SqliteStore(db) as store:
            rid = store.save_qa("/my/repo", "How does auth work?", "It uses JWT.", "gpt-4o")
            assert rid == 1
            history = store.get_qa_history("/my/repo")
            assert len(history) == 1
            assert history[0]["question"] == "How does auth work?"
            assert history[0]["model"] == "gpt-4o"


def test_qa_history_only_returns_own_repo():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "store.db"
        with SqliteStore(db) as store:
            store.save_qa("/repo-a", "Q1", "A1", "")
            store.save_qa("/repo-b", "Q2", "A2", "")
            assert len(store.get_qa_history("/repo-a")) == 1
            assert len(store.get_qa_history("/repo-b")) == 1
