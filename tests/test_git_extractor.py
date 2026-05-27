"""Tests for the git_extractor module (issue #172)."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from rekipedia.extractors.git_extractor import (
    GitCommit,
    _parse_git_log,
    commits_to_dicts,
    extract_commits,
)
from rekipedia.storage.sqlite_store import SqliteStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_GIT_LOG = """\
a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2|a1b2c3d|Alice|2024-01-15T10:00:00+00:00|Fix authentication bug

src/auth/login.py
src/auth/middleware.py

b2c3d4e5f6a7b2c3d4e5f6a7b2c3d4e5f6a7b2c3|b2c3d4e|Bob|2024-01-14T09:30:00+00:00|Add unit tests for payment module

tests/test_payment.py
src/payment/processor.py

c3d4e5f6a7b8c3d4e5f6a7b8c3d4e5f6a7b8c3d4|c3d4e5f|Carol|2024-01-13T08:00:00+00:00|Initial commit

src/main.py
README.md
"""


# ---------------------------------------------------------------------------
# Parser tests
# ---------------------------------------------------------------------------

class TestParseGitLog:
    def test_parses_three_commits(self):
        commits = _parse_git_log(SAMPLE_GIT_LOG)
        assert len(commits) == 3

    def test_commit_fields(self):
        commits = _parse_git_log(SAMPLE_GIT_LOG)
        c = commits[0]
        assert c.hash == "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2"
        assert c.short_hash == "a1b2c3d"
        assert c.author == "Alice"
        assert c.date == "2024-01-15T10:00:00+00:00"
        assert c.message == "Fix authentication bug"
        assert "src/auth/login.py" in c.files_changed
        assert "src/auth/middleware.py" in c.files_changed

    def test_files_changed_parsed(self):
        commits = _parse_git_log(SAMPLE_GIT_LOG)
        assert commits[1].files_changed == ["tests/test_payment.py", "src/payment/processor.py"]

    def test_empty_output_returns_empty_list(self):
        assert _parse_git_log("") == []

    def test_returns_git_commit_instances(self):
        commits = _parse_git_log(SAMPLE_GIT_LOG)
        for c in commits:
            assert isinstance(c, GitCommit)


# ---------------------------------------------------------------------------
# extract_commits — no real git needed
# ---------------------------------------------------------------------------

class TestExtractCommits:
    def test_non_git_directory_returns_empty(self, tmp_path):
        """Non-git directories should return [] without raising."""
        result = extract_commits(tmp_path)
        assert result == []

    def test_git_not_found_returns_empty(self, tmp_path):
        """If git binary is absent, return []."""
        with patch("rekipedia.extractors.git_extractor.subprocess.run", side_effect=FileNotFoundError):
            result = extract_commits(tmp_path)
        assert result == []

    def test_git_nonzero_exit_returns_empty(self, tmp_path):
        """Non-zero returncode (e.g. not a git repo) returns []."""
        mock_result = MagicMock()
        mock_result.returncode = 128
        mock_result.stdout = ""
        mock_result.stderr = "fatal: not a git repository"
        with patch("rekipedia.extractors.git_extractor.subprocess.run", return_value=mock_result):
            result = extract_commits(tmp_path)
        assert result == []

    def test_successful_extraction(self, tmp_path):
        """Successful git log output is parsed correctly."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = SAMPLE_GIT_LOG
        with patch("rekipedia.extractors.git_extractor.subprocess.run", return_value=mock_result):
            commits = extract_commits(tmp_path)
        assert len(commits) == 3
        assert commits[0].author == "Alice"

    def test_max_commits_respected(self, tmp_path):
        """max_commits is passed to the git command."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        with patch("rekipedia.extractors.git_extractor.subprocess.run", return_value=mock_result) as mock_run:
            extract_commits(tmp_path, max_commits=10)
        cmd = mock_run.call_args[0][0]
        assert "-10" in cmd


# ---------------------------------------------------------------------------
# commits_to_dicts
# ---------------------------------------------------------------------------

class TestCommitsToDicts:
    def test_converts_correctly(self):
        commits = _parse_git_log(SAMPLE_GIT_LOG)
        dicts = commits_to_dicts(commits)
        assert len(dicts) == 3
        d = dicts[0]
        assert d["hash"] == commits[0].hash
        assert d["short_hash"] == commits[0].short_hash
        files = json.loads(d["files_changed"])
        assert isinstance(files, list)
        assert "src/auth/login.py" in files


# ---------------------------------------------------------------------------
# SqliteStore roundtrip
# ---------------------------------------------------------------------------

class TestSqliteStoreGit:
    def _make_store(self, tmp_path: Path) -> SqliteStore:
        store = SqliteStore(tmp_path / "test.db")
        store.open()
        return store

    def test_store_and_retrieve_commits(self, tmp_path):
        store = self._make_store(tmp_path)
        try:
            commits = _parse_git_log(SAMPLE_GIT_LOG)
            dicts = commits_to_dicts(commits)
            store.store_commits(dicts)

            rows = store.get_commits_for_file("src/auth/login.py")
            assert len(rows) == 1
            assert rows[0]["author"] == "Alice"
        finally:
            store.close()

    def test_get_commit_count(self, tmp_path):
        store = self._make_store(tmp_path)
        try:
            assert store.get_commit_count() == 0
            commits = _parse_git_log(SAMPLE_GIT_LOG)
            store.store_commits(commits_to_dicts(commits))
            assert store.get_commit_count() == 3
        finally:
            store.close()

    def test_get_commits_for_file_no_results(self, tmp_path):
        store = self._make_store(tmp_path)
        try:
            rows = store.get_commits_for_file("nonexistent.py")
            assert rows == []
        finally:
            store.close()

    def test_upsert_idempotent(self, tmp_path):
        """Storing the same commits twice should not duplicate them."""
        store = self._make_store(tmp_path)
        try:
            commits = _parse_git_log(SAMPLE_GIT_LOG)
            dicts = commits_to_dicts(commits)
            store.store_commits(dicts)
            store.store_commits(dicts)
            assert store.get_commit_count() == 3
        finally:
            store.close()


# ---------------------------------------------------------------------------
# CLI flag
# ---------------------------------------------------------------------------

class TestCliWithGitFlag:
    def test_with_git_flag_accepted(self):
        """--with-git flag must be accepted by the CLI without error."""
        from click.testing import CliRunner
        from rekipedia.cli.scan import scan_cmd

        runner = CliRunner()
        # Use --help to avoid actually running a scan; just verify argparse accepts the flag
        result = runner.invoke(scan_cmd, ["--help"])
        assert result.exit_code == 0
        assert "--with-git" in result.output

    def test_no_git_flag_accepted(self):
        """--no-git flag must also be accepted."""
        from click.testing import CliRunner
        from rekipedia.cli.scan import scan_cmd

        runner = CliRunner()
        result = runner.invoke(scan_cmd, ["--help"])
        assert result.exit_code == 0
        assert "--no-git" in result.output
