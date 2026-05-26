"""Tests for SQLite performance optimisations (issues #108-#111)."""
from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from rekipedia.storage.sqlite_store import SqliteStore


def make_store(tmp_path: Path) -> SqliteStore:
    store = SqliteStore(tmp_path / "test.db")
    store.open()
    return store


# ── #108 Batch commits ────────────────────────────────────────────────

def test_upsert_files_batch(tmp_path):
    store = make_store(tmp_path)
    run_id = "run-batch-files"
    store.upsert_run(run_id, "/repo")

    files = [
        SimpleNamespace(path=f"src/file{i}.py", sha256=f"sha{i}", size_bytes=100 * i, language="python")
        for i in range(5)
    ]
    store.upsert_files_batch(run_id, files)

    rows = store.get_files_for_run(run_id)
    assert len(rows) == 5
    paths = {r["path"] for r in rows}
    assert paths == {f"src/file{i}.py" for i in range(5)}
    store.close()


def test_upsert_pages_batch(tmp_path):
    store = make_store(tmp_path)
    run_id = "run-batch-pages"
    store.upsert_run(run_id, "/repo")

    pages = {
        "overview": ("Overview", "# Overview\nContent"),
        "architecture": ("Architecture", "# Architecture\nContent"),
        "api-reference": ("Api Reference", "# API\nContent"),
    }
    store.upsert_pages_batch(run_id, pages)

    rows = store.get_pages(run_id)
    assert len(rows) == 3
    slugs = {r[1] for r in rows}
    assert "overview" in slugs
    assert "architecture" in slugs
    store.close()


def test_upsert_page_sources_batch(tmp_path):
    store = make_store(tmp_path)
    run_id = "run-batch-sources"
    store.upsert_run(run_id, "/repo")

    # upsert_page_sources now uses executemany
    store.upsert_page_sources(run_id, "overview", ["src/a.py", "src/b.py", "src/c.py"])

    found = store.get_pages_for_files(run_id, ["src/a.py"])
    assert "overview" in found

    found2 = store.get_pages_for_files(run_id, ["src/b.py", "src/c.py"])
    assert "overview" in found2
    store.close()


# ── #109 PRAGMA settings ──────────────────────────────────────────────

def test_pragma_settings(tmp_path):
    """synchronous should be NORMAL (1) after opening the store."""
    store = make_store(tmp_path)
    row = store._c.execute("PRAGMA synchronous").fetchone()
    # NORMAL = 1
    assert row[0] == 1, f"Expected synchronous=1 (NORMAL), got {row[0]}"
    store.close()


# ── #110 Table names cache ────────────────────────────────────────────

def test_table_names_cache(tmp_path):
    store = make_store(tmp_path)
    # First call populates cache
    names1 = store._table_names()
    # Second call should return cached object
    names2 = store._table_names()
    assert names1 is names2
    store.close()


# ── #111 SQL-side copy filtering ─────────────────────────────────────

def test_copy_unchanged_sql_filtering(tmp_path):
    store = make_store(tmp_path)
    from_run = "run-from"
    to_run = "run-to"
    store.upsert_run(from_run, "/repo")
    store.upsert_run(to_run, "/repo")

    symbols = [
        {"name": f"func{i}", "kind": "function", "file": f"src/file{i}.py",
         "line_start": 1, "line_end": 10, "signature": "", "docstring": ""}
        for i in range(4)
    ]
    store.upsert_symbols(from_run, symbols)

    # Exclude file0.py and file1.py
    exclude = {"src/file0.py", "src/file1.py"}
    count = store.copy_unchanged_symbols(from_run, to_run, exclude)

    assert count == 2
    copied = store.get_all_symbols(to_run)
    copied_files = {r["file"] if isinstance(r, dict) else r[3] for r in copied}
    assert "src/file0.py" not in copied_files
    assert "src/file1.py" not in copied_files
    assert "src/file2.py" in copied_files
    assert "src/file3.py" in copied_files
    store.close()


# ── #108 Rollback on error ────────────────────────────────────────────

def test_batch_rollback(tmp_path):
    """When upsert_files_batch encounters a DB error, nothing should be committed."""
    store = make_store(tmp_path)
    run_id = "run-rollback"
    store.upsert_run(run_id, "/repo")

    # Inject a bad row that will cause a constraint / type error at executemany level
    # by patching upsert_files_batch to call the real impl but with a connection that
    # raises on executemany.  Since sqlite3.Connection.executemany is read-only (C slot),
    # we swap out the internal cursor wrapper with a subclass that raises.
    import sqlite3 as _sqlite3

    original_conn = store._conn

    class _FailConn:
        """Thin proxy that raises on executemany to simulate a mid-batch DB error."""
        def __getattr__(self, name):
            return getattr(original_conn, name)

        def executemany(self, sql, rows):
            raise RuntimeError("Simulated DB error")

        def execute(self, *a, **kw):
            return original_conn.execute(*a, **kw)

        def commit(self):
            original_conn.commit()

    store._conn = _FailConn()

    files = [
        SimpleNamespace(path=f"src/x{i}.py", sha256=f"sha{i}", size_bytes=i, language="python")
        for i in range(3)
    ]

    with pytest.raises(RuntimeError, match="upsert_files_batch failed"):
        store.upsert_files_batch(run_id, files)

    # Restore real connection and verify nothing was committed
    store._conn = original_conn
    rows = store.get_files_for_run(run_id)
    assert len(rows) == 0, f"Expected 0 rows after rollback, got {len(rows)}"
    store.close()
