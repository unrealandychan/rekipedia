"""Multi-repo daemon for rekipedia — watches directories and auto-indexes on change."""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path

CONFIG_PATH = Path.home() / ".rekipedia" / "watch.json"

_SOURCE_EXTENSIONS = frozenset({
    ".py", ".pyw",
    ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs",
    ".go",
    ".rs",
    ".java",
    ".rb",
    ".php",
    ".swift",
    ".kt",
})


def _is_source_file(path: str) -> bool:
    return Path(path).suffix.lower() in _SOURCE_EXTENSIONS


def _load_config() -> dict:
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text())
    return {"repos": []}


def _save_config(cfg: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))


def add_repo(path: str) -> None:
    path = str(Path(path).resolve())
    cfg = _load_config()
    if path not in cfg["repos"]:
        cfg["repos"].append(path)
        _save_config(cfg)
        print(f"Added repo: {path}")
    else:
        print(f"Already registered: {path}")


def list_repos() -> list[str]:
    return _load_config()["repos"]


def remove_repo(path: str) -> None:
    path = str(Path(path).resolve())
    cfg = _load_config()
    if path in cfg["repos"]:
        cfg["repos"].remove(path)
        _save_config(cfg)
        print(f"Removed repo: {path}")
    else:
        print(f"Not registered: {path}")


_SMART_DIFF_THRESHOLD = 20


class _RepoWatcher:
    def __init__(self, repo_path: str, debounce_seconds: float = 3.0):
        self.repo_path = repo_path
        self.debounce = debounce_seconds
        self._dirty = False
        self._changed_paths: set[str] = set()
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None

    def on_change(self, path: str) -> None:
        with self._lock:
            self._dirty = True
            self._changed_paths.add(path)
            if self._timer:
                self._timer.cancel()
            self._timer = threading.Timer(self.debounce, self._trigger)
            self._timer.start()

    def on_delete(self, path: str) -> None:
        """Immediately purge symbols for a deleted file."""
        print(f"[reki watch] File deleted: {path}, purging symbols...", flush=True)
        try:
            subprocess.run(
                [sys.executable, "-m", "rekipedia", "purge-file", path],
                cwd=self.repo_path,
                timeout=30,
                check=False,
            )
        except Exception as e:
            print(f"[reki watch] Purge failed: {e}", flush=True)

    def _trigger(self) -> None:
        with self._lock:
            if not self._dirty:
                return
            self._dirty = False
            changed = set(self._changed_paths)
            self._changed_paths.clear()
        print(f"[reki watch] Change detected in {self.repo_path}, running update...", flush=True)
        try:
            if 0 < len(changed) <= _SMART_DIFF_THRESHOLD:
                cmd = [sys.executable, "-m", "rekipedia", "update"] + sorted(changed)
            else:
                cmd = [sys.executable, "-m", "rekipedia", "update"]
            subprocess.run(
                cmd,
                cwd=self.repo_path,
                timeout=120,
                check=False,
            )
        except Exception as e:
            print(f"[reki watch] Update failed: {e}", flush=True)


def start_watching(repos: list[str] | None = None, debounce_seconds: float = 2.0) -> None:
    """Start watching repos. Blocks until interrupted."""
    try:
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer
    except ImportError:
        print("watchdog not installed. Run: pip install watchdog")
        return

    if repos is None:
        repos = list_repos()
    if not repos:
        print("No repos registered. Use: reki watch add <path>")
        return

    class _Handler(FileSystemEventHandler):
        def __init__(self, repo_watcher: _RepoWatcher):
            self._rw = repo_watcher

        def on_modified(self, event):
            if not event.is_directory and _is_source_file(event.src_path):
                self._rw.on_change(event.src_path)

        def on_created(self, event):
            if not event.is_directory and _is_source_file(event.src_path):
                self._rw.on_change(event.src_path)

        def on_deleted(self, event):
            if not event.is_directory and _is_source_file(event.src_path):
                self._rw.on_delete(event.src_path)

    observer = Observer()
    watchers = []
    for repo in repos:
        rw = _RepoWatcher(repo, debounce_seconds=debounce_seconds)
        handler = _Handler(rw)
        observer.schedule(handler, repo, recursive=True)
        watchers.append(rw)
        print(f"Watching: {repo}")

    observer.start()
    print("reki watch started. Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
