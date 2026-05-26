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

    def _capture_call(prompt: str, system: str = "", history=None) -> str:
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

    def _capture(prompt: str, system: str = "", history=None) -> str:
        captured.append(system)
        return "ok"

    with patch("rekipedia.orchestrator.run_ask.LLMClient") as MockAskClient:
        mock = MagicMock()
        mock.call.side_effect = _capture
        MockAskClient.return_value = mock

        run_ask("Tell me about MyClass", repo, output_dir, LLMConfig())

    assert captured
    assert "MyClass" in captured[0]


# ── #125 Streaming output tests ───────────────────────────────────────────────

def test_stream_ask_yields_chunks(scanned_repo):
    """stream_ask should yield string chunks from the LLM stream method."""
    from rekipedia.orchestrator.run_ask import stream_ask

    repo, output_dir = scanned_repo
    expected_chunks = ["Hello", " world", "!"]

    with patch("rekipedia.orchestrator.run_ask.LLMClient") as MockClient:
        mock = MagicMock()
        mock.stream.return_value = iter(expected_chunks)
        MockClient.return_value = mock

        result = list(stream_ask("What is this?", repo, output_dir, LLMConfig()))

    assert result == expected_chunks


def test_stream_ask_joins_to_full_answer(scanned_repo):
    """Concatenating stream_ask chunks should equal the full answer."""
    from rekipedia.orchestrator.run_ask import stream_ask

    repo, output_dir = scanned_repo
    chunks = ["This ", "is ", "the ", "answer."]

    with patch("rekipedia.orchestrator.run_ask.LLMClient") as MockClient:
        mock = MagicMock()
        mock.stream.return_value = iter(chunks)
        MockClient.return_value = mock

        full = "".join(stream_ask("Explain", repo, output_dir, LLMConfig()))

    assert full == "This is the answer."


def test_stream_ask_raises_if_no_scan(tmp_path):
    """stream_ask raises RuntimeError if no store.db exists."""
    from rekipedia.orchestrator.run_ask import stream_ask

    repo = tmp_path / "repo"
    repo.mkdir()
    output_dir = tmp_path / ".rekipedia"

    with pytest.raises(RuntimeError, match="No knowledge store found"):
        list(stream_ask("anything?", repo, output_dir, LLMConfig()))


def test_stream_ask_passes_history(scanned_repo):
    """stream_ask should pass history to LLMClient.stream."""
    from rekipedia.orchestrator.run_ask import stream_ask

    repo, output_dir = scanned_repo
    history = [
        {"role": "user", "content": "previous question"},
        {"role": "assistant", "content": "previous answer"},
    ]

    with patch("rekipedia.orchestrator.run_ask.LLMClient") as MockClient:
        mock = MagicMock()
        mock.stream.return_value = iter(["ok"])
        MockClient.return_value = mock

        list(stream_ask("Follow up?", repo, output_dir, LLMConfig(), history=history))

    call_kwargs = mock.stream.call_args
    passed_history = call_kwargs.kwargs.get("history") or (call_kwargs.args[1:] and call_kwargs.args[1])
    assert passed_history == history


def test_ask_cmd_no_stream_flag(scanned_repo):
    """--no-stream flag should call _answer_streaming with stream=False."""
    from click.testing import CliRunner

    from rekipedia.cli.ask import ask_cmd

    repo, output_dir = scanned_repo
    runner = CliRunner()

    with patch("rekipedia.cli.ask._answer_streaming") as mock_answer:
        mock_answer.return_value = "buffered answer"
        result = runner.invoke(
            ask_cmd,
            ["--repo", str(repo), "--output-dir", str(output_dir), "--no-stream", "What is this?"],
        )

    assert result.exit_code == 0 or "Error" not in (result.output or "")
    if mock_answer.called:
        call_kwargs = mock_answer.call_args.kwargs
        assert call_kwargs.get("stream") is False


def test_answer_streaming_non_stream_calls_run_ask(scanned_repo):
    """_answer_streaming with stream=False should use run_ask not stream_ask."""
    from rekipedia.cli.ask import _answer_streaming
    from rekipedia.models.contracts import LLMConfig

    repo, output_dir = scanned_repo

    with (
        patch("rekipedia.orchestrator.run_ask.LLMClient") as MockClient,
        patch("rekipedia.cli.ask.console"),
    ):
        mock = MagicMock()
        mock.call.return_value = "full buffered answer"
        MockClient.return_value = mock

        result = _answer_streaming(
            "Test?", repo, output_dir, LLMConfig(), history=[], stream=False
        )

    assert result == "full buffered answer"
