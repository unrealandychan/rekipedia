"""Tests for Issue #94: Agentic ReAct ask loop."""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from close_wiki.orchestrator.agentic_ask import (
    TOOL_SCHEMAS,
    _ToolExecutor,
    agentic_ask,
)


# ---------------------------------------------------------------------------
# TOOL_SCHEMAS structure
# ---------------------------------------------------------------------------

def test_tool_schemas_structure():
    names = {t["function"]["name"] for t in TOOL_SCHEMAS}
    assert {"search_code", "get_symbol", "get_page", "get_relationships"} <= names
    for schema in TOOL_SCHEMAS:
        assert schema["type"] == "function"
        fn = schema["function"]
        assert "name" in fn
        assert "description" in fn
        assert "parameters" in fn


# ---------------------------------------------------------------------------
# _ToolExecutor dispatch tests
# ---------------------------------------------------------------------------

@pytest.fixture()
def wiki_dir(tmp_path: Path) -> Path:
    d = tmp_path / "wiki"
    d.mkdir()
    (d / "architecture.md").write_text("# Architecture\nHigh level overview.")
    return tmp_path


@pytest.fixture()
def mock_db(tmp_path: Path) -> Path:
    from close_wiki.storage.sqlite_store import SqliteStore
    db = tmp_path / "store.db"
    run_id = "run-test"
    with SqliteStore(db) as store:
        store.upsert_run(run_id, str(tmp_path), status="success")
    return db


def make_executor(wiki_dir, mock_db, llm_config=None):
    from close_wiki.models.contracts import LLMConfig
    cfg = llm_config or LLMConfig(model="ollama/llama4")
    return _ToolExecutor(
        output_dir=wiki_dir,
        llm_config=cfg,
        db_path=mock_db,
        run_id="run-test",
    )


def test_executor_search_code_returns_string(wiki_dir, mock_db):
    """search_code should return a non-empty string (even if no embeddings)."""
    ex = make_executor(wiki_dir, mock_db)
    result = ex.execute("search_code", {"query": "architecture"})
    assert isinstance(result, str)


def test_executor_get_symbol_calls_store(wiki_dir, mock_db):
    ex = make_executor(wiki_dir, mock_db)
    result = ex.execute("get_symbol", {"name": "nonexistent_fn"})
    assert "nonexistent_fn" in result or "No symbol" in result


def test_executor_get_page_found(wiki_dir, mock_db):
    ex = make_executor(wiki_dir, mock_db)
    result = ex.execute("get_page", {"slug": "architecture"})
    assert "Architecture" in result


def test_executor_get_page_not_found(wiki_dir, mock_db):
    ex = make_executor(wiki_dir, mock_db)
    result = ex.execute("get_page", {"slug": "no_such_page_xyz"})
    assert "No wiki page" in result


def test_executor_get_relationships_empty(wiki_dir, mock_db):
    ex = make_executor(wiki_dir, mock_db)
    result = ex.execute("get_relationships", {"symbol": "nonexistent"})
    assert isinstance(result, str)


def test_executor_formats_symbol_and_relationship_rows(wiki_dir, mock_db):
    from close_wiki.storage.sqlite_store import SqliteStore

    with SqliteStore(mock_db) as store:
        store.upsert_symbols(
            "run-test",
            [
                {
                    "name": "main",
                    "kind": "function",
                    "file": "src/main.py",
                    "line_start": 12,
                    "line_end": 20,
                    "signature": "def main() -> None",
                    "docstring": "",
                }
            ],
        )
        store.upsert_relationships(
            "run-test",
            [{"from_": "main", "to": "App.run", "kind": "calls", "file": "src/main.py"}],
        )

    ex = make_executor(wiki_dir, mock_db)
    symbol_result = ex.execute("get_symbol", {"name": "main"})
    relationships_result = ex.execute("get_relationships", {"symbol": "main"})

    assert "**main** (function) — `src/main.py` line 12" in symbol_result
    assert "Signature: `def main() -> None`" in symbol_result
    assert "- **main** → **App.run** (calls)" in relationships_result


def test_executor_unknown_tool(wiki_dir, mock_db):
    ex = make_executor(wiki_dir, mock_db)
    result = ex.execute("nonexistent_tool", {})
    assert "unknown" in result.lower() or "Unknown" in result


# ---------------------------------------------------------------------------
# agentic_ask: high-level smoke tests (LLM mocked)
# ---------------------------------------------------------------------------

def _make_db(tmp_path: Path) -> Path:
    from close_wiki.storage.sqlite_store import SqliteStore
    db_path = tmp_path / ".close-wiki" / "store.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    run_id = str(uuid.uuid4())
    with SqliteStore(db_path) as store:
        store.upsert_run(run_id, str(tmp_path), status="success")
    return db_path


def test_agentic_ask_immediate_answer(tmp_path: Path):
    """LLM answers on first call with no tool calls → return directly."""
    from close_wiki.models.contracts import LLMConfig
    _make_db(tmp_path)
    cfg = LLMConfig(model="ollama/llama4")

    with patch("close_wiki.orchestrator.agentic_ask.LLMClient") as MockClient:
        inst = MagicMock()
        MockClient.return_value = inst
        inst.call_with_tools.return_value = {
            "content": "Direct answer, no tools needed.",
            "tool_calls": [],
        }
        answer = agentic_ask("What does this codebase do?", tmp_path, tmp_path / ".close-wiki", cfg)

    assert "Direct answer" in answer
    assert inst.call_with_tools.call_count == 1


def test_agentic_ask_one_tool_then_answer(tmp_path: Path):
    """LLM calls get_symbol once, then returns answer."""
    from close_wiki.models.contracts import LLMConfig
    _make_db(tmp_path)
    cfg = LLMConfig(model="ollama/llama4")

    tool_call = {
        "id": "tc_1",
        "type": "function",
        "function": {"name": "get_symbol", "arguments": json.dumps({"name": "main"})},
    }

    with patch("close_wiki.orchestrator.agentic_ask.LLMClient") as MockClient:
        inst = MagicMock()
        MockClient.return_value = inst
        inst.call_with_tools.side_effect = [
            {"content": "", "tool_calls": [tool_call]},
            {"content": "The main function is the entry point.", "tool_calls": []},
        ]
        answer = agentic_ask("Where is main?", tmp_path, tmp_path / ".close-wiki", cfg)

    assert "main" in answer.lower() or "entry" in answer.lower()
    assert inst.call_with_tools.call_count == 2


def test_agentic_ask_no_db_raises(tmp_path: Path):
    """agentic_ask raises if no knowledge store exists."""
    from close_wiki.models.contracts import LLMConfig
    cfg = LLMConfig(model="ollama/llama4")
    with pytest.raises(Exception):
        agentic_ask("Any question", tmp_path, tmp_path / ".close-wiki", cfg)
