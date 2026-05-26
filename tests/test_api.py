"""Tests for the rekipedia Python API (rekipedia.api)."""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from rekipedia.api import (
    AskResult,
    Citation,
    ScanResult,
    _parse_citations,
    ask,
    ask_async,
    scan,
    scan_async,
)


# ---------------------------------------------------------------------------
# Citation parsing
# ---------------------------------------------------------------------------


class TestParseCitations:
    def test_parses_file_with_line(self):
        text = "See `src/rekipedia/api.py:42` for details."
        citations = _parse_citations(text)
        assert len(citations) == 1
        assert citations[0].file == "src/rekipedia/api.py"
        assert citations[0].line == 42

    def test_parses_file_without_line(self):
        text = "Check orchestrator/run_digest.py for the pipeline."
        citations = _parse_citations(text)
        assert any(c.file == "orchestrator/run_digest.py" for c in citations)

    def test_deduplicates(self):
        text = "api.py:10 and api.py:10 again"
        citations = _parse_citations(text)
        assert sum(1 for c in citations if c.file == "api.py" and c.line == 10) == 1

    def test_multiple_files(self):
        text = "See api.py:1 and storage/sqlite_store.py:99 for more."
        citations = _parse_citations(text)
        files = [c.file for c in citations]
        assert "api.py" in files
        assert "storage/sqlite_store.py" in files

    def test_empty_text(self):
        assert _parse_citations("") == []

    def test_no_citations(self):
        citations = _parse_citations("This answer has no file references at all.")
        assert citations == []


# ---------------------------------------------------------------------------
# ScanResult / AskResult dataclasses
# ---------------------------------------------------------------------------


class TestScanResult:
    def test_defaults(self, tmp_path):
        r = ScanResult(
            repo_path=tmp_path,
            db_path=tmp_path / "store.db",
            wiki_dir=tmp_path / "wiki",
        )
        assert r.page_count == 0
        assert r.symbol_count == 0
        assert r.token_count == 0
        assert r.wiki_pages == []
        assert r.run_id == ""

    def test_repr(self, tmp_path):
        r = ScanResult(
            repo_path=tmp_path,
            db_path=tmp_path / "store.db",
            wiki_dir=tmp_path / "wiki",
            page_count=5,
            symbol_count=100,
            token_count=2000,
        )
        rep = repr(r)
        assert "pages=5" in rep
        assert "symbols=100" in rep


class TestAskResult:
    def test_fields(self):
        r = AskResult(question="What?", text="Answer here. See api.py:1.")
        assert r.question == "What?"
        assert "Answer" in r.text

    def test_citation_dataclass(self):
        c = Citation(file="foo.py", line=10, snippet="def foo():")
        assert c.file == "foo.py"
        assert c.line == 10
        assert c.snippet == "def foo():"


# ---------------------------------------------------------------------------
# scan() — unit tests with mocked run_digest
# ---------------------------------------------------------------------------


class TestScanFunction:
    def _make_wiki(self, tmp_path: Path) -> Path:
        """Create a fake wiki directory with two markdown pages."""
        wiki_dir = tmp_path / ".rekipedia" / "wiki"
        wiki_dir.mkdir(parents=True)
        (wiki_dir / "overview.md").write_text(
            '---\ntitle: "Overview"\n---\n# Overview\n' + "word " * 200
        )
        (wiki_dir / "api-design.md").write_text(
            '---\ntitle: "API Design"\n---\n# API\n' + "word " * 100
        )
        return wiki_dir

    def test_scan_returns_scan_result(self, tmp_path):
        self._make_wiki(tmp_path)

        with (
            patch("rekipedia.orchestrator.run_digest.run_digest") as mock_digest,
            patch("rekipedia.api._get_run_id", return_value="run-abc"),
        ):
            mock_digest.return_value = None
            result = scan(tmp_path)

        assert isinstance(result, ScanResult)
        assert result.repo_path == tmp_path
        assert result.page_count == 2
        assert result.token_count > 0
        assert result.run_id == "run-abc"

    def test_scan_passes_force_flag(self, tmp_path):
        self._make_wiki(tmp_path)

        with (
            patch("rekipedia.orchestrator.run_digest.run_digest") as mock_digest,
            patch("rekipedia.api._get_run_id", return_value=""),
        ):
            mock_digest.return_value = None
            scan(tmp_path, force=True)
            _, kwargs = mock_digest.call_args
            assert kwargs.get("force") is True

    def test_scan_passes_languages(self, tmp_path):
        self._make_wiki(tmp_path)

        with (
            patch("rekipedia.orchestrator.run_digest.run_digest") as mock_digest,
            patch("rekipedia.api._get_run_id", return_value=""),
        ):
            mock_digest.return_value = None
            scan(tmp_path, languages=["python"])
            _, kwargs = mock_digest.call_args
            assert kwargs.get("languages") == ["python"]

    def test_scan_str_path(self, tmp_path):
        self._make_wiki(tmp_path)

        with (
            patch("rekipedia.orchestrator.run_digest.run_digest"),
            patch("rekipedia.api._get_run_id", return_value=""),
        ):
            result = scan(str(tmp_path))
            assert result.repo_path == tmp_path

    def test_wiki_pages_include_title(self, tmp_path):
        self._make_wiki(tmp_path)

        with (
            patch("rekipedia.orchestrator.run_digest.run_digest"),
            patch("rekipedia.api._get_run_id", return_value=""),
        ):
            result = scan(tmp_path)

        titles = [p["title"] for p in result.wiki_pages]
        assert "Overview" in titles
        assert "API Design" in titles

    def test_scan_no_wiki_dir(self, tmp_path):
        """scan() should succeed even if wiki dir does not exist yet."""
        (tmp_path / ".rekipedia").mkdir()

        with (
            patch("rekipedia.orchestrator.run_digest.run_digest"),
            patch("rekipedia.api._get_run_id", return_value=""),
        ):
            result = scan(tmp_path)

        assert result.page_count == 0
        assert result.token_count == 0


# ---------------------------------------------------------------------------
# ask() — unit tests with mocked run_ask
# ---------------------------------------------------------------------------


class TestAskFunction:
    def test_ask_returns_ask_result(self, tmp_path):
        (tmp_path / ".rekipedia").mkdir()

        with patch("rekipedia.orchestrator.run_ask.run_ask") as mock_ask:
            mock_ask.return_value = (
                "The auth flow is in auth.py:42 and uses JWT tokens."
            )
            result = ask(tmp_path, "How does auth work?")

        assert isinstance(result, AskResult)
        assert result.question == "How does auth work?"
        assert "JWT" in result.text
        assert any(c.file == "auth.py" for c in result.citations)

    def test_ask_passes_question(self, tmp_path):
        (tmp_path / ".rekipedia").mkdir()

        with patch("rekipedia.orchestrator.run_ask.run_ask") as mock_ask:
            mock_ask.return_value = "Answer."
            ask(tmp_path, "What is the entry point?")
            _, kwargs = mock_ask.call_args
            assert kwargs.get("question") == "What is the entry point?"

    def test_ask_str_path(self, tmp_path):
        (tmp_path / ".rekipedia").mkdir()

        with patch("rekipedia.orchestrator.run_ask.run_ask") as mock_ask:
            mock_ask.return_value = "Answer."
            result = ask(str(tmp_path), "test question")
            assert isinstance(result, AskResult)

    def test_ask_empty_citations(self, tmp_path):
        (tmp_path / ".rekipedia").mkdir()

        with patch("rekipedia.orchestrator.run_ask.run_ask") as mock_ask:
            mock_ask.return_value = "This answer has no file references."
            result = ask(tmp_path, "?")
            assert result.citations == []


# ---------------------------------------------------------------------------
# Async variants
# ---------------------------------------------------------------------------


class TestAsyncAPI:
    def test_scan_async(self, tmp_path):
        (tmp_path / ".rekipedia" / "wiki").mkdir(parents=True)

        with (
            patch("rekipedia.orchestrator.run_digest.run_digest"),
            patch("rekipedia.api._get_run_id", return_value=""),
        ):
            result = asyncio.run(scan_async(tmp_path))

        assert isinstance(result, ScanResult)

    def test_ask_async(self, tmp_path):
        (tmp_path / ".rekipedia").mkdir()

        with patch("rekipedia.orchestrator.run_ask.run_ask") as mock_ask:
            mock_ask.return_value = "Async answer."
            result = asyncio.run(ask_async(tmp_path, "async question?"))

        assert isinstance(result, AskResult)
        assert result.text == "Async answer."

    @pytest.mark.asyncio
    async def test_scan_async_awaitable(self, tmp_path):
        (tmp_path / ".rekipedia" / "wiki").mkdir(parents=True)

        with (
            patch("rekipedia.orchestrator.run_digest.run_digest"),
            patch("rekipedia.api._get_run_id", return_value=""),
        ):
            result = await scan_async(tmp_path)

        assert isinstance(result, ScanResult)

    @pytest.mark.asyncio
    async def test_ask_async_awaitable(self, tmp_path):
        (tmp_path / ".rekipedia").mkdir()

        with patch("rekipedia.orchestrator.run_ask.run_ask") as mock_ask:
            mock_ask.return_value = "Awaitable answer."
            result = await ask_async(tmp_path, "awaitable question?")

        assert isinstance(result, AskResult)


# ---------------------------------------------------------------------------
# Top-level import
# ---------------------------------------------------------------------------


class TestTopLevelImport:
    def test_import_from_package(self):
        import rekipedia

        assert callable(rekipedia.scan)
        assert callable(rekipedia.ask)
        assert callable(rekipedia.scan_async)
        assert callable(rekipedia.ask_async)
        assert rekipedia.ScanResult is ScanResult
        assert rekipedia.AskResult is AskResult
        assert rekipedia.Citation is Citation

    def test_version_still_present(self):
        import rekipedia

        assert rekipedia.__version__ == "0.17.22"
