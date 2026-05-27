"""Tests for reki watch status — issue #178."""
from __future__ import annotations

import json
import pytest
from click.testing import CliRunner
from unittest.mock import patch


@pytest.fixture(autouse=True)
def isolated_status(tmp_path, monkeypatch):
    """Redirect STATUS_PATH and CONFIG_PATH to tmp dirs."""
    import rekipedia.watcher.watcher as watcher_mod
    status_file = tmp_path / "watch_status.json"
    config_file = tmp_path / "watch.json"
    monkeypatch.setattr(watcher_mod, "STATUS_PATH", status_file)
    monkeypatch.setattr(watcher_mod, "CONFIG_PATH", config_file)
    yield status_file, config_file


def test_update_repo_status_writes_data(isolated_status):
    from rekipedia.watcher.watcher import update_repo_status, _load_status

    update_repo_status("/repo/foo", success=True)
    status = _load_status()
    assert "/repo/foo" in status
    entry = status["/repo/foo"]
    assert entry["update_count"] == 1
    assert entry["last_error"] is None
    assert "last_updated" in entry


def test_update_count_increments(isolated_status):
    from rekipedia.watcher.watcher import update_repo_status, _load_status

    update_repo_status("/repo/bar", success=True)
    update_repo_status("/repo/bar", success=True)
    update_repo_status("/repo/bar", success=True)
    status = _load_status()
    assert status["/repo/bar"]["update_count"] == 3


def test_last_error_cleared_on_success(isolated_status):
    from rekipedia.watcher.watcher import update_repo_status, _load_status

    update_repo_status("/repo/baz", success=False, error="oops")
    status = _load_status()
    assert status["/repo/baz"]["last_error"] == "oops"

    update_repo_status("/repo/baz", success=True)
    status = _load_status()
    assert status["/repo/baz"]["last_error"] is None


def test_watch_status_cli_no_repos(isolated_status, monkeypatch):
    from rekipedia.cli.watch import watch_cmd

    runner = CliRunner()
    result = runner.invoke(watch_cmd, ["status"])
    assert result.exit_code == 0
    assert "No repos registered" in result.output


def test_watch_status_cli_with_repos(isolated_status, monkeypatch):
    from rekipedia.watcher.watcher import _save_config, _save_status
    from rekipedia.cli.watch import watch_cmd

    _save_config({"repos": ["/repo/alpha", "/repo/beta"]})
    _save_status({
        "/repo/alpha": {"last_updated": "2026-01-01T00:00:00+00:00", "update_count": 5, "last_error": None},
        "/repo/beta": {"last_updated": "2026-01-02T00:00:00+00:00", "update_count": 2, "last_error": "update failed"},
    })

    runner = CliRunner()
    result = runner.invoke(watch_cmd, ["status"])
    assert result.exit_code == 0
    assert "/repo/alpha" in result.output
    assert "/repo/beta" in result.output
    assert "update failed" in result.output
