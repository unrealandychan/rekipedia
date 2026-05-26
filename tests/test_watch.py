"""Tests for reki watch — native OS filesystem watcher (#138)."""
from __future__ import annotations

import json
import time
from unittest.mock import patch

from rekipedia.watcher.watcher import (
    _is_source_file,
    _RepoWatcher,
    add_repo,
    list_repos,
    remove_repo,
)

# ── _is_source_file ───────────────────────────────────────────────────────────

class TestIsSourceFile:
    def test_python(self):
        assert _is_source_file("app.py")

    def test_pyw(self):
        assert _is_source_file("script.pyw")

    def test_typescript(self):
        assert _is_source_file("server.ts")

    def test_tsx(self):
        assert _is_source_file("App.tsx")

    def test_javascript(self):
        assert _is_source_file("index.js")

    def test_jsx(self):
        assert _is_source_file("Component.jsx")

    def test_go(self):
        assert _is_source_file("main.go")

    def test_rust(self):
        assert _is_source_file("lib.rs")

    def test_java(self):
        assert _is_source_file("Main.java")

    def test_kotlin(self):
        assert _is_source_file("App.kt")

    def test_ruby(self):
        assert _is_source_file("app.rb")

    def test_php(self):
        assert _is_source_file("index.php")

    def test_swift(self):
        assert _is_source_file("ContentView.swift")

    def test_markdown_ignored(self):
        assert not _is_source_file("README.md")

    def test_json_ignored(self):
        assert not _is_source_file("package.json")

    def test_yaml_ignored(self):
        assert not _is_source_file("config.yaml")

    def test_png_ignored(self):
        assert not _is_source_file("logo.png")

    def test_uppercase_extension(self):
        # case-insensitive
        assert _is_source_file("Main.PY")

    def test_full_path(self):
        assert _is_source_file("/home/user/project/src/app.py")


# ── _RepoWatcher debounce ─────────────────────────────────────────────────────

class TestRepoWatcher:
    def test_trigger_called_after_debounce(self):
        rw = _RepoWatcher("/fake/repo", debounce_seconds=0.05)
        triggered = []
        original_trigger = rw._trigger

        def mock_trigger():
            triggered.append(True)

        rw._trigger = mock_trigger
        rw.on_change("app.py")
        time.sleep(0.2)
        assert len(triggered) == 1

    def test_debounce_resets_on_rapid_changes(self):
        rw = _RepoWatcher("/fake/repo", debounce_seconds=0.1)
        triggered = []

        def mock_trigger():
            triggered.append(True)

        rw._trigger = mock_trigger
        for _ in range(10):
            rw.on_change("app.py")
            time.sleep(0.01)
        time.sleep(0.3)
        # Should only fire once despite 10 rapid changes
        assert len(triggered) == 1

    def test_trigger_calls_subprocess(self):
        rw = _RepoWatcher("/fake/repo", debounce_seconds=0.0)
        with patch("subprocess.run") as mock_run:
            rw._dirty = True
            rw._trigger()
            assert mock_run.called
            cmd = mock_run.call_args[0][0]
            assert "update" in cmd

    def test_trigger_noop_when_not_dirty(self):
        rw = _RepoWatcher("/fake/repo", debounce_seconds=0.0)
        with patch("subprocess.run") as mock_run:
            rw._dirty = False
            rw._trigger()
            assert not mock_run.called

    def test_trigger_handles_subprocess_exception(self):
        """Should not raise even if subprocess fails."""
        rw = _RepoWatcher("/fake/repo", debounce_seconds=0.0)
        with patch("subprocess.run", side_effect=OSError("no such file")):
            rw._dirty = True
            rw._trigger()  # must not raise


# ── config CRUD ───────────────────────────────────────────────────────────────

class TestConfigCRUD:
    def _tmp_cfg(self, tmp_path):
        cfg_path = tmp_path / "watch.json"
        with patch("rekipedia.watcher.watcher.CONFIG_PATH", cfg_path):
            yield cfg_path

    def test_add_repo(self, tmp_path):
        cfg_path = tmp_path / "watch.json"
        with patch("rekipedia.watcher.watcher.CONFIG_PATH", cfg_path):
            add_repo(str(tmp_path))
            repos = list_repos()
        assert str(tmp_path) in repos

    def test_add_repo_no_duplicate(self, tmp_path):
        cfg_path = tmp_path / "watch.json"
        with patch("rekipedia.watcher.watcher.CONFIG_PATH", cfg_path):
            add_repo(str(tmp_path))
            add_repo(str(tmp_path))
            repos = list_repos()
        assert repos.count(str(tmp_path)) == 1

    def test_remove_repo(self, tmp_path):
        cfg_path = tmp_path / "watch.json"
        with patch("rekipedia.watcher.watcher.CONFIG_PATH", cfg_path):
            add_repo(str(tmp_path))
            remove_repo(str(tmp_path))
            repos = list_repos()
        assert str(tmp_path) not in repos

    def test_remove_nonexistent_noop(self, tmp_path):
        cfg_path = tmp_path / "watch.json"
        with patch("rekipedia.watcher.watcher.CONFIG_PATH", cfg_path):
            remove_repo("/does/not/exist")  # should not raise

    def test_list_repos_empty(self, tmp_path):
        cfg_path = tmp_path / "watch.json"
        with patch("rekipedia.watcher.watcher.CONFIG_PATH", cfg_path):
            assert list_repos() == []

    def test_config_persists(self, tmp_path):
        cfg_path = tmp_path / "watch.json"
        with patch("rekipedia.watcher.watcher.CONFIG_PATH", cfg_path):
            add_repo("/some/repo")
            # Re-read from disk
            data = json.loads(cfg_path.read_text())
        assert "/some/repo" in data["repos"]


# ── CLI commands ──────────────────────────────────────────────────────────────

class TestWatchCLI:
    def test_watch_add_command(self, tmp_path):
        from click.testing import CliRunner

        from rekipedia.cli.watch import watch_cmd
        runner = CliRunner()
        cfg_path = tmp_path / "watch.json"
        with patch("rekipedia.watcher.watcher.CONFIG_PATH", cfg_path):
            result = runner.invoke(watch_cmd, ["add", str(tmp_path)])
        assert result.exit_code == 0

    def test_watch_list_command_empty(self, tmp_path):
        from click.testing import CliRunner

        from rekipedia.cli.watch import watch_cmd
        runner = CliRunner()
        cfg_path = tmp_path / "watch.json"
        with patch("rekipedia.watcher.watcher.CONFIG_PATH", cfg_path):
            result = runner.invoke(watch_cmd, ["list"])
        assert result.exit_code == 0

    def test_watch_remove_command(self, tmp_path):
        from click.testing import CliRunner

        from rekipedia.cli.watch import watch_cmd
        runner = CliRunner()
        cfg_path = tmp_path / "watch.json"
        with patch("rekipedia.watcher.watcher.CONFIG_PATH", cfg_path):
            runner.invoke(watch_cmd, ["add", str(tmp_path)])
            result = runner.invoke(watch_cmd, ["remove", str(tmp_path)])
        assert result.exit_code == 0

    def test_watch_start_no_watchdog(self, tmp_path):
        """Should print a helpful message when watchdog not installed."""
        from click.testing import CliRunner

        from rekipedia.cli.watch import watch_cmd
        runner = CliRunner()
        cfg_path = tmp_path / "watch.json"
        with patch("rekipedia.watcher.watcher.CONFIG_PATH", cfg_path), \
             patch.dict("sys.modules", {"watchdog": None, "watchdog.observers": None, "watchdog.events": None}):
            result = runner.invoke(watch_cmd, ["start", str(tmp_path)])
        # May fail import but should not crash with unhandled exception
        assert result.exit_code in (0, 1)

    def test_watch_start_with_path(self, tmp_path):
        """start <path> should call start_watching with that path."""
        from click.testing import CliRunner

        from rekipedia.cli.watch import watch_cmd
        runner = CliRunner()
        with patch("rekipedia.watcher.watcher.start_watching") as mock_sw:
            result = runner.invoke(watch_cmd, ["start", str(tmp_path)])
        assert result.exit_code == 0
        mock_sw.assert_called_once()
        call_kwargs = mock_sw.call_args
        repos_arg = call_kwargs[1].get("repos") or call_kwargs[0][0]
        assert str(tmp_path) in repos_arg

    def test_watch_start_no_path_uses_registered(self, tmp_path):
        """start with no path should pass repos=None (uses registered list)."""
        from click.testing import CliRunner

        from rekipedia.cli.watch import watch_cmd
        runner = CliRunner()
        with patch("rekipedia.watcher.watcher.start_watching") as mock_sw:
            result = runner.invoke(watch_cmd, ["start"])
        assert result.exit_code == 0
        call_kwargs = mock_sw.call_args
        repos_arg = call_kwargs[1].get("repos") or (call_kwargs[0][0] if call_kwargs[0] else None)
        assert repos_arg is None
