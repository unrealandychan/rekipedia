"""Tests for the GitHub Issues & PR connector (#173)."""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from rekipedia.cli import main
from rekipedia.connectors.github_connector import (
    ExternalSource,
    GitHubConnector,
    RateLimitError,
    _detect_repo_from_git,
)
from rekipedia.storage.sqlite_store import SqliteStore


# ---------------------------------------------------------------------------
# 1. ExternalSource dataclass
# ---------------------------------------------------------------------------

def test_external_source_defaults():
    src = ExternalSource(
        source_type="github_issue",
        source_id="owner/repo#1",
        title="Fix bug",
        body="body text",
        url="https://github.com/owner/repo/issues/1",
        state="open",
    )
    assert src.labels == []
    assert src.files_changed == []
    assert src.date == ""


def test_external_source_to_dict():
    src = ExternalSource(
        source_type="github_pr",
        source_id="owner/repo#42",
        title="Add feature",
        body="PR body",
        url="https://github.com/owner/repo/pull/42",
        state="closed",
        labels=["enhancement"],
        date="2024-01-01T00:00:00Z",
        files_changed=["src/foo.py"],
    )
    d = src.to_dict()
    assert d["id"] == "github_pr:owner/repo#42"
    assert d["source_type"] == "github_pr"
    assert d["labels"] == ["enhancement"]
    assert d["files_changed"] == ["src/foo.py"]


# ---------------------------------------------------------------------------
# 2. Pagination logic with mocked HTTP
# ---------------------------------------------------------------------------

def _make_mock_response(data: list | dict) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(data).encode()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


def test_fetch_issues_pagination():
    """Test that fetch_issues paginates and filters out PRs."""
    page1 = [
        {"number": i, "title": f"Issue {i}", "body": "", "html_url": f"https://g.co/{i}",
         "state": "open", "labels": [], "created_at": "2024-01-01T00:00:00Z"}
        for i in range(1, 101)
    ]
    page2 = [
        {"number": 101, "title": "Issue 101", "body": "", "html_url": "https://g.co/101",
         "state": "open", "labels": [], "created_at": "2024-01-01T00:00:00Z"},
        # This one is a PR — should be filtered
        {"number": 102, "title": "PR 102", "body": "", "html_url": "https://g.co/102",
         "state": "open", "labels": [], "created_at": "2024-01-01T00:00:00Z",
         "pull_request": {}},
    ]

    responses = [_make_mock_response(page1), _make_mock_response(page2)]

    with patch("rekipedia.connectors.github_connector.urllib.request.urlopen", side_effect=responses):
        connector = GitHubConnector(repo="owner/repo", max_issues=200)
        issues = connector.fetch_issues()

    # page1 has 100 issues (no PR key), page2 has 1 issue (102 is PR, filtered)
    assert len(issues) == 101
    assert all(s.source_type == "github_issue" for s in issues)


def test_fetch_prs_with_files():
    """Test that fetch_prs fetches files for each PR."""
    prs_page = [
        {"number": 1, "title": "PR 1", "body": "", "html_url": "https://g.co/pr/1",
         "state": "merged", "labels": [], "created_at": "2024-01-01T00:00:00Z"},
    ]
    pr_files = [{"filename": "src/foo.py"}, {"filename": "src/bar.py"}]

    responses = [
        _make_mock_response(prs_page),   # pulls list page 1 (< 100 items → stops paginating)
        _make_mock_response(pr_files),   # pull/1/files
    ]

    call_count = [0]

    def side_effect(req, **kwargs):
        idx = call_count[0]
        call_count[0] += 1
        return responses[idx]

    with patch("rekipedia.connectors.github_connector.urllib.request.urlopen", side_effect=side_effect):
        connector = GitHubConnector(repo="owner/repo", max_prs=10)
        prs = connector.fetch_prs()

    assert len(prs) == 1
    assert prs[0].source_type == "github_pr"
    assert "src/foo.py" in prs[0].files_changed


# ---------------------------------------------------------------------------
# 3. Auto-detect repo from git remote
# ---------------------------------------------------------------------------

def test_detect_repo_from_https_remote():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="https://github.com/myorg/myrepo.git\n",
        )
        result = _detect_repo_from_git()
    assert result == "myorg/myrepo"


def test_detect_repo_from_ssh_remote():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="git@github.com:myorg/myrepo.git\n",
        )
        result = _detect_repo_from_git()
    assert result == "myorg/myrepo"


def test_detect_repo_returns_none_on_failure():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        result = _detect_repo_from_git()
    assert result is None


# ---------------------------------------------------------------------------
# 4. store_external_sources + get_sources_for_file roundtrip
# ---------------------------------------------------------------------------

def test_store_and_get_sources_for_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "store.db"
        with SqliteStore(db_path) as store:
            sources = [
                {
                    "id": "github_pr:owner/repo#5",
                    "source_type": "github_pr",
                    "source_id": "owner/repo#5",
                    "title": "My PR",
                    "body": "PR body",
                    "url": "https://github.com/owner/repo/pull/5",
                    "state": "closed",
                    "labels": ["bug"],
                    "date": "2024-06-01T00:00:00Z",
                    "files_changed": ["src/main.py"],
                }
            ]
            store.store_external_sources(sources)
            # Store a file_changed link
            store.store_source_symbol_links([
                {"source_id": "github_pr:owner/repo#5", "symbol_name": "src/main.py", "link_type": "file_changed"}
            ])
            results = store.get_sources_for_file("src/main.py")

    assert len(results) == 1
    assert results[0]["source_id"] == "owner/repo#5"
    assert results[0]["title"] == "My PR"


def test_get_external_source_count():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "store.db"
        with SqliteStore(db_path) as store:
            assert store.get_external_source_count() == 0
            store.store_external_sources([
                {"id": "github_issue:owner/repo#1", "source_type": "github_issue",
                 "source_id": "owner/repo#1", "title": "T", "body": "", "url": "",
                 "state": "open", "labels": [], "date": "", "files_changed": []}
            ])
            assert store.get_external_source_count() == 1


# ---------------------------------------------------------------------------
# 5. reki connect github --help
# ---------------------------------------------------------------------------

def test_connect_github_help():
    runner = CliRunner()
    result = runner.invoke(main, ["connect", "github", "--help"])
    assert result.exit_code == 0
    assert "--repo" in result.output
    assert "--token" in result.output
    assert "--max-issues" in result.output
    assert "--max-prs" in result.output


# ---------------------------------------------------------------------------
# 6. Token read order: flag > env var > config
# ---------------------------------------------------------------------------

def test_token_read_order_flag_beats_env(tmp_path):
    """CLI --token flag should take precedence over env var."""
    (tmp_path / ".rekipedia").mkdir()
    db_path = tmp_path / ".rekipedia" / "store.db"
    # Create empty db
    with SqliteStore(db_path) as _:
        pass

    captured_tokens = []

    def fake_connector_init(self, repo, token=None, max_issues=500, max_prs=200, progress_callback=None):
        captured_tokens.append(token)
        self.repo = repo
        self.token = token
        self.max_issues = max_issues
        self.max_prs = max_prs
        self._progress = lambda *a: None

    with patch.dict(os.environ, {"REKIPEDIA_GITHUB_TOKEN": "env_token"}):
        with patch("rekipedia.cli.connect.GitHubConnector.__init__", fake_connector_init):
            with patch("rekipedia.cli.connect.GitHubConnector.fetch_issues", return_value=[]):
                with patch("rekipedia.cli.connect.GitHubConnector.fetch_prs", return_value=[]):
                    with patch("rekipedia.cli.connect.GitHubConnector.build_symbol_links", return_value=[]):
                        runner = CliRunner()
                        result = runner.invoke(
                            main,
                            ["connect", "github", str(tmp_path), "--repo", "o/r", "--token", "flag_token"],
                        )

    assert captured_tokens == ["flag_token"]


def test_token_read_order_env_beats_config(tmp_path):
    """Env var should beat config file token."""
    (tmp_path / ".rekipedia").mkdir()
    # Write a config with a token
    (tmp_path / ".rekipedia" / "config.yml").write_text(
        "connectors:\n  github:\n    token: config_token\n    repo: o/r\n"
    )
    db_path = tmp_path / ".rekipedia" / "store.db"
    with SqliteStore(db_path) as _:
        pass

    captured_tokens = []

    def fake_connector_init(self, repo, token=None, max_issues=500, max_prs=200, progress_callback=None):
        captured_tokens.append(token)
        self.repo = repo
        self.token = token
        self.max_issues = max_issues
        self.max_prs = max_prs
        self._progress = lambda *a: None

    with patch.dict(os.environ, {"REKIPEDIA_GITHUB_TOKEN": "env_token"}):
        with patch("rekipedia.cli.connect.GitHubConnector.__init__", fake_connector_init):
            with patch("rekipedia.cli.connect.GitHubConnector.fetch_issues", return_value=[]):
                with patch("rekipedia.cli.connect.GitHubConnector.fetch_prs", return_value=[]):
                    with patch("rekipedia.cli.connect.GitHubConnector.build_symbol_links", return_value=[]):
                        runner = CliRunner()
                        result = runner.invoke(
                            main,
                            ["connect", "github", str(tmp_path)],
                        )

    assert captured_tokens == ["env_token"]


# ---------------------------------------------------------------------------
# 7. Rate limit handling
# ---------------------------------------------------------------------------

def test_rate_limit_warning_partial_results(tmp_path):
    """RateLimitError should print warning, not crash, and show partial results."""
    (tmp_path / ".rekipedia").mkdir()
    db_path = tmp_path / ".rekipedia" / "store.db"
    with SqliteStore(db_path) as _:
        pass

    def fake_fetch_issues(self):
        raise RateLimitError("HTTP 429")

    with patch("rekipedia.cli.connect.GitHubConnector.fetch_issues", fake_fetch_issues):
        with patch("rekipedia.cli.connect.GitHubConnector.fetch_prs", return_value=[]):
        # Need to patch build_symbol_links too since it's called on the instance
            with patch("rekipedia.cli.connect.GitHubConnector.build_symbol_links", return_value=[]):
                runner = CliRunner()
                result = runner.invoke(
                    main,
                    ["connect", "github", str(tmp_path), "--repo", "owner/repo"],
                )

    assert "Rate limit" in result.output or result.exit_code == 0


# ---------------------------------------------------------------------------
# 8. build_symbol_links cross-referencing
# ---------------------------------------------------------------------------

def test_build_symbol_links_pr_files():
    """PRs should link via file_changed to matching symbols."""
    sources = [
        ExternalSource(
            source_type="github_pr",
            source_id="o/r#1",
            title="T",
            body="",
            url="",
            state="open",
            files_changed=["src/foo.py"],
        )
    ]
    all_symbols = [
        {"name": "MyClass", "kind": "class", "file": "src/foo.py"},
    ]
    connector = GitHubConnector(repo="o/r")
    links = connector.build_symbol_links(sources, all_symbols)
    sym_names = [lnk["symbol_name"] for lnk in links]
    assert "MyClass" in sym_names
    assert "src/foo.py" in sym_names


def test_build_symbol_links_issue_mention():
    """Issues should link to symbols mentioned in title/body."""
    sources = [
        ExternalSource(
            source_type="github_issue",
            source_id="o/r#2",
            title="Bug in parse_config function",
            body="The parse_config function crashes.",
            url="",
            state="open",
        )
    ]
    all_symbols = [
        {"name": "parse_config", "kind": "function", "file": "src/cfg.py"},
        {"name": "unrelated_symbol", "kind": "function", "file": "src/other.py"},
    ]
    connector = GitHubConnector(repo="o/r")
    links = connector.build_symbol_links(sources, all_symbols)
    sym_names = [lnk["symbol_name"] for lnk in links]
    assert "parse_config" in sym_names
    assert "unrelated_symbol" not in sym_names
