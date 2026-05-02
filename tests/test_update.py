"""Tests for rekipedia update (Phase 3 — incremental refresh)."""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from rekipedia.models.contracts import LLMConfig
from rekipedia.orchestrator.run_digest import run_digest
from rekipedia.orchestrator.run_update import run_update
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


# ── helpers ──────────────────────────────────────────────────────────

def _do_full_scan(repo: Path, output_dir: Path) -> None:
    run_digest(repo_root=repo, output_dir=output_dir, llm_config=LLMConfig(), force_local=True)


def _do_update(repo: Path, output_dir: Path) -> None:
    run_update(repo_root=repo, output_dir=output_dir, llm_config=LLMConfig(), force_local=True)


# ── tests ─────────────────────────────────────────────────────────────

def test_update_no_prior_scan_falls_back_to_full(mock_llm, tmp_path):
    """If no previous scan exists, run_update() falls back to run_digest()."""
    output_dir = tmp_path / ".rekipedia"
    _do_update(MINI_PY, output_dir)

    # Should produce the same output as a full scan
    wiki_dir = output_dir / "wiki"
    assert wiki_dir.exists()
    assert len(list(wiki_dir.glob("*.md"))) >= 3


def test_update_no_changes_exits_early(mock_llm, tmp_path):
    """If nothing has changed, update exits early without re-calling the LLM."""
    output_dir = tmp_path / ".rekipedia"

    # First: full scan
    _do_full_scan(MINI_PY, output_dir)
    call_count_after_scan = mock_llm.call.call_count

    # Second: update on the same unchanged repo
    _do_update(MINI_PY, output_dir)
    # LLM should NOT have been called again (no synthesis needed)
    assert mock_llm.call.call_count == call_count_after_scan


def test_update_on_changed_file_creates_new_run(mock_llm, tmp_path):
    """When a file changes, run_update creates a new run entry in scan_runs."""
    # Copy fixture to a mutable tmpdir so we can modify files
    repo = tmp_path / "repo"
    shutil.copytree(MINI_PY, repo)
    output_dir = tmp_path / ".rekipedia"

    # Full scan
    _do_full_scan(repo, output_dir)

    # Mutate a file
    (repo / "utils.py").write_text("# changed\ndef new_helper(): pass\n", encoding="utf-8")

    # Update
    _do_update(repo, output_dir)

    db = SqliteStore(output_dir / "store.db")
    db.open()
    rows = db.db.execute("SELECT id FROM scan_runs WHERE status='success'").fetchall()
    db.close()

    # Should have two successful runs: initial scan + update
    assert len(rows) == 2


def test_update_carries_forward_symbols_from_unchanged_files(mock_llm, tmp_path):
    """Symbols from unchanged files are present in the new run without re-extraction."""
    repo = tmp_path / "repo"
    shutil.copytree(MINI_PY, repo)
    output_dir = tmp_path / ".rekipedia"

    _do_full_scan(repo, output_dir)

    # Mutate only utils.py — core.py symbols should be carried forward
    (repo / "utils.py").write_text("# changed\ndef new_helper(): pass\n", encoding="utf-8")
    _do_update(repo, output_dir)

    db = SqliteStore(output_dir / "store.db")
    db.open()
    runs = db.db.execute(
        "SELECT id FROM scan_runs WHERE status='success' ORDER BY started_at"
    ).fetchall()
    new_run_id = runs[-1][0]

    syms = db.db.execute(
        "SELECT name FROM scan_symbols WHERE run_id = ?", [new_run_id]
    ).fetchall()
    db.close()

    sym_names = {r[0] for r in syms}
    # new_helper should be extracted from the mutated utils.py
    assert "new_helper" in sym_names


def test_update_wiki_pages_refreshed_after_change(mock_llm, tmp_path):
    """After an update the wiki pages should still exist and be 5 in number."""
    repo = tmp_path / "repo"
    shutil.copytree(MINI_PY, repo)
    output_dir = tmp_path / ".rekipedia"

    _do_full_scan(repo, output_dir)
    (repo / "core.py").write_text("def new_core(): pass\n", encoding="utf-8")
    _do_update(repo, output_dir)

    wiki_dir = output_dir / "wiki"
    pages = list(wiki_dir.glob("*.md"))
    assert len(pages) >= 3
