"""Tests for smart diff feature in _RepoWatcher (issue #176)."""
from __future__ import annotations

import sys
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from rekipedia.watcher.watcher import _RepoWatcher, _SMART_DIFF_THRESHOLD


class TestSmartDiffAccumulation:
    """Test that _RepoWatcher accumulates changed paths during debounce window."""

    def test_accumulates_paths_during_debounce(self):
        watcher = _RepoWatcher("/tmp/repo", debounce_seconds=10.0)
        watcher.on_change("/tmp/repo/foo.py")
        watcher.on_change("/tmp/repo/bar.py")
        watcher.on_change("/tmp/repo/baz.py")

        with watcher._lock:
            assert watcher._changed_paths == {
                "/tmp/repo/foo.py",
                "/tmp/repo/bar.py",
                "/tmp/repo/baz.py",
            }
        # Cleanup
        if watcher._timer:
            watcher._timer.cancel()

    def test_same_path_added_once(self):
        watcher = _RepoWatcher("/tmp/repo", debounce_seconds=10.0)
        for _ in range(5):
            watcher.on_change("/tmp/repo/foo.py")

        with watcher._lock:
            assert watcher._changed_paths == {"/tmp/repo/foo.py"}
        if watcher._timer:
            watcher._timer.cancel()

    def test_paths_reset_after_trigger(self):
        triggered = threading.Event()
        captured_cmd = []

        def fake_subprocess_run(cmd, **kwargs):
            captured_cmd.extend(cmd)
            triggered.set()
            return MagicMock(returncode=0)

        with patch("rekipedia.watcher.watcher.subprocess.run", side_effect=fake_subprocess_run):
            watcher = _RepoWatcher("/tmp/repo", debounce_seconds=0.05)
            watcher.on_change("/tmp/repo/foo.py")
            triggered.wait(timeout=3.0)

        with watcher._lock:
            assert watcher._changed_paths == set()
            assert not watcher._dirty


class TestSmartDiffTargeted:
    """Test that ≤20 files trigger targeted update command."""

    def _run_trigger(self, paths):
        captured_cmd = []
        triggered = threading.Event()

        def fake_subprocess_run(cmd, **kwargs):
            captured_cmd.extend(cmd)
            triggered.set()
            return MagicMock(returncode=0)

        with patch("rekipedia.watcher.watcher.subprocess.run", side_effect=fake_subprocess_run):
            watcher = _RepoWatcher("/tmp/repo", debounce_seconds=0.05)
            for p in paths:
                watcher.on_change(p)
            triggered.wait(timeout=3.0)

        return captured_cmd

    def test_single_file_uses_targeted_update(self):
        cmd = self._run_trigger(["/tmp/repo/foo.py"])
        assert "update" in cmd
        assert "/tmp/repo/foo.py" in cmd

    def test_twenty_files_uses_targeted_update(self):
        paths = [f"/tmp/repo/file{i}.py" for i in range(20)]
        cmd = self._run_trigger(paths)
        assert "update" in cmd
        # All 20 files should appear in cmd
        for p in paths:
            assert p in cmd

    def test_five_files_uses_targeted_update(self):
        paths = [f"/tmp/repo/mod{i}.py" for i in range(5)]
        cmd = self._run_trigger(paths)
        assert "update" in cmd
        for p in paths:
            assert p in cmd

    def test_targeted_update_does_not_run_full_scan(self):
        """With ≤20 files, the command should have extra args beyond 'update'."""
        paths = ["/tmp/repo/a.py", "/tmp/repo/b.py"]
        cmd = self._run_trigger(paths)
        update_idx = cmd.index("update")
        extra_args = cmd[update_idx + 1:]
        assert len(extra_args) > 0, "Expected file paths after 'update' for targeted update"


class TestSmartDiffFallback:
    """Test that >20 files fall back to full reki update."""

    def test_twenty_one_files_uses_full_scan(self):
        captured_cmd = []
        triggered = threading.Event()

        def fake_subprocess_run(cmd, **kwargs):
            captured_cmd.extend(cmd)
            triggered.set()
            return MagicMock(returncode=0)

        paths = [f"/tmp/repo/file{i}.py" for i in range(21)]

        with patch("rekipedia.watcher.watcher.subprocess.run", side_effect=fake_subprocess_run):
            watcher = _RepoWatcher("/tmp/repo", debounce_seconds=0.05)
            for p in paths:
                watcher.on_change(p)
            triggered.wait(timeout=3.0)

        assert "update" in captured_cmd
        # No file paths should appear after 'update'
        update_idx = captured_cmd.index("update")
        extra_args = captured_cmd[update_idx + 1:]
        assert len(extra_args) == 0, f"Expected no extra args for >20 files, got: {extra_args}"

    def test_large_changeset_uses_full_scan(self):
        captured_cmd = []
        triggered = threading.Event()

        def fake_subprocess_run(cmd, **kwargs):
            captured_cmd.extend(cmd)
            triggered.set()
            return MagicMock(returncode=0)

        paths = [f"/tmp/repo/file{i}.py" for i in range(100)]

        with patch("rekipedia.watcher.watcher.subprocess.run", side_effect=fake_subprocess_run):
            watcher = _RepoWatcher("/tmp/repo", debounce_seconds=0.05)
            for p in paths:
                watcher.on_change(p)
            triggered.wait(timeout=3.0)

        update_idx = captured_cmd.index("update")
        extra_args = captured_cmd[update_idx + 1:]
        assert len(extra_args) == 0

    def test_threshold_constant_is_twenty(self):
        assert _SMART_DIFF_THRESHOLD == 20
