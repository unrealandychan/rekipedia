"""Repository staleness checker (inspired by CodeGraph connect-time catchup)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from rekipedia.orchestrator.snapshotter import Snapshotter
from rekipedia.storage.sqlite_store import SqliteStore


def check_index_staleness(
    repo_root: Path,
    store: SqliteStore,
    run_id: str | None = None,
    max_check_files: int = 500,
) -> dict[str, Any]:
    """Check if working tree files have changed compared to the indexed snapshot.

    Returns:
        Dict with keys:
          - is_stale: bool
          - changed_files: list of relative paths modified, added, or deleted
          - count: number of changed files
          - banner: human-readable warning banner or ""
    """
    if not run_id:
        run_id = store.get_latest_run_id(str(repo_root)) or store.latest_run_id()
    if not run_id:
        return {"is_stale": False, "changed_files": [], "count": 0, "banner": ""}

    stored_files = store.get_files_for_run(run_id)
    if not stored_files:
        return {"is_stale": False, "changed_files": [], "count": 0, "banner": ""}

    stored_map = {f["path"]: f["sha256"] for f in stored_files}

    # Snapshot current repo files
    try:
        snapshotter = Snapshotter(repo_root)
        current_files = snapshotter.snapshot()
    except Exception:
        return {"is_stale": False, "changed_files": [], "count": 0, "banner": ""}

    current_map = {f.path: f.sha256 for f in current_files}

    changed: list[str] = []
    # Check modified or deleted
    for path, stored_hash in stored_map.items():
        if path not in current_map or current_map[path] != stored_hash:
            changed.append(path)

    # Check added
    for path in current_map:
        if path not in stored_map:
            changed.append(path)

    is_stale = len(changed) > 0
    banner = ""
    if is_stale:
        samples = ", ".join(changed[:3])
        more = f" and {len(changed) - 3} more" if len(changed) > 3 else ""
        banner = f"⚠️ Warning: {len(changed)} file(s) modified since last scan ({samples}{more}). Run 'reki update .' to refresh."

    return {
        "is_stale": is_stale,
        "changed_files": changed,
        "count": len(changed),
        "banner": banner,
    }
