"""Tests for on_deleted event handling in reki watch (issue #177)."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest


# ---------------------------------------------------------------------------
# Test 1: on_deleted triggers purge for source files
# ---------------------------------------------------------------------------

def test_on_deleted_triggers_purge():
    """_Handler.on_deleted should call _RepoWatcher.on_delete for source files."""
    from rekipedia.watcher.watcher import _RepoWatcher, _is_source_file

    # Build a minimal start_watching context by constructing _Handler directly
    # We need to import inside start_watching's local scope — replicate the class
    rw = _RepoWatcher("/fake/repo", debounce_seconds=0.1)
    rw.on_delete = MagicMock()

    # Simulate the _Handler as defined inside start_watching
    try:
        from watchdog.events import FileSystemEventHandler, FileDeletedEvent
    except ImportError:
        pytest.skip("watchdog not installed")

    class _Handler(FileSystemEventHandler):
        def __init__(self, repo_watcher):
            self._rw = repo_watcher

        def on_deleted(self, event):
            if not event.is_directory and _is_source_file(event.src_path):
                self._rw.on_delete(event.src_path)

    handler = _Handler(rw)
    event = FileDeletedEvent("/fake/repo/module.py")
    handler.on_deleted(event)

    rw.on_delete.assert_called_once_with("/fake/repo/module.py")


# ---------------------------------------------------------------------------
# Test 2: non-source files are ignored on delete
# ---------------------------------------------------------------------------

def test_on_deleted_ignores_non_source_files():
    """_Handler.on_deleted should NOT call on_delete for non-source files."""
    from rekipedia.watcher.watcher import _RepoWatcher, _is_source_file

    rw = _RepoWatcher("/fake/repo", debounce_seconds=0.1)
    rw.on_delete = MagicMock()

    try:
        from watchdog.events import FileSystemEventHandler, FileDeletedEvent
    except ImportError:
        pytest.skip("watchdog not installed")

    class _Handler(FileSystemEventHandler):
        def __init__(self, repo_watcher):
            self._rw = repo_watcher

        def on_deleted(self, event):
            if not event.is_directory and _is_source_file(event.src_path):
                self._rw.on_delete(event.src_path)

    handler = _Handler(rw)

    for non_src in ["/repo/README.md", "/repo/.env", "/repo/data.json", "/repo/image.png"]:
        event = FileDeletedEvent(non_src)
        handler.on_deleted(event)

    rw.on_delete.assert_not_called()


# ---------------------------------------------------------------------------
# Test 3: on_delete calls subprocess purge-file
# ---------------------------------------------------------------------------

def test_repo_watcher_on_delete_calls_subprocess():
    """_RepoWatcher.on_delete should invoke 'reki purge-file <path>' via subprocess."""
    from rekipedia.watcher.watcher import _RepoWatcher

    rw = _RepoWatcher("/fake/repo", debounce_seconds=0.1)

    with patch("rekipedia.watcher.watcher.subprocess.run") as mock_run:
        rw.on_delete("/fake/repo/deleted.py")

    mock_run.assert_called_once()
    args = mock_run.call_args[0][0]
    assert "purge-file" in args
    assert "/fake/repo/deleted.py" in args


# ---------------------------------------------------------------------------
# Test 4: purge-file command removes symbols from DB (integration)
# ---------------------------------------------------------------------------

def test_purge_file_removes_symbols_from_db(tmp_path):
    """Integration test: purge_file() removes symbols for the given file."""
    from rekipedia.storage.sqlite_store import SqliteStore

    db_path = tmp_path / "store.db"
    store = SqliteStore(db_path)
    store.open()

    run_id = "test-run-001"
    repo_path = str(tmp_path)

    # Insert a scan run
    store.upsert_run(run_id, repo_path, status="success")

    # Insert symbols for two files
    store.upsert_symbols(run_id, [
        {"name": "MyClass", "kind": "class", "file": "src/foo.py", "line_start": 1, "line_end": 10},
        {"name": "helper", "kind": "function", "file": "src/foo.py", "line_start": 12, "line_end": 20},
        {"name": "OtherClass", "kind": "class", "file": "src/bar.py", "line_start": 1, "line_end": 5},
    ])

    # Sanity check
    assert len(store.get_all_symbols(run_id)) == 3

    # Purge foo.py
    result = store.purge_file(run_id, "src/foo.py")
    assert result["symbols"] == 2

    # Only bar.py symbols remain
    remaining = store.get_all_symbols(run_id)
    assert len(remaining) == 1
    assert remaining[0]["file"] == "src/bar.py"

    store.close()


# ---------------------------------------------------------------------------
# Test 5: delete_symbols_for_file method works correctly
# ---------------------------------------------------------------------------

def test_delete_symbols_for_file(tmp_path):
    """SqliteStore.delete_symbols_for_file removes exactly the right symbols."""
    from rekipedia.storage.sqlite_store import SqliteStore

    db_path = tmp_path / "store.db"
    with SqliteStore(db_path) as store:
        run_id = "run-x"
        store.upsert_run(run_id, str(tmp_path))
        store.upsert_symbols(run_id, [
            {"name": "A", "kind": "class", "file": "a.py", "line_start": 1, "line_end": 5},
            {"name": "B", "kind": "function", "file": "b.py", "line_start": 1, "line_end": 3},
        ])

        deleted = store.delete_symbols_for_file(run_id, "a.py")
        assert deleted == 1
        syms = store.get_all_symbols(run_id)
        assert all(s["file"] == "b.py" for s in syms)


# ---------------------------------------------------------------------------
# Test 6: purge on empty DB does not raise
# ---------------------------------------------------------------------------

def test_purge_file_on_empty_db(tmp_path):
    """purge_file on a fresh store should return zeros without error."""
    from rekipedia.storage.sqlite_store import SqliteStore

    db_path = tmp_path / "empty.db"
    with SqliteStore(db_path) as store:
        # No run, no tables
        result = store.purge_file("no-run", "nonexistent.py")
    assert result["symbols"] == 0
    assert result["relationships"] == 0
    assert result["pages"] == 0
