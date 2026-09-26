"""Tests for index staleness checking and warning banner."""
from __future__ import annotations

from pathlib import Path
import pytest

from rekipedia.models.contracts import FileManifest
from rekipedia.orchestrator.snapshotter import Snapshotter
from rekipedia.storage.sqlite_store import SqliteStore
from rekipedia.utils.staleness import check_index_staleness


def test_staleness_fresh_repo(tmp_path: Path):
    f1 = tmp_path / "main.py"
    f1.write_text("print('hello')")

    dot_reki = tmp_path / ".rekipedia"
    dot_reki.mkdir()
    db_file = dot_reki / "store.db"
    run_id = "run_fresh"

    with SqliteStore(db_file) as store:
        store.upsert_run(run_id, str(tmp_path), status="success")
        files = Snapshotter(tmp_path).snapshot()
        for f in files:
            store.upsert_file(run_id, f.path, f.sha256, f.size_bytes, f.language)

        stale = check_index_staleness(tmp_path, store, run_id=run_id)
        assert stale["is_stale"] is False
        assert stale["count"] == 0
        assert stale["banner"] == ""


def test_staleness_detects_modified_file(tmp_path: Path):
    f1 = tmp_path / "main.py"
    f1.write_text("print('hello')")

    dot_reki = tmp_path / ".rekipedia"
    dot_reki.mkdir()
    db_file = dot_reki / "store.db"
    run_id = "run_modified"

    with SqliteStore(db_file) as store:
        store.upsert_run(run_id, str(tmp_path), status="success")
        files = Snapshotter(tmp_path).snapshot()
        for f in files:
            store.upsert_file(run_id, f.path, f.sha256, f.size_bytes, f.language)

        # Modify main.py
        f1.write_text("print('hello world modified')")

        stale = check_index_staleness(tmp_path, store, run_id=run_id)
        assert stale["is_stale"] is True
        assert stale["count"] == 1
        assert "main.py" in stale["changed_files"]
        assert "modified since last scan" in stale["banner"]
        assert "reki update" in stale["banner"]
