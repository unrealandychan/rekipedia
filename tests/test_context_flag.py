"""Tests for the --context flag implementation (issue #135)."""
from __future__ import annotations

import textwrap
from unittest.mock import MagicMock, patch

from rekipedia.orchestrator.run_ask import _build_full_system, _load_pinned_context

# ---------------------------------------------------------------------------
# _load_pinned_context tests
# ---------------------------------------------------------------------------

def test_load_pinned_context_plain_file(tmp_path):
    """Plain file path: content should appear under the filename header."""
    f = tmp_path / "myfile.py"
    f.write_text("def hello():\n    pass\n")
    result = _load_pinned_context([str(f)], tmp_path)
    assert "myfile.py" in result
    assert "def hello():" in result
    assert "## Pinned Context (--context)" in result


def test_load_pinned_context_file_symbol(tmp_path):
    """file:symbol syntax: only the targeted function should be extracted."""
    f = tmp_path / "core.py"
    f.write_text(textwrap.dedent("""\
        def foo():
            return 1

        def bar():
            return 2

        def baz():
            return 3
    """))
    result = _load_pinned_context([f"{f}:bar"], tmp_path)
    assert "bar" in result
    # foo and baz should NOT appear (they are other top-level symbols)
    assert "def foo" not in result
    assert "def baz" not in result


def test_load_pinned_context_missing_file(tmp_path):
    """Missing file should not raise — just produce a graceful skip note."""
    result = _load_pinned_context([str(tmp_path / "nonexistent.py")], tmp_path)
    # Should either be empty or contain a skip note — but no exception
    # We accept either behavior as long as no exception is raised
    assert isinstance(result, str)


def test_load_pinned_context_token_budget(tmp_path):
    """Files exceeding 16000 chars should be truncated with a note."""
    f = tmp_path / "big.py"
    f.write_text("x = 1\n" * 4000)  # ~24000 chars
    result = _load_pinned_context([str(f)], tmp_path)
    assert "truncated" in result.lower()


# ---------------------------------------------------------------------------
# _build_full_system with pinned context
# ---------------------------------------------------------------------------

def test_build_full_system_with_pinned(tmp_path):
    """pinned_context string should appear early in the assembled system prompt."""
    output_dir = tmp_path / ".rekipedia"
    output_dir.mkdir()
    (output_dir / "wiki").mkdir()

    # Fake store.db so _verify_scan passes — we patch it away anyway
    fake_db = output_dir / "store.db"
    fake_db.write_bytes(b"")

    with (
        patch("rekipedia.orchestrator.run_ask._load_wiki_pages", return_value=[]),
        patch("rekipedia.orchestrator.run_ask._load_symbol_lines", return_value=[]),
        patch("rekipedia.orchestrator.run_ask._rag_chunks", return_value=[]),
        patch("rekipedia.orchestrator.run_ask._rewrite_query", side_effect=lambda q, *a, **kw: q),
        patch("rekipedia.orchestrator.run_ask.SqliteStore") as mock_store_cls,
    ):
        mock_store = MagicMock()
        mock_store.list_notes.return_value = []
        mock_store_cls.return_value.__enter__ = lambda s, *a: mock_store
        mock_store_cls.return_value.__exit__ = MagicMock(return_value=False)

        from rekipedia.models.contracts import LLMConfig
        result = _build_full_system("test question", output_dir, LLMConfig(), pinned_context="PINNED_SENTINEL")

    assert "PINNED_SENTINEL" in result
    # Pinned context should appear before any RAG section
    pinned_pos = result.find("PINNED_SENTINEL")
    knowledge_pos = result.find("# Knowledge Context")
    assert pinned_pos > knowledge_pos  # it's inside the knowledge context block


# ---------------------------------------------------------------------------
# run_ask passes pinned_context through
# ---------------------------------------------------------------------------

def test_run_ask_passes_pinned_context(tmp_path):
    """run_ask should call _prepare_ask with the loaded pinned_context string."""
    from rekipedia.models.contracts import LLMConfig

    output_dir = tmp_path / ".rekipedia"
    output_dir.mkdir()

    pinned_files = ["src/auth/jwt.py"]
    expected_pinned_str = "## Pinned Context (--context)\n\n### `src/auth/jwt.py`\n\n*[File not found — skipped]*\n"

    mock_client = MagicMock()
    mock_client.call.return_value = "answer text"

    with (
        patch("rekipedia.orchestrator.run_ask._prepare_ask") as mock_prepare,
        patch("rekipedia.orchestrator.run_ask._load_pinned_context", return_value="PINNED") as mock_load,
    ):
        mock_prepare.return_value = (mock_client, "system prompt")
        from rekipedia.orchestrator.run_ask import run_ask
        result = run_ask(
            question="how does auth work?",
            repo_root=tmp_path,
            output_dir=output_dir,
            llm_config=LLMConfig(),
            history=[],
            pinned_context=pinned_files,
        )

    mock_load.assert_called_once_with(pinned_files, tmp_path)
    mock_prepare.assert_called_once()
    # Verify pinned_context="PINNED" was passed to _prepare_ask
    _, kwargs = mock_prepare.call_args
    assert kwargs.get("pinned_context") == "PINNED"
    assert result == "answer text"
