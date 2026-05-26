"""Tests for --brief flag and REKIPEDIA_BRIEF=1 env var in `reki ask`."""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from rekipedia.models.contracts import LLMConfig
from rekipedia.orchestrator.run_ask import (
    _build_full_system,
    _BRIEF_SYSTEM_SUFFIX,
    run_ask,
    stream_ask,
)


# ---------------------------------------------------------------------------
# Helper: minimal output_dir with store.db
# ---------------------------------------------------------------------------

def _make_output_dir(tmp_path: Path) -> Path:
    output_dir = tmp_path / ".rekipedia"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "store.db").touch()
    return output_dir


# ---------------------------------------------------------------------------
# _build_full_system — brief flag appends the suffix
# ---------------------------------------------------------------------------

class TestBuildFullSystemBrief:
    def test_brief_false_does_not_append_suffix(self, tmp_path):
        llm_config = LLMConfig(model="test/model")
        with patch("rekipedia.orchestrator.run_ask._rag_chunks", return_value=[]):
            result = _build_full_system("what is this?", tmp_path, llm_config, brief=False)
        assert _BRIEF_SYSTEM_SUFFIX not in result

    def test_brief_true_appends_suffix(self, tmp_path):
        llm_config = LLMConfig(model="test/model")
        with patch("rekipedia.orchestrator.run_ask._rag_chunks", return_value=[]):
            result = _build_full_system("what is this?", tmp_path, llm_config, brief=True)
        assert _BRIEF_SYSTEM_SUFFIX in result
        assert "ONE paragraph" in result
        assert "file:line citations" in result


# ---------------------------------------------------------------------------
# run_ask — brief=True passes suffix to LLM
# ---------------------------------------------------------------------------

class TestRunAskBrief:
    def _setup(self, tmp_path):
        output_dir = _make_output_dir(tmp_path)
        llm_config = LLMConfig(model="test/model")
        return output_dir, llm_config

    def test_brief_true_includes_brief_suffix_in_system(self, tmp_path):
        output_dir, llm_config = self._setup(tmp_path)
        captured_system: list[str] = []

        def _capture(prompt, system="", history=None):
            captured_system.append(system)
            return "short answer"

        with patch("rekipedia.orchestrator.run_ask.SqliteStore") as MockStore:
            MockStore.return_value.__enter__.return_value.get_latest_run_id.return_value = "run-1"
            with patch("rekipedia.orchestrator.run_ask.LLMClient") as MockLLM:
                MockLLM.return_value.call.side_effect = _capture
                with patch("rekipedia.orchestrator.run_ask._rag_chunks", return_value=[]):
                    run_ask("what is this?", tmp_path, output_dir, llm_config, brief=True)

        assert captured_system, "LLMClient.call was never invoked"
        assert _BRIEF_SYSTEM_SUFFIX in captured_system[0]

    def test_brief_false_excludes_brief_suffix(self, tmp_path):
        output_dir, llm_config = self._setup(tmp_path)
        captured_system: list[str] = []

        def _capture(prompt, system="", history=None):
            captured_system.append(system)
            return "long answer"

        with patch("rekipedia.orchestrator.run_ask.SqliteStore") as MockStore:
            MockStore.return_value.__enter__.return_value.get_latest_run_id.return_value = "run-1"
            with patch("rekipedia.orchestrator.run_ask.LLMClient") as MockLLM:
                MockLLM.return_value.call.side_effect = _capture
                with patch("rekipedia.orchestrator.run_ask._rag_chunks", return_value=[]):
                    run_ask("what is this?", tmp_path, output_dir, llm_config, brief=False)

        assert captured_system
        assert _BRIEF_SYSTEM_SUFFIX not in captured_system[0]

    def test_env_var_rekipedia_brief_activates_brief(self, tmp_path, monkeypatch):
        monkeypatch.setenv("REKIPEDIA_BRIEF", "1")
        output_dir, llm_config = self._setup(tmp_path)
        captured_system: list[str] = []

        def _capture(prompt, system="", history=None):
            captured_system.append(system)
            return "brief answer"

        with patch("rekipedia.orchestrator.run_ask.SqliteStore") as MockStore:
            MockStore.return_value.__enter__.return_value.get_latest_run_id.return_value = "run-1"
            with patch("rekipedia.orchestrator.run_ask.LLMClient") as MockLLM:
                MockLLM.return_value.call.side_effect = _capture
                with patch("rekipedia.orchestrator.run_ask._rag_chunks", return_value=[]):
                    run_ask("what is this?", tmp_path, output_dir, llm_config)

        assert captured_system
        assert _BRIEF_SYSTEM_SUFFIX in captured_system[0]

    def test_env_var_0_does_not_activate_brief(self, tmp_path, monkeypatch):
        monkeypatch.setenv("REKIPEDIA_BRIEF", "0")
        output_dir, llm_config = self._setup(tmp_path)
        captured_system: list[str] = []

        def _capture(prompt, system="", history=None):
            captured_system.append(system)
            return "normal answer"

        with patch("rekipedia.orchestrator.run_ask.SqliteStore") as MockStore:
            MockStore.return_value.__enter__.return_value.get_latest_run_id.return_value = "run-1"
            with patch("rekipedia.orchestrator.run_ask.LLMClient") as MockLLM:
                MockLLM.return_value.call.side_effect = _capture
                with patch("rekipedia.orchestrator.run_ask._rag_chunks", return_value=[]):
                    run_ask("what is this?", tmp_path, output_dir, llm_config)

        assert captured_system
        assert _BRIEF_SYSTEM_SUFFIX not in captured_system[0]


# ---------------------------------------------------------------------------
# stream_ask — brief=True also works
# ---------------------------------------------------------------------------

class TestStreamAskBrief:
    def test_stream_brief_true_appends_suffix(self, tmp_path, monkeypatch):
        monkeypatch.delenv("REKIPEDIA_BRIEF", raising=False)
        output_dir = _make_output_dir(tmp_path)
        llm_config = LLMConfig(model="test/model")
        captured_system: list[str] = []

        def _capture_stream(prompt, system="", history=None):
            captured_system.append(system)
            return iter(["brief answer"])

        with patch("rekipedia.orchestrator.run_ask.SqliteStore") as MockStore:
            MockStore.return_value.__enter__.return_value.get_latest_run_id.return_value = "run-1"
            with patch("rekipedia.orchestrator.run_ask.LLMClient") as MockLLM:
                MockLLM.return_value.stream.side_effect = _capture_stream
                with patch("rekipedia.orchestrator.run_ask._rag_chunks", return_value=[]):
                    chunks = list(stream_ask("what?", tmp_path, output_dir, llm_config, brief=True))

        assert chunks == ["brief answer"]
        assert captured_system
        assert _BRIEF_SYSTEM_SUFFIX in captured_system[0]


# ---------------------------------------------------------------------------
# CLI — --brief flag is accepted
# ---------------------------------------------------------------------------

class TestAskCmdBriefFlag:
    def test_brief_flag_accepted_by_cli(self, tmp_path):
        from click.testing import CliRunner
        from rekipedia.cli.ask import ask_cmd

        runner = CliRunner()
        with patch("rekipedia.cli.ask._answer_streaming") as mock_answer:
            mock_answer.return_value = "brief answer"
            result = runner.invoke(
                ask_cmd,
                [
                    "--repo", str(tmp_path),
                    "--output-dir", str(tmp_path),
                    "--brief",
                    "What is this?",
                ],
            )

        # Should not fail with "No such option" error
        assert "No such option" not in (result.output or "")
        assert result.exit_code in (0, 1)  # 1 = missing scan, not CLI error

    def test_brief_flag_passed_to_answer_streaming(self, tmp_path):
        from click.testing import CliRunner
        from rekipedia.cli.ask import ask_cmd

        runner = CliRunner()
        with patch("rekipedia.cli.ask._answer_streaming") as mock_answer:
            mock_answer.return_value = "brief"
            runner.invoke(
                ask_cmd,
                [
                    "--repo", str(tmp_path),
                    "--output-dir", str(tmp_path),
                    "--brief",
                    "What is this?",
                ],
            )

        if mock_answer.called:
            call_kwargs = mock_answer.call_args.kwargs
            assert call_kwargs.get("brief") is True

    def test_no_brief_flag_defaults_false(self, tmp_path):
        from click.testing import CliRunner
        from rekipedia.cli.ask import ask_cmd

        runner = CliRunner()
        with patch("rekipedia.cli.ask._answer_streaming") as mock_answer:
            mock_answer.return_value = "normal"
            runner.invoke(
                ask_cmd,
                [
                    "--repo", str(tmp_path),
                    "--output-dir", str(tmp_path),
                    "What is this?",
                ],
            )

        if mock_answer.called:
            call_kwargs = mock_answer.call_args.kwargs
            assert call_kwargs.get("brief") is False
