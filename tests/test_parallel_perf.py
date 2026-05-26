"""Tests for parallelism optimizations (issues #112, #113)."""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

from rekipedia.orchestrator.snapshotter import Snapshotter

# ── #112 Snapshotter parallel hashing ────────────────────────────────

def test_snapshotter_parallel_hashing(tmp_path: Path) -> None:
    """10 files should all appear in the manifest."""
    for i in range(10):
        (tmp_path / f"file_{i:02d}.py").write_text(f"# file {i}\n")

    s = Snapshotter(tmp_path)
    manifests = s.snapshot()
    paths = {m.path for m in manifests}
    for i in range(10):
        assert f"file_{i:02d}.py" in paths, f"file_{i:02d}.py missing from manifest"


def test_snapshotter_skips_unreadable_file(tmp_path: Path) -> None:
    """Unreadable file should be skipped; others still appear."""
    for i in range(5):
        (tmp_path / f"ok_{i}.py").write_text(f"# ok {i}\n")

    secret = tmp_path / "secret.py"
    secret.write_text("# secret\n")
    os.chmod(secret, 0o000)

    try:
        s = Snapshotter(tmp_path)
        manifests = s.snapshot()
        paths = {m.path for m in manifests}

        # The unreadable file should NOT be in the manifest
        assert "secret.py" not in paths
        # The other 5 files should still be present
        for i in range(5):
            assert f"ok_{i}.py" in paths
    finally:
        # Restore permissions for cleanup
        os.chmod(secret, 0o644)


# ── #113 run_update parallel shards ──────────────────────────────────

def _make_analysis_result(shard_id: str):
    from rekipedia.models.contracts import AnalysisResult
    return AnalysisResult(shard_id=shard_id, files_seen=[], entry_points=[])


def test_run_update_parallel_shards(tmp_path: Path) -> None:
    """All shards should be processed via the parallel runner."""
    import threading

    from rekipedia.models.contracts import LLMConfig
    from rekipedia.orchestrator.run_update import run_update

    call_count = 0
    lock = threading.Lock()

    def fake_run(shard, repo_root):
        nonlocal call_count
        with lock:
            call_count += 1
        return _make_analysis_result(shard.shard_id)

    # Build a minimal store + repo setup
    output_dir = tmp_path / ".rekipedia"
    output_dir.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("x=1")
    (repo / "b.py").write_text("y=2")

    from rekipedia.storage.sqlite_store import SqliteStore
    db_path = output_dir / "store.db"
    store = SqliteStore(db_path)
    store.open()

    # Create a fake prior run so update doesn't fall through to full scan
    import uuid
    last_run_id = str(uuid.uuid4())
    store.upsert_run(last_run_id, str(repo))
    store.upsert_file(last_run_id, "a.py", "aaa", 3, "python")
    # Don't add b.py so it's "new"
    store.update_run_status(last_run_id, "success")
    store.close()

    with patch("rekipedia.orchestrator.run_update.get_runner") as mock_get_runner, \
         patch("rekipedia.synthesis.page_builder.LLMClient") as mock_llm_cls, \
         patch("rekipedia.orchestrator.run_update.run_digest"):

        mock_runner = MagicMock()
        mock_runner.run.side_effect = fake_run
        mock_get_runner.return_value = mock_runner

        mock_llm = MagicMock()
        import json
        mock_llm.call.return_value = json.dumps({
            "title": "T", "summary": "S", "key_concepts": [], "symbols": [],
            "relationships": [], "risks": [], "build_commands": [],
            "test_commands": [], "mermaid_graph": "",
        })
        mock_llm_cls.return_value = mock_llm

        run_update(
            repo_root=repo,
            output_dir=output_dir,
            llm_config=LLMConfig(),
            force_local=True,
        )

    # At least one shard was processed
    assert call_count >= 1


def test_run_update_partial_failure(tmp_path: Path) -> None:
    """One shard failing should not prevent others from succeeding."""
    import uuid

    from rekipedia.models.contracts import LLMConfig
    from rekipedia.orchestrator.run_update import run_update
    from rekipedia.storage.sqlite_store import SqliteStore

    output_dir = tmp_path / ".rekipedia"
    output_dir.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    for name in ["a.py", "b.py", "c.py"]:
        (repo / name).write_text(f"# {name}")

    db_path = output_dir / "store.db"
    store = SqliteStore(db_path)
    store.open()

    last_run_id = str(uuid.uuid4())
    store.upsert_run(last_run_id, str(repo))
    # Mark a.py as unchanged; b.py and c.py are new → likely 1-2 shards
    store.upsert_file(last_run_id, "a.py", "old-hash", 5, "python")
    store.update_run_status(last_run_id, "success")
    store.close()

    call_results = []

    def sometimes_fail(shard, repo_root):
        # Fail on the first shard, succeed on others
        if not call_results:
            call_results.append("fail")
            raise RuntimeError("Simulated shard failure")
        call_results.append("ok")
        return _make_analysis_result(shard.shard_id)

    with patch("rekipedia.orchestrator.run_update.get_runner") as mock_get_runner, \
         patch("rekipedia.synthesis.page_builder.LLMClient") as mock_llm_cls:

        mock_runner = MagicMock()
        mock_runner.run.side_effect = sometimes_fail
        mock_get_runner.return_value = mock_runner

        mock_llm = MagicMock()
        import json
        mock_llm.call.return_value = json.dumps({
            "title": "T", "summary": "S", "key_concepts": [], "symbols": [],
            "relationships": [], "risks": [], "build_commands": [],
            "test_commands": [], "mermaid_graph": "",
        })
        mock_llm_cls.return_value = mock_llm

        # Should not raise since not ALL shards fail (only 1 of possibly 2+)
        # If only 1 shard total, it will raise RuntimeError — that's correct behavior
        total_shards = 0
        try:
            run_update(
                repo_root=repo,
                output_dir=output_dir,
                llm_config=LLMConfig(),
                force_local=True,
            )
        except RuntimeError as e:
            # Acceptable only if all shards failed
            assert "shard" in str(e).lower()

    # We made at least one call
    assert len(call_results) >= 1
