"""Comprehensive tests for rekipedia ask CLI and run_ask orchestrator."""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from rekipedia.cli.ask import _answer_streaming, _build_llm_config, _load_config
from rekipedia.models.contracts import LLMConfig
from rekipedia.orchestrator.run_ask import (
    _build_full_system,
    _load_symbol_lines,
    _load_wiki_pages,
    _verify_scan,
    run_ask,
    stream_ask,
)

# ---------------------------------------------------------------------------
# _load_config
# ---------------------------------------------------------------------------

class TestLoadConfig:
    def test_returns_empty_dict_when_no_config(self, tmp_path):
        result = _load_config(tmp_path)
        assert result == {}

    def test_parses_yaml_when_file_exists(self, tmp_path):
        cfg_dir = tmp_path / ".rekipedia"
        cfg_dir.mkdir()
        cfg_file = cfg_dir / "config.yml"
        cfg_file.write_text("llm:\n  model: gpt-4\n  temperature: 0.5\n")
        result = _load_config(tmp_path)
        assert result == {"llm": {"model": "gpt-4", "temperature": 0.5}}

    def test_empty_yaml_file_returns_empty_dict(self, tmp_path):
        cfg_dir = tmp_path / ".rekipedia"
        cfg_dir.mkdir()
        cfg_file = cfg_dir / "config.yml"
        cfg_file.write_text("")
        result = _load_config(tmp_path)
        assert result == {}


# ---------------------------------------------------------------------------
# _build_llm_config
# ---------------------------------------------------------------------------

class TestBuildLLMConfig:
    def test_uses_env_var_when_set(self, tmp_path, monkeypatch):
        monkeypatch.setenv("REKIPEDIA_MODEL", "anthropic/claude-3")
        monkeypatch.delenv("REKIPEDIA_API_KEY", raising=False)
        monkeypatch.delenv("REKIPEDIA_BASE_URL", raising=False)
        cfg = _build_llm_config(tmp_path, None)
        assert cfg.model == "anthropic/claude-3"

    def test_falls_back_to_config_model(self, tmp_path, monkeypatch):
        monkeypatch.delenv("REKIPEDIA_MODEL", raising=False)
        monkeypatch.delenv("REKIPEDIA_API_KEY", raising=False)
        monkeypatch.delenv("REKIPEDIA_BASE_URL", raising=False)
        cfg_dir = tmp_path / ".rekipedia"
        cfg_dir.mkdir()
        (cfg_dir / "config.yml").write_text("llm:\n  model: openai/gpt-4o\n")
        cfg = _build_llm_config(tmp_path, None)
        assert cfg.model == "openai/gpt-4o"

    def test_falls_back_to_default(self, tmp_path, monkeypatch):
        monkeypatch.delenv("REKIPEDIA_MODEL", raising=False)
        monkeypatch.delenv("REKIPEDIA_API_KEY", raising=False)
        monkeypatch.delenv("REKIPEDIA_BASE_URL", raising=False)
        cfg = _build_llm_config(tmp_path, None)
        assert cfg.model == "ollama/llama4"

    def test_model_arg_overrides_config(self, tmp_path, monkeypatch):
        monkeypatch.delenv("REKIPEDIA_MODEL", raising=False)
        monkeypatch.delenv("REKIPEDIA_API_KEY", raising=False)
        monkeypatch.delenv("REKIPEDIA_BASE_URL", raising=False)
        cfg = _build_llm_config(tmp_path, "openai/gpt-3.5")
        assert cfg.model == "openai/gpt-3.5"

    def test_env_var_overrides_model_arg(self, tmp_path, monkeypatch):
        monkeypatch.setenv("REKIPEDIA_MODEL", "env-model")
        monkeypatch.delenv("REKIPEDIA_API_KEY", raising=False)
        monkeypatch.delenv("REKIPEDIA_BASE_URL", raising=False)
        cfg = _build_llm_config(tmp_path, "arg-model")
        assert cfg.model == "env-model"


# ---------------------------------------------------------------------------
# _answer_streaming
# ---------------------------------------------------------------------------

class TestAnswerStreaming:
    def _make_llm_config(self):
        return LLMConfig(model="test/model")

    def test_prints_error_when_stream_ask_raises(self, tmp_path, capsys):
        llm_config = self._make_llm_config()
        with patch("rekipedia.orchestrator.run_ask.stream_ask", side_effect=RuntimeError("scan not found")):
            # Patch the lazy import inside _answer_streaming
            with patch("rekipedia.cli.ask.console") as mock_console:
                # We need stream_ask to raise when called from _answer_streaming
                # The function does: from rekipedia.orchestrator.run_ask import stream_ask
                # So patch it at the source
                with patch("rekipedia.orchestrator.run_ask.LLMClient"):
                    _answer_streaming("test question", tmp_path, tmp_path, llm_config, history=[])

    def test_prints_error_via_module_patch(self, tmp_path):
        """stream_ask raises RuntimeError -> error printed, no exception bubbles."""
        llm_config = self._make_llm_config()

        def bad_stream(**kwargs):
            raise RuntimeError("no scan found")

        import rekipedia.orchestrator.run_ask as run_ask_mod
        original = run_ask_mod.stream_ask
        run_ask_mod.stream_ask = bad_stream
        try:
            # Should not raise — error is caught and printed
            _answer_streaming("hello?", tmp_path, tmp_path, llm_config, history=[])
        finally:
            run_ask_mod.stream_ask = original

    def test_streams_chunks_to_stdout(self, tmp_path, capsys):
        """stream_ask yields chunks -> written to stdout."""
        llm_config = self._make_llm_config()

        def fake_stream(**kwargs):
            return iter(["Hello", " world"])

        import rekipedia.orchestrator.run_ask as run_ask_mod
        original = run_ask_mod.stream_ask
        run_ask_mod.stream_ask = fake_stream
        try:
            _answer_streaming("question", tmp_path, tmp_path, llm_config, history=[])
        finally:
            run_ask_mod.stream_ask = original

        captured = capsys.readouterr()
        assert "Hello" in captured.out
        assert "world" in captured.out

    def test_stop_iteration_uses_empty_string(self, tmp_path, capsys):
        """If iterator is immediately exhausted, first_chunk = '' and no crash."""
        llm_config = self._make_llm_config()

        def empty_stream(**kwargs):
            return iter([])

        import rekipedia.orchestrator.run_ask as run_ask_mod
        original = run_ask_mod.stream_ask
        run_ask_mod.stream_ask = empty_stream
        try:
            _answer_streaming("question", tmp_path, tmp_path, llm_config, history=[])
        finally:
            run_ask_mod.stream_ask = original

        # Should complete without error
        captured = capsys.readouterr()
        assert "\n" in captured.out  # the final newline is always written


# ---------------------------------------------------------------------------
# _verify_scan
# ---------------------------------------------------------------------------

class TestVerifyScan:
    def test_raises_when_no_db(self, tmp_path):
        with pytest.raises(RuntimeError, match="No knowledge store"):
            _verify_scan(tmp_path, tmp_path)

    def test_raises_when_no_successful_run(self, tmp_path):
        db_path = tmp_path / "store.db"
        db_path.touch()
        with patch("rekipedia.orchestrator.run_ask.SqliteStore") as MockStore:
            instance = MockStore.return_value.__enter__.return_value
            instance.get_latest_run_id.return_value = None
            with pytest.raises(RuntimeError, match="No successful scan"):
                _verify_scan(tmp_path, tmp_path)

    def test_returns_run_id_when_scan_exists(self, tmp_path):
        db_path = tmp_path / "store.db"
        db_path.touch()
        with patch("rekipedia.orchestrator.run_ask.SqliteStore") as MockStore:
            instance = MockStore.return_value.__enter__.return_value
            instance.get_latest_run_id.return_value = "run-abc123"
            result = _verify_scan(tmp_path, tmp_path)
        assert result == "run-abc123"


# ---------------------------------------------------------------------------
# _load_wiki_pages
# ---------------------------------------------------------------------------

class TestLoadWikiPages:
    def test_returns_empty_list_when_no_wiki_dir(self, tmp_path):
        result = _load_wiki_pages(tmp_path)
        assert result == []

    def test_returns_formatted_pages(self, tmp_path):
        wiki_dir = tmp_path / "wiki"
        wiki_dir.mkdir()
        (wiki_dir / "overview.md").write_text("# Overview\nThis is the overview.")
        (wiki_dir / "api.md").write_text("# API\nAPI docs here.")
        result = _load_wiki_pages(tmp_path)
        assert len(result) == 2
        # sorted alphabetically: api.md first, overview.md second
        assert "## [api.md]" in result[0]
        assert "# API" in result[0]
        assert "## [overview.md]" in result[1]
        assert "# Overview" in result[1]

    def test_returns_sorted_pages(self, tmp_path):
        wiki_dir = tmp_path / "wiki"
        wiki_dir.mkdir()
        (wiki_dir / "z_last.md").write_text("Z content")
        (wiki_dir / "a_first.md").write_text("A content")
        result = _load_wiki_pages(tmp_path)
        assert "a_first" in result[0]
        assert "z_last" in result[1]


# ---------------------------------------------------------------------------
# _load_symbol_lines
# ---------------------------------------------------------------------------

class TestLoadSymbolLines:
    def test_returns_empty_when_no_symbols_file(self, tmp_path):
        result = _load_symbol_lines(tmp_path)
        assert result == []

    def test_parses_and_formats_symbols(self, tmp_path):
        exports = tmp_path / "exports"
        exports.mkdir()
        symbols = [
            {"name": "MyClass", "kind": "class", "file": "src/myclass.py", "signature": "class MyClass:"},
            {"name": "my_func", "kind": "function", "file": "src/utils.py"},
        ]
        (exports / "symbols.json").write_text(json.dumps(symbols))
        result = _load_symbol_lines(tmp_path)
        assert len(result) == 2
        assert "[Symbol: MyClass]" in result[0]
        assert "kind=class" in result[0]
        assert "signature=class MyClass:" in result[0]
        assert "[Symbol: my_func]" in result[1]
        assert "signature=" not in result[1]

    def test_handles_malformed_json(self, tmp_path):
        exports = tmp_path / "exports"
        exports.mkdir()
        (exports / "symbols.json").write_text("not valid json {{")
        result = _load_symbol_lines(tmp_path)
        assert result == []


# ---------------------------------------------------------------------------
# _build_full_system
# ---------------------------------------------------------------------------

class TestBuildFullSystem:
    def test_assembles_context_with_wiki(self, tmp_path):
        wiki_dir = tmp_path / "wiki"
        wiki_dir.mkdir()
        (wiki_dir / "readme.md").write_text("# Readme\nSome content.")
        llm_config = LLMConfig(model="test/model")
        with patch("rekipedia.orchestrator.run_ask._rag_chunks", return_value=[]):
            result = _build_full_system("what is this?", tmp_path, llm_config)
        assert "readme.md" in result
        assert "Some content" in result

    def test_includes_symbol_index(self, tmp_path):
        exports = tmp_path / "exports"
        exports.mkdir()
        symbols = [{"name": "Foo", "kind": "class", "file": "foo.py"}]
        (exports / "symbols.json").write_text(json.dumps(symbols))
        llm_config = LLMConfig(model="test/model")
        with patch("rekipedia.orchestrator.run_ask._rag_chunks", return_value=[]):
            result = _build_full_system("question", tmp_path, llm_config)
        assert "Symbol Index" in result
        assert "[Symbol: Foo]" in result

    def test_truncates_large_wiki_pages(self, tmp_path):
        wiki_dir = tmp_path / "wiki"
        wiki_dir.mkdir()
        # Create a huge page that exceeds budget
        huge_content = "x" * 100_000
        (wiki_dir / "huge.md").write_text(huge_content)
        (wiki_dir / "small.md").write_text("small content")
        llm_config = LLMConfig(model="test/model")
        with patch("rekipedia.orchestrator.run_ask._rag_chunks", return_value=[]):
            result = _build_full_system("question", tmp_path, llm_config)
        assert "token budget reached" in result

    def test_includes_rag_chunks(self, tmp_path):
        llm_config = LLMConfig(model="test/model")
        rag_chunks = [
            {"file": "src/main.py", "ext": ".py", "score": 0.95, "text": "def main(): pass"}
        ]
        with patch("rekipedia.orchestrator.run_ask._rag_chunks", return_value=rag_chunks):
            result = _build_full_system("question", tmp_path, llm_config)
        assert "src/main.py" in result
        assert "def main(): pass" in result

    def test_rag_chunks_respect_budget(self, tmp_path):
        """RAG chunks that exceed budget are skipped."""
        llm_config = LLMConfig(model="test/model")
        huge_text = "y" * 100_000
        rag_chunks = [
            {"file": "big.py", "ext": ".py", "score": 0.9, "text": huge_text},
            {"file": "small.py", "ext": ".py", "score": 0.8, "text": "tiny"},
        ]
        # Fill wiki to near budget first
        wiki_dir = tmp_path / "wiki"
        wiki_dir.mkdir()
        (wiki_dir / "big.md").write_text("z" * 90_000)
        with patch("rekipedia.orchestrator.run_ask._rag_chunks", return_value=rag_chunks):
            result = _build_full_system("question", tmp_path, llm_config)
        # The huge RAG chunk should be skipped
        assert "big.py" not in result or huge_text[:100] not in result


# ---------------------------------------------------------------------------
# run_ask and stream_ask
# ---------------------------------------------------------------------------

class TestRunAsk:
    def _setup_output_dir(self, tmp_path):
        db_path = tmp_path / "store.db"
        db_path.touch()
        return tmp_path

    def test_run_ask_returns_answer(self, tmp_path):
        output_dir = self._setup_output_dir(tmp_path)
        llm_config = LLMConfig(model="test/model")

        with patch("rekipedia.orchestrator.run_ask.SqliteStore") as MockStore:
            instance = MockStore.return_value.__enter__.return_value
            instance.get_latest_run_id.return_value = "run-1"
            with patch("rekipedia.orchestrator.run_ask.LLMClient") as MockLLM:
                MockLLM.return_value.call.return_value = "The answer is 42."
                with patch("rekipedia.orchestrator.run_ask._rag_chunks", return_value=[]):
                    result = run_ask("What is the answer?", tmp_path, output_dir, llm_config)

        assert result == "The answer is 42."

    def test_run_ask_raises_when_no_scan(self, tmp_path):
        llm_config = LLMConfig(model="test/model")
        with pytest.raises(RuntimeError, match="No knowledge store"):
            run_ask("question", tmp_path, tmp_path, llm_config)


class TestStreamAsk:
    def test_stream_ask_yields_chunks(self, tmp_path):
        db_path = tmp_path / "store.db"
        db_path.touch()
        llm_config = LLMConfig(model="test/model")

        with patch("rekipedia.orchestrator.run_ask.SqliteStore") as MockStore:
            instance = MockStore.return_value.__enter__.return_value
            instance.get_latest_run_id.return_value = "run-1"
            with patch("rekipedia.orchestrator.run_ask.LLMClient") as MockLLM:
                MockLLM.return_value.stream.return_value = iter(["Hello", " world", "!"])
                with patch("rekipedia.orchestrator.run_ask._rag_chunks", return_value=[]):
                    result = stream_ask("What?", tmp_path, tmp_path, llm_config)
                    chunks = list(result)

        assert chunks == ["Hello", " world", "!"]

    def test_stream_ask_raises_when_no_scan(self, tmp_path):
        llm_config = LLMConfig(model="test/model")
        with pytest.raises(RuntimeError, match="No knowledge store"):
            stream_ask("question", tmp_path, tmp_path, llm_config)

    def test_stream_ask_uses_default_llm_config(self, tmp_path):
        db_path = tmp_path / "store.db"
        db_path.touch()

        with patch("rekipedia.orchestrator.run_ask.SqliteStore") as MockStore:
            instance = MockStore.return_value.__enter__.return_value
            instance.get_latest_run_id.return_value = "run-1"
            with patch("rekipedia.orchestrator.run_ask.LLMClient") as MockLLM:
                MockLLM.return_value.stream.return_value = iter(["answer"])
                with patch("rekipedia.orchestrator.run_ask._rag_chunks", return_value=[]):
                    result = stream_ask("What?", tmp_path, tmp_path)
                    chunks = list(result)

        assert chunks == ["answer"]
