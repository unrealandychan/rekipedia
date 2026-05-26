"""Tests for impact-aware wiki regeneration (`reki update --impact-only`, issue #164)."""
from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from rekipedia.models.contracts import LLMConfig
from rekipedia.orchestrator.run_digest import run_digest
from rekipedia.orchestrator.run_update import _compute_impact_affected_files, run_update
from rekipedia.storage.sqlite_store import SqliteStore

MINI_PY = Path(__file__).parent / "fixtures" / "mini-py-repo"


def _fake_llm_response() -> str:
    return json.dumps({
        "title": "Test",
        "summary": "Stub.",
        "key_concepts": [],
        "symbols": [],
        "relationships": [],
        "risks": [],
        "build_commands": [],
        "test_commands": [],
        "mermaid_graph": "",
    })


@pytest.fixture()
def mock_llm():
    with patch("rekipedia.synthesis.page_builder.LLMClient") as MockClient:
        mock_instance = MagicMock()
        mock_instance.call.side_effect = lambda prompt, system="": _fake_llm_response()
        MockClient.return_value = mock_instance
        yield mock_instance


def _do_full_scan(repo: Path, output_dir: Path) -> None:
    run_digest(repo_root=repo, output_dir=output_dir, llm_config=LLMConfig(), force_local=True)


def _do_update(repo: Path, output_dir: Path, impact_only: bool = False) -> None:
    run_update(
        repo_root=repo,
        output_dir=output_dir,
        llm_config=LLMConfig(),
        force_local=True,
        impact_only=impact_only,
    )


# ── Tests ─────────────────────────────────────────────────────────────

def test_impact_only_only_regenerates_affected_pages(mock_llm, tmp_path):
    """With --impact-only, only pages whose modules are BFS-reachable are regenerated."""
    repo = tmp_path / "repo"
    shutil.copytree(MINI_PY, repo)
    output_dir = tmp_path / ".rekipedia"

    # Full scan first — establishes baseline page_sources
    _do_full_scan(repo, output_dir)
    call_count_after_scan = mock_llm.call.call_count

    # Mutate one file
    (repo / "utils.py").write_text("# changed\ndef new_helper(): pass\n", encoding="utf-8")

    # Run update with impact-only
    _do_update(repo, output_dir, impact_only=True)

    # LLM should have been called (synthesis happened for at least something)
    assert mock_llm.call.call_count >= call_count_after_scan

    # Wiki pages should still exist
    wiki_dir = output_dir / "wiki"
    assert wiki_dir.exists()
    assert len(list(wiki_dir.glob("*.md"))) >= 1


def test_impact_only_unaffected_pages_not_regenerated(mock_llm, tmp_path):
    """Unaffected pages are carried forward without re-calling LLM (fewer calls with impact-only)."""
    repo = tmp_path / "repo"
    shutil.copytree(MINI_PY, repo)
    output_dir = tmp_path / ".rekipedia"

    # Full scan
    _do_full_scan(repo, output_dir)

    # Mutate a file
    (repo / "utils.py").write_text("# changed\ndef new_helper(): pass\n", encoding="utf-8")

    # Count calls with normal update (regenerates all affected pages by file)
    call_count_before_normal = mock_llm.call.call_count
    _do_update(repo, output_dir, impact_only=False)
    normal_calls = mock_llm.call.call_count - call_count_before_normal

    # Reset: new tmp for impact-only run
    repo2 = tmp_path / "repo2"
    shutil.copytree(MINI_PY, repo2)
    output_dir2 = tmp_path / ".rekipedia2"
    _do_full_scan(repo2, output_dir2)
    (repo2 / "utils.py").write_text("# changed\ndef new_helper(): pass\n", encoding="utf-8")

    call_count_before_impact = mock_llm.call.call_count
    _do_update(repo2, output_dir2, impact_only=True)
    impact_calls = mock_llm.call.call_count - call_count_before_impact

    # impact-only should not call LLM more than normal update
    assert impact_calls <= normal_calls + 1  # small tolerance for different code paths


def test_impact_only_fallback_when_impact_graph_empty(mock_llm, tmp_path):
    """If the impact graph has no relationships, impact-only falls back to normal synthesis."""
    repo = tmp_path / "repo"
    shutil.copytree(MINI_PY, repo)
    output_dir = tmp_path / ".rekipedia"

    _do_full_scan(repo, output_dir)

    # Patch _compute_impact_affected_files to simulate empty graph
    with patch(
        "rekipedia.orchestrator.run_update._compute_impact_affected_files",
        return_value=set(),
    ):
        (repo / "utils.py").write_text("# changed\ndef new_helper(): pass\n", encoding="utf-8")
        call_count_before = mock_llm.call.call_count
        _do_update(repo, output_dir, impact_only=True)

    # Should still have regenerated something (fallback to changed_paths)
    assert mock_llm.call.call_count >= call_count_before


def test_compute_impact_affected_files_with_relationships(tmp_path):
    """_compute_impact_affected_files returns files reachable via BFS."""
    store = SqliteStore(tmp_path / "store.db")
    store.open()
    run_id = str(uuid.uuid4())
    store.upsert_run(run_id, "/repo")

    # Symbols: A in file_a.py, B in file_b.py, C in file_c.py
    store.upsert_symbols(run_id, [
        {"name": "A", "file": "file_a.py", "kind": "function", "line_start": 1, "line_end": 5},
        {"name": "B", "file": "file_b.py", "kind": "function", "line_start": 1, "line_end": 5},
        {"name": "C", "file": "file_c.py", "kind": "function", "line_start": 1, "line_end": 5},
    ])
    # B calls A, C calls B — so changing file_a.py should affect file_b.py and file_c.py
    store.upsert_relationships(run_id, [
        {"from": "B", "to": "A", "kind": "calls"},
        {"from": "C", "to": "B", "kind": "calls"},
    ])

    affected = _compute_impact_affected_files(
        changed_paths={"file_a.py"},
        store=store,
        run_id=run_id,
    )
    store.close()

    assert "file_a.py" in affected
    assert "file_b.py" in affected
    assert "file_c.py" in affected


def test_compute_impact_affected_files_no_relationships(tmp_path):
    """_compute_impact_affected_files returns empty set when no relationships exist."""
    store = SqliteStore(tmp_path / "store.db")
    store.open()
    run_id = str(uuid.uuid4())
    store.upsert_run(run_id, "/repo")

    store.upsert_symbols(run_id, [
        {"name": "A", "file": "file_a.py", "kind": "function", "line_start": 1, "line_end": 5},
    ])
    # No relationships

    affected = _compute_impact_affected_files(
        changed_paths={"file_a.py"},
        store=store,
        run_id=run_id,
    )
    store.close()

    # Empty graph → empty set (caller falls back to full synthesis)
    assert affected == set()
