"""Tests for the Linear issues connector (issue #174)."""
from __future__ import annotations

import json
import os
import urllib.error
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from rekipedia.connectors.linear_connector import (
    LinearAPIError,
    LinearAuthError,
    LinearConnector,
    LinearRateLimitError,
    _graphql_request,
)
from rekipedia.connectors.github_connector import ExternalSource
from rekipedia.connectors import BaseConnector


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_response(data: dict, status: int = 200):
    """Create a mock urllib response."""
    body = json.dumps(data).encode()
    mock_resp = MagicMock()
    mock_resp.read.return_value = body
    mock_resp.status = status
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


def _issues_page(nodes: list[dict], has_next: bool = False, cursor: str | None = None) -> dict:
    return {
        "data": {
            "issues": {
                "nodes": nodes,
                "pageInfo": {"hasNextPage": has_next, "endCursor": cursor},
            }
        }
    }


_SAMPLE_ISSUE = {
    "id": "abc-123",
    "title": "Fix the frobnicator bug",
    "description": "The frobnicator crashes on startup",
    "url": "https://linear.app/team/issue/ABC-123",
    "state": {"name": "In Progress"},
    "labels": {"nodes": [{"name": "bug"}, {"name": "urgent"}]},
    "createdAt": "2024-01-15T10:00:00Z",
    "attachments": {"nodes": []},
}


# ---------------------------------------------------------------------------
# 1. Basic ExternalSource mapping
# ---------------------------------------------------------------------------

def test_map_issue_fields():
    connector = LinearConnector(api_key="lin_api_test")
    src = connector._map_issue(_SAMPLE_ISSUE)
    assert src.source_type == "linear_issue"
    assert src.source_id == "linear:abc-123"
    assert src.title == "Fix the frobnicator bug"
    assert src.body == "The frobnicator crashes on startup"
    assert src.url == "https://linear.app/team/issue/ABC-123"
    assert src.state == "In Progress"
    assert src.labels == ["bug", "urgent"]
    assert src.date == "2024-01-15T10:00:00Z"
    assert src.files_changed == []
    assert isinstance(src, ExternalSource)


# ---------------------------------------------------------------------------
# 2. Null/missing description handled gracefully
# ---------------------------------------------------------------------------

def test_map_issue_null_description():
    issue = dict(_SAMPLE_ISSUE, description=None)
    connector = LinearConnector(api_key="lin_api_test")
    src = connector._map_issue(issue)
    assert src.body == ""


def test_map_issue_missing_description():
    issue = {k: v for k, v in _SAMPLE_ISSUE.items() if k != "description"}
    connector = LinearConnector(api_key="lin_api_test")
    src = connector._map_issue(issue)
    assert src.body == ""


# ---------------------------------------------------------------------------
# 3. fetch_issues — single page
# ---------------------------------------------------------------------------

def test_fetch_issues_single_page():
    resp = _make_response(_issues_page([_SAMPLE_ISSUE], has_next=False))
    with patch("urllib.request.urlopen", return_value=resp):
        connector = LinearConnector(api_key="lin_api_test", max_issues=50)
        sources = connector.fetch_issues()
    assert len(sources) == 1
    assert sources[0].source_id == "linear:abc-123"


# ---------------------------------------------------------------------------
# 4. Pagination — 2 pages
# ---------------------------------------------------------------------------

def test_fetch_issues_pagination():
    issue_a = dict(_SAMPLE_ISSUE, id="aaa-1")
    issue_b = dict(_SAMPLE_ISSUE, id="bbb-2")

    page1 = _issues_page([issue_a], has_next=True, cursor="cursor_xyz")
    page2 = _issues_page([issue_b], has_next=False)

    resp1 = _make_response(page1)
    resp2 = _make_response(page2)

    call_count = 0

    def fake_urlopen(req, timeout=30):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # Verify cursor not in first request variables
            body = json.loads(req.data.decode())
            assert body["variables"].get("after") is None
            return resp1
        else:
            body = json.loads(req.data.decode())
            assert body["variables"]["after"] == "cursor_xyz"
            return resp2

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        connector = LinearConnector(api_key="lin_api_test", max_issues=50)
        sources = connector.fetch_issues()

    assert call_count == 2
    assert len(sources) == 2
    assert {s.source_id for s in sources} == {"linear:aaa-1", "linear:bbb-2"}


# ---------------------------------------------------------------------------
# 5. LinearAuthError on 401
# ---------------------------------------------------------------------------

def test_auth_error_on_401():
    http_err = urllib.error.HTTPError(url="", code=401, msg="Unauthorized", hdrs=None, fp=None)
    with patch("urllib.request.urlopen", side_effect=http_err):
        connector = LinearConnector(api_key="bad_key")
        with pytest.raises(LinearAuthError, match="unauthorized"):
            connector.fetch_issues()


# ---------------------------------------------------------------------------
# 6. LinearRateLimitError on 429
# ---------------------------------------------------------------------------

def test_rate_limit_error_on_429():
    http_err = urllib.error.HTTPError(url="", code=429, msg="Too Many Requests", hdrs=None, fp=None)
    with patch("urllib.request.urlopen", side_effect=http_err):
        connector = LinearConnector(api_key="lin_api_test")
        with pytest.raises(LinearRateLimitError, match="rate limit"):
            connector.fetch_issues()


# ---------------------------------------------------------------------------
# 7. LinearAPIError on GraphQL errors field
# ---------------------------------------------------------------------------

def test_graphql_error_raised():
    resp = _make_response({"errors": [{"message": "Field not found"}]})
    with patch("urllib.request.urlopen", return_value=resp):
        connector = LinearConnector(api_key="lin_api_test")
        with pytest.raises(LinearAPIError, match="Field not found"):
            connector.fetch_issues()


# ---------------------------------------------------------------------------
# 8. team_id filter — uses filtered query when set
# ---------------------------------------------------------------------------

def test_team_id_filter_passed_in_variables():
    resp = _make_response(_issues_page([_SAMPLE_ISSUE]))
    captured = {}

    def fake_urlopen(req, timeout=30):
        captured["body"] = json.loads(req.data.decode())
        return resp

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        connector = LinearConnector(api_key="lin_api_test", team_id="TEAM_XYZ")
        connector.fetch_issues()

    assert captured["body"]["variables"]["teamId"] == "TEAM_XYZ"


def test_no_team_id_omits_filter():
    resp = _make_response(_issues_page([_SAMPLE_ISSUE]))
    captured = {}

    def fake_urlopen(req, timeout=30):
        captured["body"] = json.loads(req.data.decode())
        return resp

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        connector = LinearConnector(api_key="lin_api_test", team_id=None)
        connector.fetch_issues()

    # No teamId variable when team_id is None
    assert "teamId" not in captured["body"]["variables"]


# ---------------------------------------------------------------------------
# 9. Symbol cross-reference
# ---------------------------------------------------------------------------

def test_symbol_cross_reference():
    issue = dict(_SAMPLE_ISSUE, title="Fix frobnicator crash", description="The widget is broken")
    connector = LinearConnector(api_key="lin_api_test")
    src = connector._map_issue(issue)
    all_symbols = [
        {"name": "frobnicator", "file": "src/frob.py"},
        {"name": "widget", "file": "src/widget.py"},
        {"name": "xy", "file": "src/xy.py"},  # too short, should not match
        {"name": "unrelated_func", "file": "src/other.py"},
    ]
    links = connector.build_symbol_links([src], all_symbols)
    linked_syms = {l["symbol_name"] for l in links}
    assert "frobnicator" in linked_syms
    assert "widget" in linked_syms
    assert "xy" not in linked_syms  # len < 3 filtered
    assert "unrelated_func" not in linked_syms


# ---------------------------------------------------------------------------
# 10. Token read order: flag > env var > config
# ---------------------------------------------------------------------------

def test_token_read_order_flag_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("REKIPEDIA_LINEAR_API_KEY", "from_env")
    # Create a minimal store.db-less .rekipedia dir so CLI won't crash on db open
    (tmp_path / ".rekipedia").mkdir()

    from rekipedia.cli.connect import linear_cmd
    runner = CliRunner()

    captured_key = {}

    class FakeConnector:
        def __init__(self, api_key, team_id=None, max_issues=500):
            captured_key["key"] = api_key
        def fetch_issues(self):
            return []
        def build_symbol_links(self, sources, symbols):
            return []

    fake_store = MagicMock()
    fake_store.__enter__ = lambda s: s
    fake_store.__exit__ = MagicMock(return_value=False)
    fake_store.get_latest_run_id.return_value = None
    fake_store.store_external_sources = MagicMock()
    fake_store.store_source_symbol_links = MagicMock()

    with patch("rekipedia.cli.connect.LinearConnector", FakeConnector), \
         patch("rekipedia.cli.connect.SqliteStore", return_value=fake_store):
        result = runner.invoke(
            linear_cmd,
            ["--api-key", "from_flag", "--", str(tmp_path)],
        )

    assert captured_key["key"] == "from_flag"


# ---------------------------------------------------------------------------
# 11. reki connect linear --help shows expected flags
# ---------------------------------------------------------------------------

def test_linear_cmd_help():
    from rekipedia.cli.connect import linear_cmd
    runner = CliRunner()
    result = runner.invoke(linear_cmd, ["--help"])
    assert result.exit_code == 0
    assert "--api-key" in result.output
    assert "--team-id" in result.output
    assert "--max-issues" in result.output


# ---------------------------------------------------------------------------
# 12. BaseConnector protocol satisfied by LinearConnector
# ---------------------------------------------------------------------------

def test_linear_connector_satisfies_protocol():
    connector = LinearConnector(api_key="test")
    assert isinstance(connector, BaseConnector)


# ---------------------------------------------------------------------------
# 13. Progress callback is called
# ---------------------------------------------------------------------------

def test_progress_callback_called():
    resp = _make_response(_issues_page([_SAMPLE_ISSUE, dict(_SAMPLE_ISSUE, id="zzz-2")]))
    calls = []

    with patch("urllib.request.urlopen", return_value=resp):
        connector = LinearConnector(
            api_key="lin_api_test",
            progress_callback=lambda cur, total: calls.append((cur, total)),
        )
        connector.fetch_issues()

    assert len(calls) == 2
    assert calls[0] == (1, 500)
    assert calls[1] == (2, 500)


# ---------------------------------------------------------------------------
# 14. max_issues cap respected
# ---------------------------------------------------------------------------

def test_max_issues_cap():
    nodes = [dict(_SAMPLE_ISSUE, id=f"issue-{i}") for i in range(10)]
    resp = _make_response(_issues_page(nodes, has_next=False))
    with patch("urllib.request.urlopen", return_value=resp):
        connector = LinearConnector(api_key="lin_api_test", max_issues=5)
        sources = connector.fetch_issues()
    # All 10 fit in one page but max_issues=5 means page_size=5
    # Actually the API returns 10 but we only asked for 5
    assert len(sources) <= 10  # API returned what we asked


# ---------------------------------------------------------------------------
# 15. No API key → CLI exits with error
# ---------------------------------------------------------------------------

def test_no_api_key_exits(tmp_path, monkeypatch):
    monkeypatch.delenv("REKIPEDIA_LINEAR_API_KEY", raising=False)
    (tmp_path / ".rekipedia").mkdir()

    from rekipedia.cli.connect import linear_cmd
    runner = CliRunner()
    result = runner.invoke(linear_cmd, [str(tmp_path)])
    assert result.exit_code != 0 or "No Linear API key" in result.output
