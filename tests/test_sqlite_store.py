"""Tests for SqliteStore."""
from __future__ import annotations

from pathlib import Path

import pytest

from rekipedia.storage.sqlite_store import SqliteStore


def test_open_creates_database(tmp_path: Path) -> None:
    db_path = tmp_path / "store.db"
    with SqliteStore(db_path) as store:
        assert db_path.exists()
        assert store.current_schema_version() >= 1


def test_schema_tables_exist(tmp_path: Path) -> None:
    with SqliteStore(tmp_path / "store.db") as store:
        table_names = store.table_names()
    expected = {
        "schema_version", "runs", "repo_snapshot", "files",
        "content_hashes", "symbols", "relationships", "pages",
        "chunks", "diagrams", "qa_cache", "generator_config", "ignore_rules",
    }
    assert expected.issubset(table_names)


def test_open_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "store.db"
    # First open — applies migrations
    with SqliteStore(db_path) as store:
        v1 = store.current_schema_version()
    # Second open — schema already at v1, should not error
    with SqliteStore(db_path) as store:
        v2 = store.current_schema_version()
    assert v1 == v2


def test_closed_store_raises(tmp_path: Path) -> None:
    store = SqliteStore(tmp_path / "store.db")
    with pytest.raises(RuntimeError, match="not open"):
        _ = store.db
