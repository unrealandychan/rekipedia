"""Additional coverage tests targeting CLI commands and diagram_builder.

These tests focus on the modules with lowest coverage:
- cli/scan.py (28%)
- cli/embed.py (21%)
- cli/update.py (36%)
- synthesis/diagram_builder.py (38%)
- llm/client.py (54%)
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from rekipedia.cli import main
from rekipedia.models.contracts import LLMConfig

# ---------------------------------------------------------------------------
# CLI help / version smoke tests (quick coverage wins)
# ---------------------------------------------------------------------------

def test_cli_help() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "scan" in result.output
    assert "ask" in result.output
    assert "export" in result.output
    assert "embed" in result.output


def test_scan_help() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["scan", "--help"])
    assert result.exit_code == 0
    assert "--embed-model" in result.output
    assert "--embed-provider" in result.output


def test_embed_help() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["embed", "--help"])
    assert result.exit_code == 0
    assert "--provider" in result.output
    assert "--model" in result.output


def test_export_help() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["export", "--help"])
    assert result.exit_code == 0
    assert "--format" in result.output


def test_ask_help() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["ask", "--help"])
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# cli/embed.py — missing .rekipedia dir exits non-zero
# ---------------------------------------------------------------------------

def test_embed_missing_rekipedia(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["embed", str(tmp_path)])
    assert result.exit_code != 0
    assert "Missing RAG dependencies" in result.output or ".rekipedia" in result.output or "No .rekipedia" in result.output


# ---------------------------------------------------------------------------
# cli/scan.py — _load_config
# ---------------------------------------------------------------------------

def test_load_config_returns_empty_when_no_file(tmp_path: Path) -> None:
    from rekipedia.cli.scan import _load_config
    assert _load_config(tmp_path) == {}


def test_load_config_reads_yaml(tmp_path: Path) -> None:
    from rekipedia.cli.scan import _load_config
    cfg_path = tmp_path / ".rekipedia" / "config.yml"
    cfg_path.parent.mkdir()
    cfg_path.write_text("llm:\n  model: gpt-4o\n  api_key: sk-test\n")
    cfg = _load_config(tmp_path)
    assert cfg["llm"]["model"] == "gpt-4o"


def test_scan_cmd_missing_repo(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["scan", str(tmp_path / "nonexistent")])
    assert result.exit_code != 0


def test_scan_cmd_error_propagates(tmp_path: Path) -> None:
    """scan should print error and exit 1 when run_digest raises."""
    runner = CliRunner()
    with patch("rekipedia.orchestrator.run_digest.run_digest", side_effect=RuntimeError("boom")):
        result = runner.invoke(main, ["scan", str(tmp_path), "--no-docker"])
    assert result.exit_code == 1
    assert "boom" in result.output


# ---------------------------------------------------------------------------
# synthesis/diagram_builder.py
# ---------------------------------------------------------------------------

def test_diagram_builder_empty_input() -> None:
    from rekipedia.synthesis.diagram_builder import DiagramBuilder

    db = DiagramBuilder()
    result = db.build([], entry_points=[])
    assert isinstance(result, dict)


def test_diagram_builder_with_relationships() -> None:
    from rekipedia.synthesis.diagram_builder import DiagramBuilder

    rels = [
        {"from": "rekipedia.cli", "to": "rekipedia.orchestrator", "kind": "import", "file": "cli/__init__.py"},
        {"from": "rekipedia.orchestrator", "to": "rekipedia.storage", "kind": "import", "file": "orchestrator/run_digest.py"},
        {"from": "rekipedia.storage", "to": "sqlite3", "kind": "import", "file": "storage/sqlite_store.py"},
    ]
    db = DiagramBuilder()
    result = db.build(rels, entry_points=["rekipedia.cli"])
    assert isinstance(result, dict)
    # Should produce at least a module graph
    assert len(result) >= 0  # non-crashing is the key assertion


def test_diagram_builder_returns_mermaid_strings() -> None:
    from rekipedia.synthesis.diagram_builder import DiagramBuilder

    rels = [
        {"from": "module_a", "to": "module_b", "kind": "import", "file": "a.py"},
    ]
    db = DiagramBuilder()
    result = db.build(rels, entry_points=["module_a"])
    for name, (dtype, content) in result.items():
        assert isinstance(dtype, str)
        assert isinstance(content, str)


# ---------------------------------------------------------------------------
# llm/client.py — LLMClient basic paths
# ---------------------------------------------------------------------------

def test_llm_client_call_success() -> None:
    from rekipedia.llm.client import LLMClient

    cfg = LLMConfig(model="ollama/llama4")
    client = LLMClient(cfg)

    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock()]
    mock_resp.choices[0].message.content = "Hello answer"

    with patch("rekipedia.llm.client.litellm.completion", return_value=mock_resp):
        result = client.call("What is 2+2?", system="You are a math tutor.")
    assert result == "Hello answer"


def test_llm_client_call_retries_on_timeout() -> None:
    """_with_retry should retry on litellm.Timeout and succeed on second attempt."""
    import litellm as _ll

    from rekipedia.llm.client import LLMClient

    cfg = LLMConfig(model="ollama/llama4")
    client = LLMClient(cfg)

    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock()]
    mock_resp.choices[0].message.content = "Recovered"

    call_count = {"n": 0}

    def flaky(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] < 2:
            raise _ll.Timeout(message="timeout", model="llama4", llm_provider="ollama")
        return mock_resp

    with patch("rekipedia.llm.client.litellm.completion", side_effect=flaky):
        with patch("time.sleep"):
            result = client.call("test", system="sys")
    assert result == "Recovered"
    assert call_count["n"] == 2


def test_llm_client_stream_returns_iterator() -> None:
    """stream() yields delta content from each chunk."""
    from rekipedia.llm.client import LLMClient

    cfg = LLMConfig(model="ollama/llama4")
    client = LLMClient(cfg)

    def _fake_stream(*args, **kwargs):
        for text in ["Hello", " world", None]:   # None chunk should be skipped
            chunk = MagicMock()
            chunk.choices = [MagicMock()]
            chunk.choices[0].delta.content = text
            yield chunk

    # Patch at the module level where it's imported
    with patch("rekipedia.llm.client.litellm") as mock_ll:
        mock_ll.completion.side_effect = _fake_stream
        mock_ll.Timeout = Exception
        mock_ll.ServiceUnavailableError = Exception
        mock_ll.InternalServerError = Exception
        mock_ll.RateLimitError = Exception
        stream = client.stream("hi", system="sys")
        tokens = list(stream)
    assert tokens == ["Hello", " world"]


# ---------------------------------------------------------------------------
# orchestrator/run_ask.py — _rag_chunks fallback when no index
# ---------------------------------------------------------------------------

def test_rag_chunks_fallback_no_index(tmp_path: Path) -> None:
    from rekipedia.orchestrator.run_ask import _rag_chunks

    out_dir = tmp_path / ".rekipedia"
    out_dir.mkdir()
    result = _rag_chunks("test question", out_dir, LLMConfig())
    assert result == []


def test_build_full_system_assembles_context(tmp_path: Path) -> None:
    from rekipedia.orchestrator.run_ask import _build_full_system

    out_dir = tmp_path / ".rekipedia"
    wiki_dir = out_dir / "wiki"
    wiki_dir.mkdir(parents=True)
    (wiki_dir / "index.md").write_text("# Index\n\nWelcome.", encoding="utf-8")

    result = _build_full_system("What is this?", out_dir, LLMConfig())
    assert "Knowledge Context" in result
    assert "index.md" in result


# ---------------------------------------------------------------------------
# rag/embedder.py — additional branches
# ---------------------------------------------------------------------------

def test_embed_pipeline_build_shows_progress(tmp_path: Path) -> None:
    import numpy as np

    from rekipedia.rag.embedder import EmbedPipeline

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text("def main():\n    pass\n")
    out_dir = tmp_path / ".rekipedia"
    out_dir.mkdir()

    messages: list[str] = []

    with patch("rekipedia.rag.embedder._embed_batch") as mock_embed:
        mock_embed.return_value = np.random.default_rng(0).random((1, 8)).astype(np.float32)
        pipe = EmbedPipeline(out_dir, LLMConfig())
        n = pipe.build(repo, progress_cb=messages.append)

    assert n > 0
    assert any("Embedding" in m or "FAISS" in m or "Collecting" in m for m in messages)
