"""Integration test for rekipedia scan using LocalRunner (no Docker required)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from rekipedia.models.contracts import LLMConfig
from rekipedia.orchestrator.run_digest import run_digest

MINI_PY = Path(__file__).parent / "fixtures" / "mini-py-repo"
MINI_TS = Path(__file__).parent / "fixtures" / "mini-ts-repo"


def _fake_llm_response(slug: str = "index") -> str:
    import json
    return json.dumps({
        "title": slug.title(),
        "summary": "Stub summary.",
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


def test_scan_mini_py_repo(mock_llm, tmp_path):
    output_dir = tmp_path / ".rekipedia"
    run_digest(
        repo_root=MINI_PY,
        output_dir=output_dir,
        llm_config=LLMConfig(),
        force_local=True,
    )

    # Wiki pages created
    wiki_dir = output_dir / "wiki"
    assert wiki_dir.exists()
    pages = list(wiki_dir.glob("*.md"))
    assert len(pages) >= 3

    # Manifest created
    manifest = output_dir / "exports" / "manifest.json"
    assert manifest.exists()

    import json
    data = json.loads(manifest.read_text())
    assert data["file_count"] > 0
    assert len(data["pages"]) >= 3


def test_scan_creates_diagrams(mock_llm, tmp_path):
    output_dir = tmp_path / ".rekipedia"
    run_digest(
        repo_root=MINI_PY,
        output_dir=output_dir,
        llm_config=LLMConfig(),
        force_local=True,
    )
    diagram_dir = output_dir / "diagrams"
    assert diagram_dir.exists()


def test_scan_populates_db(mock_llm, tmp_path):
    output_dir = tmp_path / ".rekipedia"
    run_digest(
        repo_root=MINI_PY,
        output_dir=output_dir,
        llm_config=LLMConfig(),
        force_local=True,
    )
    db_path = output_dir / "store.db"
    assert db_path.exists()

    import sqlite_utils
    db = sqlite_utils.Database(db_path)
    assert db["scan_runs"].count >= 1
    # symbols should be populated (scan_symbols table may or may not have rows)
    assert "scan_runs" in db.table_names()


def test_scan_mini_ts_repo(mock_llm, tmp_path):
    output_dir = tmp_path / ".rekipedia"
    run_digest(
        repo_root=MINI_TS,
        output_dir=output_dir,
        llm_config=LLMConfig(),
        force_local=True,
    )
    manifest = output_dir / "exports" / "manifest.json"
    assert manifest.exists()
