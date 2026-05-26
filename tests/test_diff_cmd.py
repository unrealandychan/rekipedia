"""Tests for reki diff command (uncommitted-change impact analysis)."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from click.testing import CliRunner

from rekipedia.cli.diff import diff_cmd

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_run(stdout: str, returncode: int = 0):
    m = SimpleNamespace(stdout=stdout, returncode=returncode, stderr="")
    return m


def _make_store(tmp_path: Path, symbols: list[dict] | None = None) -> Path:
    """Create a minimal .rekipedia/store.db matching SqliteStore's schema."""
    reki_dir = tmp_path / ".rekipedia"
    reki_dir.mkdir(parents=True, exist_ok=True)
    db = reki_dir / "store.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS scan_runs "
        "(id TEXT PRIMARY KEY, repo_path TEXT, status TEXT, started_at TEXT, finished_at TEXT)"
    )
    conn.execute(
        "INSERT INTO scan_runs VALUES ('run1', ?, 'success', '2026-01-01', '2026-01-01')",
        (str(tmp_path),),
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS scan_symbols "
        "(run_id TEXT, name TEXT, kind TEXT, file TEXT, line_start INTEGER, "
        "line_end INTEGER, signature TEXT, docstring TEXT, "
        "PRIMARY KEY(run_id, name, file))"
    )
    for sym in symbols or []:
        conn.execute(
            "INSERT OR REPLACE INTO scan_symbols(run_id, name, kind, file, line_start) "
            "VALUES (?, ?, ?, ?, ?)",
            ("run1", sym.get("name", "fn"), sym.get("kind", "function"),
             sym.get("file", "src/foo.py"), sym.get("line", 1)),
        )
    conn.commit()
    conn.close()
    (tmp_path / ".git").mkdir(exist_ok=True)
    return db


# ---------------------------------------------------------------------------
# Unit: _get_changed_files
# ---------------------------------------------------------------------------

def test_get_changed_files_staged():
    """--staged passes --cached to git diff."""
    from rekipedia.cli.diff import _get_changed_files
    with patch("rekipedia.cli.diff.subprocess.run") as mock:
        mock.return_value = _mock_run("src/foo.py\n")
        result = _get_changed_files(Path(), staged=True, base=None)
    call_args = mock.call_args[0][0]
    assert "--cached" in call_args
    assert result == ["src/foo.py"]


def test_get_changed_files_base():
    """--base passes the ref to git diff."""
    from rekipedia.cli.diff import _get_changed_files
    with patch("rekipedia.cli.diff.subprocess.run") as mock:
        mock.return_value = _mock_run("src/bar.py\n")
        _get_changed_files(Path(), staged=False, base="HEAD~3")
    call_args = mock.call_args[0][0]
    assert "HEAD~3" in call_args


def test_get_changed_files_no_staged_no_base():
    """Without --staged or --base, both staged and unstaged are returned (union)."""
    from rekipedia.cli.diff import _get_changed_files
    calls = [_mock_run("a.py\n"), _mock_run("b.py\n")]
    with patch("rekipedia.cli.diff.subprocess.run", side_effect=calls):
        result = _get_changed_files(Path(), staged=False, base=None)
    # Union of a.py + b.py
    assert set(result) == {"a.py", "b.py"}


# ---------------------------------------------------------------------------
# Unit: _risk_tier
# ---------------------------------------------------------------------------

def test_risk_tier():
    from rekipedia.cli.diff import _risk_tier
    # _risk_tier returns (label, emoji)
    assert _risk_tier(0)[0] == "LOW"
    assert _risk_tier(1)[0] == "LOW"
    assert _risk_tier(2)[0] == "MEDIUM"
    assert _risk_tier(4)[0] == "MEDIUM"
    assert _risk_tier(5)[0] == "HIGH"
    assert _risk_tier(100)[0] == "HIGH"


# ---------------------------------------------------------------------------
# CLI: integration
# ---------------------------------------------------------------------------

def test_diff_cmd_no_scan(tmp_path):
    """No .rekipedia/store.db → helpful error message."""
    (tmp_path / ".git").mkdir()
    runner = CliRunner()
    with patch("rekipedia.cli.diff.subprocess.run") as mock:
        mock.return_value = _mock_run("", 0)
        result = runner.invoke(diff_cmd, [str(tmp_path)])
    assert "scan" in result.output.lower() or "❌" in result.output or result.exit_code != 0


def test_diff_cmd_no_changes(tmp_path):
    """Git returns empty → 'No changes detected'."""
    _make_store(tmp_path)
    runner = CliRunner()

    def fake_run(cmd, **kwargs):
        if "rev-parse" in cmd:
            return _mock_run(".git", 0)
        return _mock_run("", 0)

    with patch("rekipedia.cli.diff.subprocess.run", side_effect=fake_run):
        result = runner.invoke(diff_cmd, [str(tmp_path)])
    assert "No changes" in result.output


def test_diff_cmd_text_output(tmp_path):
    """Text output shows risk tier information."""
    _make_store(tmp_path, symbols=[{"name": "my_func", "file": "src/foo.py"}])
    runner = CliRunner()

    def fake_run(cmd, **kwargs):
        if "rev-parse" in cmd:
            return _mock_run(".git", 0)
        return _mock_run("src/foo.py\n", 0)

    fake_impact = {
        "results": [
            {"symbol": "caller_a", "depth": 1, "file": "other.py"},
            {"symbol": "caller_b", "depth": 1, "file": "other2.py"},
            {"symbol": "caller_c", "depth": 2, "file": "third.py"},
            {"symbol": "caller_d", "depth": 2, "file": "fourth.py"},
            {"symbol": "caller_e", "depth": 3, "file": "fifth.py"},
        ]
    }

    with patch("rekipedia.cli.diff.subprocess.run", side_effect=fake_run), \
         patch("rekipedia.cli.diff._compute_transitive_impact", return_value=fake_impact):
        result = runner.invoke(diff_cmd, [str(tmp_path)])

    assert result.exit_code == 0
    assert "HIGH" in result.output or "MEDIUM" in result.output or "LOW" in result.output


def test_diff_cmd_json_output(tmp_path):
    """JSON output is valid and contains 'results' key."""
    _make_store(tmp_path, symbols=[{"name": "my_func", "file": "src/foo.py"}])
    runner = CliRunner()

    def fake_run(cmd, **kwargs):
        if "rev-parse" in cmd:
            return _mock_run(".git", 0)
        return _mock_run("src/foo.py\n", 0)

    with patch("rekipedia.cli.diff.subprocess.run", side_effect=fake_run), \
         patch("rekipedia.cli.diff._compute_transitive_impact", return_value={"results": []}):
        result = runner.invoke(diff_cmd, [str(tmp_path), "--format", "json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "results" in data


def test_diff_cmd_staged_flag(tmp_path):
    """--staged flag is forwarded to _get_changed_files."""
    _make_store(tmp_path)
    runner = CliRunner()
    with patch("rekipedia.cli.diff._get_changed_files", return_value=[]) as mock_gcf, \
         patch("rekipedia.cli.diff.subprocess.run", return_value=_mock_run(".git", 0)):
        runner.invoke(diff_cmd, [str(tmp_path), "--staged"])
    mock_gcf.assert_called_once()
    _, kwargs = mock_gcf.call_args
    assert kwargs.get("staged") is True or mock_gcf.call_args[0][1] is True


def test_diff_cmd_base_flag(tmp_path):
    """--base flag is forwarded to _get_changed_files."""
    _make_store(tmp_path)
    runner = CliRunner()
    with patch("rekipedia.cli.diff._get_changed_files", return_value=[]) as mock_gcf, \
         patch("rekipedia.cli.diff.subprocess.run", return_value=_mock_run(".git", 0)):
        runner.invoke(diff_cmd, [str(tmp_path), "--base", "HEAD~2"])
    mock_gcf.assert_called_once()
    args, kwargs = mock_gcf.call_args
    assert "HEAD~2" in args or kwargs.get("base") == "HEAD~2"
