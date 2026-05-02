"""Tests for rekipedia ask (Phase 4 — grounded Q&A)."""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from rekipedia.models.contracts import LLMConfig
from rekipedia.orchestrator.run_ask import run_ask
from rekipedia.orchestrator.run_digest import run_digest

MINI_PY = Path(__file__).parent / "fixtures" / "mini-py-repo"


def _fake_page_response() -> str:
    return json.dumps({
        "title": "Index",
        "summary": "A small test project.",
        "key_concepts": [],
        "symbols": [],
        "relationships": [],
        "risks": [],
        "build_commands": [],
        "test_commands": [],
        "mermaid_graph": "",
    })


@pytest.fixture()
def mock_page_llm():
    with patch("rekipedia.synthesis.page_builder.LLMClient") as MockClient:
        mock_instance = MagicMock()
        mock_instance.call.side_effect = lambda prompt, system="": _fake_page_response()
        MockClient.return_value = mock_instance
        yield mock_instance


@pytest.fixture()
def scanned_repo(mock_page_llm, tmp_path):
    """Run a full scan and return (repo_root, output_dir)."""
    repo = tmp_path / "repo"
    shutil.copytree(MINI_PY, repo)
    output_dir = tmp_path / ".rekipedia"
    run_digest(repo_root=repo, output_dir=output_dir, llm_config=LLMConfig(), force_local=True)
    return repo, output_dir


# ── tests ─────────────────────────────────────────────────────────────

def test_ask_returns_string(scanned_repo):
    repo, output_dir = scanned_repo
    with patch("rekipedia.orchestrator.run_ask.LLMClient") as MockAskClient:
        mock = MagicMock()
        mock.call.return_value = "The entry point is main.py."
        MockAskClient.return_value = mock

        answer = run_ask("What is the entry point?", repo, output_dir, LLMConfig())

    assert isinstance(answer, str)
    assert len(answer) > 0


def test_ask_includes_wiki_context_in_system_prompt(scanned_repo):
    """The system prompt passed to the LLM should include wiki page content."""
    repo, output_dir = scanned_repo

    captured_system: list[str] = []

    def _capture_call(prompt: str, system: str = "") -> str:
        captured_system.append(system)
        return "mocked answer"

    with patch("rekipedia.orchestrator.run_ask.LLMClient") as MockAskClient:
        mock = MagicMock()
        mock.call.side_effect = _capture_call
        MockAskClient.return_value = mock

        run_ask("How does it work?", repo, output_dir, LLMConfig())

    assert captured_system, "LLMClient.call was never invoked"
    system_text = captured_system[0]
    # The system prompt should contain the ask_system.md preamble
    assert "grounded" in system_text.lower() or "context" in system_text.lower()
    # And at least one wiki page reference
    assert "[" in system_text  # page references like [architecture.md]


def test_ask_raises_if_no_scan(tmp_path):
    """run_ask raises RuntimeError if no store.db exists."""
    repo = tmp_path / "repo"
    repo.mkdir()
    output_dir = tmp_path / ".rekipedia"

    with pytest.raises(RuntimeError, match="No knowledge store found"):
        run_ask("anything?", repo, output_dir, LLMConfig())


def test_ask_raises_if_no_successful_run(tmp_path):
    """run_ask raises RuntimeError if store.db exists but has no successful run."""
    from rekipedia.storage.sqlite_store import SqliteStore

    output_dir = tmp_path / ".rekipedia"
    output_dir.mkdir(parents=True)

    # Create an empty (opened) store — no runs
    db_path = output_dir / "store.db"
    store = SqliteStore(db_path)
    store.open()
    store.close()

    repo = tmp_path / "repo"
    repo.mkdir()

    with pytest.raises(RuntimeError, match="No successful scan found"):
        run_ask("anything?", repo, output_dir, LLMConfig())


def test_ask_uses_symbols_json_in_context(scanned_repo):
    """The LLM call should include symbol index content when symbols.json exists."""
    repo, output_dir = scanned_repo

    # Ensure symbols.json has some content
    symbols_path = output_dir / "exports" / "symbols.json"
    symbols_path.parent.mkdir(parents=True, exist_ok=True)
    symbols_path.write_text(
        json.dumps([{"name": "MyClass", "kind": "class", "file": "core.py", "signature": None}]),
        encoding="utf-8",
    )

    captured: list[str] = []

    def _capture(prompt: str, system: str = "") -> str:
        captured.append(system)
        return "ok"

    with patch("rekipedia.orchestrator.run_ask.LLMClient") as MockAskClient:
        mock = MagicMock()
        mock.call.side_effect = _capture
        MockAskClient.return_value = mock

        run_ask("Tell me about MyClass", repo, output_dir, LLMConfig())

    assert captured
    assert "MyClass" in captured[0]
