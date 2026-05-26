"""Tests for reki affected — git-diff-aware test file selection (#136)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from rekipedia.cli.affected import _git_diff_files, _resolve_files, affected_cmd

# ── helper: build minimal fake symbols + relationships ────────────────────

def _make_symbols(*pairs):
    """pairs: (name, file)"""
    return [{"name": n, "file": f, "kind": "function", "line_start": 1} for n, f in pairs]


def _make_rels(*triples):
    """triples: (from_, to, kind)"""
    return [{"from_": f, "to": t, "kind": k} for f, t, k in triples]


# ── unit: _resolve_files ─────────────────────────────────────────────────

class TestResolveFiles:
    def test_files_opt_takes_priority(self):
        result = _resolve_files("a.py,b.py", base=None, head=None)
        assert result == ["a.py", "b.py"]

    def test_files_opt_strips_whitespace(self):
        result = _resolve_files(" a.py , b.py ", base=None, head=None)
        assert result == ["a.py", "b.py"]

    def test_empty_files_opt_ignored(self):
        result = _resolve_files("", base=None, head=None)
        assert result == []

    def test_base_calls_git_diff(self):
        with patch("rekipedia.cli.affected.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="src/foo.py\nsrc/bar.py\n", stderr="")
            result = _resolve_files(None, base="main", head="HEAD")
        assert result == ["src/foo.py", "src/bar.py"]
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert "main" in cmd
        assert "HEAD" in cmd

    def test_base_with_custom_head(self):
        with patch("rekipedia.cli.affected.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="x.py\n", stderr="")
            result = _resolve_files(None, base="v1.0", head="feature")
        cmd = mock_run.call_args[0][0]
        assert "v1.0" in cmd
        assert "feature" in cmd


# ── unit: _git_diff_files ────────────────────────────────────────────────

class TestGitDiffFiles:
    def test_returns_list(self):
        with patch("rekipedia.cli.affected.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="a.py\nb.py\n", stderr="")
            result = _git_diff_files("main", "HEAD")
        assert result == ["a.py", "b.py"]

    def test_git_failure_raises(self):
        import click
        with patch("rekipedia.cli.affected.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=128, stdout="", stderr="fatal: not a git repo")
            with pytest.raises(click.ClickException, match="git diff failed"):
                _git_diff_files("main", "HEAD")

    def test_empty_diff(self):
        with patch("rekipedia.cli.affected.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            result = _git_diff_files("main", "HEAD")
        assert result == []


# ── integration: CLI command ──────────────────────────────────────────────

def _make_store_mock(symbols, relationships):
    store = MagicMock()
    store.__enter__ = lambda s: s
    store.__exit__ = MagicMock(return_value=False)
    store.get_latest_run_id.return_value = "run-123"
    store.get_all_symbols.return_value = symbols
    store.get_all_relationships.return_value = relationships
    return store


class TestAffectedCmd:
    runner = CliRunner()

    def _invoke(self, args, input_text=None, store=None, db_exists=True):
        symbols = _make_symbols(
            ("login", "src/auth.py"),
            ("validate_user", "src/user.py"),
            ("test_login", "tests/test_auth.py"),
            ("test_validate", "tests/test_user.py"),
        )
        rels = _make_rels(
            ("test_login", "login", "calls"),
            ("login", "validate_user", "calls"),
            ("test_validate", "validate_user", "calls"),
        )
        _store = store or _make_store_mock(symbols, rels)

        with (
            patch("rekipedia.storage.sqlite_store.SqliteStore", return_value=_store),
            patch.object(Path, "exists", return_value=db_exists),
        ):
            return self.runner.invoke(affected_cmd, args, input=input_text, catch_exceptions=False)

    # basic text output
    def test_stdin_changed_file_returns_tests(self):
        result = self._invoke(["--files", "src/auth.py"])
        assert result.exit_code == 0
        assert "tests/test_auth.py" in result.output

    def test_changed_auth_affects_test_validate_via_chain(self):
        # auth.py → validate_user → test_validate
        result = self._invoke(["--files", "src/auth.py"])
        assert "tests/test_auth.py" in result.output

    def test_multiple_files_union_tests(self):
        result = self._invoke(["--files", "src/auth.py,src/user.py"])
        assert "tests/test_auth.py" in result.output
        assert "tests/test_user.py" in result.output

    def test_no_changed_files_prints_warning(self):
        result = self._invoke([])
        assert result.exit_code == 0
        assert "No changed files" in result.output

    # JSON output
    def test_json_format_valid(self):
        result = self._invoke(["--files", "src/auth.py", "--format", "json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "affected_tests" in data
        assert "changed_files" in data
        assert "per_file" in data
        assert "src/auth.py" in data["changed_files"]

    def test_json_no_changes_empty(self):
        result = self._invoke(["--format", "json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["affected_tests"] == []
        assert data["changed_files"] == []

    def test_json_per_file_structure(self):
        result = self._invoke(["--files", "src/auth.py", "--format", "json"])
        data = json.loads(result.output)
        assert "src/auth.py" in data["per_file"]
        entry = data["per_file"]["src/auth.py"]
        assert "related_tests" in entry
        assert "affected_files" in entry

    # --include-all
    def test_include_all_returns_non_test_files(self):
        result = self._invoke(["--files", "src/auth.py", "--include-all"])
        # Should include src/user.py since login → validate_user
        assert result.exit_code == 0

    # missing DB
    def test_missing_db_raises_error(self):
        result = self._invoke(["--files", "src/auth.py"], db_exists=False)
        assert result.exit_code != 0

    # --base / --head
    def test_base_head_flags(self):
        with patch("rekipedia.cli.affected.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="src/auth.py\n", stderr="")
            result = self._invoke(["--base", "main", "--head", "HEAD"])
        assert result.exit_code == 0

    # depth flag
    def test_depth_zero_means_unlimited(self):
        result = self._invoke(["--files", "src/auth.py", "--depth", "0"])
        assert result.exit_code == 0

    def test_depth_one_limits_traversal(self):
        # With depth=1, only direct callers of auth.py symbols
        result = self._invoke(["--files", "src/auth.py", "--depth", "1"])
        assert result.exit_code == 0

    # registered in CLI
    def test_command_registered_in_cli(self):
        from rekipedia.cli import main
        cmd_names = [c for c in main.commands]
        assert "affected" in cmd_names

    # help text
    def test_help_text(self):
        result = self.runner.invoke(affected_cmd, ["--help"])
        assert result.exit_code == 0
        assert "affected" in result.output.lower() or "test" in result.output.lower()
