"""Tests for Snapshotter."""
from __future__ import annotations

from pathlib import Path

from rekipedia.orchestrator.snapshotter import Snapshotter


def _make_repo(root: Path) -> None:
    (root / "main.py").write_text("print('hello')")
    (root / "utils.py").write_text("def helper(): pass")
    (root / "README.md").write_text("# Test repo")
    sub = root / "pkg"
    sub.mkdir()
    (sub / "__init__.py").write_text("")
    (sub / "core.py").write_text("class Core: pass")
    # Files that should be ignored
    git = root / ".git"
    git.mkdir()
    (git / "config").write_text("[core]")
    cache = root / "__pycache__"
    cache.mkdir()
    (cache / "main.cpython-311.pyc").write_bytes(b"\x00")


def test_snapshot_returns_manifests(tmp_path: Path) -> None:
    _make_repo(tmp_path)
    s = Snapshotter(tmp_path)
    manifests = s.snapshot()
    paths = {m.path for m in manifests}
    assert "main.py" in paths
    assert "pkg/core.py" in paths


def test_snapshot_excludes_git_and_pycache(tmp_path: Path) -> None:
    _make_repo(tmp_path)
    s = Snapshotter(tmp_path)
    manifests = s.snapshot()
    paths = {m.path for m in manifests}
    assert not any(p.startswith(".git") for p in paths)
    assert not any(p.startswith("__pycache__") for p in paths)
    assert not any(p.endswith(".pyc") for p in paths)


def test_snapshot_sha256_is_stable(tmp_path: Path) -> None:
    _make_repo(tmp_path)
    s = Snapshotter(tmp_path)
    run1 = {m.path: m.sha256 for m in s.snapshot()}
    run2 = {m.path: m.sha256 for m in s.snapshot()}
    assert run1 == run2


def test_snapshot_detects_language(tmp_path: Path) -> None:
    _make_repo(tmp_path)
    s = Snapshotter(tmp_path)
    manifests = {m.path: m for m in s.snapshot()}
    assert manifests["main.py"].language == "python"
    assert manifests["README.md"].language == "markdown"


def test_snapshot_extra_ignore(tmp_path: Path) -> None:
    _make_repo(tmp_path)
    (tmp_path / "secret.txt").write_text("top secret")
    s = Snapshotter(tmp_path, extra_ignore=["*.txt"])
    paths = {m.path for m in s.snapshot()}
    assert "secret.txt" not in paths
