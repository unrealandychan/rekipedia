"""Tests for --doc-type flag for reki scan (#126)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from rekipedia.models.contracts import LLMConfig
from rekipedia.synthesis.doc_types import (
    DOC_TYPE_CHOICES,
    doc_type_preamble,
)
from rekipedia.synthesis.page_builder import PageBuilder

# ── doc_types module ──────────────────────────────────────────────────────────

class TestDocTypePreamble:
    def test_all_choices_present(self):
        assert set(DOC_TYPE_CHOICES) >= {"default", "api-ref", "tutorial", "runbook", "adr", "changelog"}

    def test_default_returns_empty_string(self):
        assert doc_type_preamble("default") == ""

    def test_api_ref_contains_signature(self):
        p = doc_type_preamble("api-ref")
        assert "API Reference" in p
        assert "Signature" in p

    def test_tutorial_contains_numbered_steps(self):
        p = doc_type_preamble("tutorial")
        assert "Tutorial" in p
        assert "numbered" in p.lower() or "steps" in p.lower()

    def test_runbook_contains_prerequisites(self):
        p = doc_type_preamble("runbook")
        assert "Runbook" in p or "runbook" in p.lower()
        assert "Prerequisites" in p

    def test_adr_contains_madr_sections(self):
        p = doc_type_preamble("adr")
        assert "Context" in p
        assert "Decision" in p
        assert "Consequences" in p

    def test_changelog_contains_migration(self):
        p = doc_type_preamble("changelog")
        assert "Changelog" in p or "changelog" in p.lower()
        assert "Migration" in p

    def test_unknown_doc_type_raises(self):
        with pytest.raises(ValueError, match="Unknown doc-type"):
            doc_type_preamble("nonexistent-type")

    def test_all_non_default_preambles_nonempty(self):
        for dt in DOC_TYPE_CHOICES:
            if dt != "default":
                assert doc_type_preamble(dt), f"Empty preamble for doc-type {dt!r}"


# ── PageBuilder integration ───────────────────────────────────────────────────

class TestPageBuilderDocType:
    def _make_builder(self, doc_type: str = "default") -> PageBuilder:
        cfg = LLMConfig(model="fake/model")
        mock_caller = MagicMock()
        mock_caller.call.return_value = "# Test\nContent."
        return PageBuilder(cfg, caller=mock_caller, doc_type=doc_type)

    def test_default_doc_type_uses_standard_system(self):
        b = _make_builder_raw("default")
        # With default, system prompt should NOT contain doc-type override header
        assert "Doc-Type Override" not in b._system

    def test_api_ref_prepends_preamble(self):
        b = _make_builder_raw("api-ref")
        assert "API Reference" in b._system

    def test_tutorial_prepends_preamble(self):
        b = _make_builder_raw("tutorial")
        assert "Tutorial" in b._system

    def test_runbook_prepends_preamble(self):
        b = _make_builder_raw("runbook")
        assert "Runbook" in b._system or "runbook" in b._system.lower()

    def test_adr_prepends_preamble(self):
        b = _make_builder_raw("adr")
        assert "Decision" in b._system

    def test_changelog_prepends_preamble(self):
        b = _make_builder_raw("changelog")
        assert "Changelog" in b._system or "changelog" in b._system.lower()

    def test_doc_type_stored_on_instance(self):
        b = _make_builder_raw("tutorial")
        assert b._doc_type == "tutorial"

    def test_default_doc_type_stored(self):
        b = _make_builder_raw("default")
        assert b._doc_type == "default"


def _make_builder_raw(doc_type: str) -> PageBuilder:
    cfg = LLMConfig(model="fake/model")
    mock_caller = MagicMock()
    mock_caller.call.return_value = "# Page\nContent."
    return PageBuilder(cfg, caller=mock_caller, doc_type=doc_type)


# ── CLI --doc-type flag ───────────────────────────────────────────────────────

class TestScanDocTypeFlag:
    def _invoke(self, args: list[str]) -> object:
        from rekipedia.cli.scan import scan_cmd
        runner = CliRunner()
        with patch("rekipedia.orchestrator.run_digest.run_digest"):
            return runner.invoke(scan_cmd, args, catch_exceptions=False)

    def test_doc_type_in_params(self):
        from rekipedia.cli.scan import scan_cmd
        names = [p.name for p in scan_cmd.params]
        assert "doc_type" in names

    def test_default_doc_type_accepted(self, tmp_path):
        result = self._invoke([str(tmp_path), "--no-llm", "--doc-type", "default"])
        assert result.exit_code == 0, result.output

    def test_api_ref_accepted(self, tmp_path):
        result = self._invoke([str(tmp_path), "--no-llm", "--doc-type", "api-ref"])
        assert result.exit_code == 0, result.output

    def test_tutorial_accepted(self, tmp_path):
        result = self._invoke([str(tmp_path), "--no-llm", "--doc-type", "tutorial"])
        assert result.exit_code == 0, result.output

    def test_runbook_accepted(self, tmp_path):
        result = self._invoke([str(tmp_path), "--no-llm", "--doc-type", "runbook"])
        assert result.exit_code == 0, result.output

    def test_adr_accepted(self, tmp_path):
        result = self._invoke([str(tmp_path), "--no-llm", "--doc-type", "adr"])
        assert result.exit_code == 0, result.output

    def test_changelog_accepted(self, tmp_path):
        result = self._invoke([str(tmp_path), "--no-llm", "--doc-type", "changelog"])
        assert result.exit_code == 0, result.output

    def test_invalid_doc_type_rejected(self, tmp_path):
        from rekipedia.cli.scan import scan_cmd
        runner = CliRunner()
        result = runner.invoke(scan_cmd, [str(tmp_path), "--doc-type", "invalid-type"])
        assert result.exit_code != 0

    def test_doc_type_shown_when_non_default(self, tmp_path):
        from rekipedia.cli.scan import scan_cmd
        runner = CliRunner()
        with patch("rekipedia.orchestrator.run_digest.run_digest"):
            result = runner.invoke(
                scan_cmd, [str(tmp_path), "--no-llm", "--doc-type", "tutorial"],
                catch_exceptions=False,
            )
        assert "tutorial" in result.output

    def test_doc_type_not_shown_when_default(self, tmp_path):
        from rekipedia.cli.scan import scan_cmd
        runner = CliRunner()
        with patch("rekipedia.orchestrator.run_digest.run_digest"):
            result = runner.invoke(
                scan_cmd, [str(tmp_path), "--no-llm"],
                catch_exceptions=False,
            )
        # "doc-type" display line should be absent for default
        assert "doc-type" not in result.output

    def test_doc_type_passed_to_run_digest(self, tmp_path):
        from rekipedia.cli.scan import scan_cmd
        runner = CliRunner()
        with patch("rekipedia.orchestrator.run_digest.run_digest") as mock_rd:
            runner.invoke(
                scan_cmd, [str(tmp_path), "--no-llm", "--doc-type", "adr"],
                catch_exceptions=False,
            )
        call_kwargs = mock_rd.call_args.kwargs if mock_rd.call_args else {}
        assert call_kwargs.get("doc_type") == "adr"

    def test_envvar_rekipedia_doc_type(self, tmp_path):
        from rekipedia.cli.scan import scan_cmd
        runner = CliRunner()
        with patch("rekipedia.orchestrator.run_digest.run_digest") as mock_rd:
            result = runner.invoke(
                scan_cmd, [str(tmp_path), "--no-llm"],
                env={"REKIPEDIA_DOC_TYPE": "runbook"},
                catch_exceptions=False,
            )
        call_kwargs = mock_rd.call_args.kwargs if mock_rd.call_args else {}
        assert call_kwargs.get("doc_type") == "runbook"
