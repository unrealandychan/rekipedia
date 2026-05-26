"""Tests for OSC-8 clickable citations (#130)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

# ── terminal_links module ─────────────────────────────────────────────────────

class TestOsc8Supported:
    def test_force_off(self, monkeypatch):
        monkeypatch.setenv("REKIPEDIA_OSC8", "0")
        from importlib import reload

        import rekipedia.utils.terminal_links as m
        reload(m)
        assert m.osc8_supported() is False

    def test_force_on(self, monkeypatch):
        monkeypatch.setenv("REKIPEDIA_OSC8", "1")
        from importlib import reload

        import rekipedia.utils.terminal_links as m
        reload(m)
        # isatty check skipped when forced on
        assert m.osc8_supported() is True

    def test_no_tty_returns_false(self, monkeypatch):
        monkeypatch.delenv("REKIPEDIA_OSC8", raising=False)
        from importlib import reload

        import rekipedia.utils.terminal_links as m
        reload(m)
        with patch("sys.stdout") as mock_stdout:
            mock_stdout.isatty.return_value = False
            assert m.osc8_supported() is False

    def test_iterm_detected(self, monkeypatch):
        monkeypatch.setenv("REKIPEDIA_OSC8", "")
        monkeypatch.setenv("TERM_PROGRAM", "iTerm.app")
        from importlib import reload

        import rekipedia.utils.terminal_links as m
        reload(m)
        with patch("sys.stdout") as mock_stdout:
            mock_stdout.isatty.return_value = True
            assert m.osc8_supported() is True

    def test_wezterm_detected(self, monkeypatch):
        monkeypatch.setenv("REKIPEDIA_OSC8", "")
        monkeypatch.setenv("TERM_PROGRAM", "WezTerm")
        from importlib import reload

        import rekipedia.utils.terminal_links as m
        reload(m)
        with patch("sys.stdout") as mock_stdout:
            mock_stdout.isatty.return_value = True
            assert m.osc8_supported() is True

    def test_truecolor_detected(self, monkeypatch):
        monkeypatch.setenv("REKIPEDIA_OSC8", "")
        monkeypatch.delenv("TERM_PROGRAM", raising=False)
        monkeypatch.setenv("COLORTERM", "truecolor")
        from importlib import reload

        import rekipedia.utils.terminal_links as m
        reload(m)
        with patch("sys.stdout") as mock_stdout:
            mock_stdout.isatty.return_value = True
            assert m.osc8_supported() is True

    def test_windows_terminal_detected(self, monkeypatch):
        monkeypatch.setenv("REKIPEDIA_OSC8", "")
        monkeypatch.delenv("TERM_PROGRAM", raising=False)
        monkeypatch.delenv("COLORTERM", raising=False)
        monkeypatch.delenv("TERM", raising=False)
        monkeypatch.setenv("WT_SESSION", "some-uuid")
        from importlib import reload

        import rekipedia.utils.terminal_links as m
        reload(m)
        with patch("sys.stdout") as mock_stdout:
            mock_stdout.isatty.return_value = True
            assert m.osc8_supported() is True


class TestHyperlink:
    def test_returns_plain_text_when_not_supported(self):
        from rekipedia.utils import terminal_links as m
        with patch.object(m, "osc8_supported", return_value=False):
            result = m.hyperlink("click me", "https://example.com")
        assert result == "click me"

    def test_returns_osc8_escape_when_supported(self):
        from rekipedia.utils import terminal_links as m
        with patch.object(m, "osc8_supported", return_value=True):
            result = m.hyperlink("click me", "https://example.com")
        assert "\x1b]8;;" in result
        assert "https://example.com" in result
        assert "click me" in result

    def test_osc8_format_structure(self):
        from rekipedia.utils import terminal_links as m
        with patch.object(m, "osc8_supported", return_value=True):
            result = m.hyperlink("text", "https://x.com/path")
        # Should be: ESC]8;;URL ST text ESC]8;; ST
        assert result.startswith("\x1b]8;;https://x.com/path")
        assert result.endswith("\x1b]8;;\x1b\\")
        assert "text" in result


class TestFileHyperlink:
    def test_plain_when_not_supported(self):
        from rekipedia.utils import terminal_links as m
        with patch.object(m, "osc8_supported", return_value=False):
            result = m.file_hyperlink("src/api.py", line=42, repo_root="/repo")
        assert result == "src/api.py:42"

    def test_with_line_number(self):
        from rekipedia.utils import terminal_links as m
        with patch.object(m, "osc8_supported", return_value=True):
            result = m.file_hyperlink("src/api.py", line=42, repo_root="/repo")
        assert "src/api.py:42" in result
        assert "file:///repo/src/api.py#42" in result

    def test_without_line_number(self):
        from rekipedia.utils import terminal_links as m
        with patch.object(m, "osc8_supported", return_value=True):
            result = m.file_hyperlink("src/api.py", repo_root="/repo")
        assert "src/api.py" in result
        assert "file:///repo/src/api.py" in result

    def test_custom_display_text(self):
        from rekipedia.utils import terminal_links as m
        with patch.object(m, "osc8_supported", return_value=True):
            result = m.file_hyperlink("src/api.py", line=10, repo_root="/repo",
                                       display="custom label")
        assert "custom label" in result

    def test_default_repo_root_is_cwd(self):
        from rekipedia.utils import terminal_links as m
        with patch.object(m, "osc8_supported", return_value=True):
            with patch.object(Path, "cwd", return_value=Path("/cwd")):
                result = m.file_hyperlink("src/api.py")
        assert "/cwd/src/api.py" in result


class TestPrintCitations:
    def test_prints_nothing_for_empty_list(self, capsys):
        from rekipedia.utils.terminal_links import print_citations
        mock_console = MagicMock()
        print_citations([], console=mock_console)
        mock_console.print.assert_not_called()

    def test_prints_header_and_citations(self):
        from rekipedia.api import Citation
        from rekipedia.utils.terminal_links import print_citations
        mock_console = MagicMock()
        citations = [
            Citation(file="src/api.py", line=10),
            Citation(file="src/utils.py"),
        ]
        print_citations(citations, console=mock_console, repo_root="/repo")
        calls = [str(c) for c in mock_console.print.call_args_list]
        full_output = " ".join(calls)
        assert "src/api.py" in full_output
        assert "src/utils.py" in full_output

    def test_creates_console_if_none(self):
        from rekipedia.api import Citation
        from rekipedia.utils.terminal_links import print_citations
        # Should not raise
        print_citations([Citation(file="src/foo.py")], repo_root="/repo")


# ── _parse_citations integration ──────────────────────────────────────────────

class TestParseCitations:
    def test_extracts_file_line(self):
        from rekipedia.api import _parse_citations
        text = "See `src/api.py:42` for details."
        cites = _parse_citations(text)
        assert len(cites) == 1
        assert cites[0].file == "src/api.py"
        assert cites[0].line == 42

    def test_extracts_multiple(self):
        from rekipedia.api import _parse_citations
        text = "See src/api.py:10 and src/models.py:200."
        cites = _parse_citations(text)
        files = {c.file for c in cites}
        assert "src/api.py" in files
        assert "src/models.py" in files

    def test_no_citations(self):
        from rekipedia.api import _parse_citations
        text = "This answer has no code references at all."
        cites = _parse_citations(text)
        assert cites == []

    def test_deduplicates(self):
        from rekipedia.api import _parse_citations
        text = "src/api.py:42 and again src/api.py:42"
        cites = _parse_citations(text)
        assert len(cites) == 1


# ── ask.py integration: _print_answer_citations ───────────────────────────────

class TestPrintAnswerCitations:
    def test_called_after_non_stream_answer(self, tmp_path):
        from click.testing import CliRunner

        from rekipedia.cli.ask import ask_cmd

        runner = CliRunner()
        answer_with_cite = "The login is in `src/auth.py:15`."

        with patch("rekipedia.orchestrator.run_ask.run_ask", return_value=answer_with_cite), \
             patch("rekipedia.cli.ask._print_answer_citations") as mock_print_cites:
            result = runner.invoke(
                ask_cmd,
                [str(tmp_path), "--question", "How does login work?", "--no-stream"],
                catch_exceptions=False,
            )

        mock_print_cites.assert_called_once()
        args, kwargs = mock_print_cites.call_args
        assert args[0] == answer_with_cite

    def test_skipped_when_no_citations(self, tmp_path):
        from rekipedia.cli.ask import _print_answer_citations
        from rekipedia.utils import terminal_links as m
        mock_console = MagicMock()
        with patch.object(m, "osc8_supported", return_value=True):
            # Answer with no file references → no output
            _print_answer_citations("Just a plain answer with no refs.", tmp_path, mock_console)
        mock_console.print.assert_not_called()
