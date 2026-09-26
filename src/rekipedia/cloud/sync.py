"""Cloud Storage artifact layout and fingerprint-based incremental synchronization."""
from __future__ import annotations

import hashlib
from pathlib import Path

GCS_ARTIFACT_SPEC = """
GCS Artifact Bucket Layout:
gs://rekipedia-artifacts/{user_id}/{project_id}/
  ├── store.db          # SQLite cold backup artifact
  ├── fingerprints.json # Per-file SHA-256 map for incremental skips
  └── wiki/             # Generated Markdown wiki pages
"""


def compute_file_fingerprint(file_path: Path) -> str:
    """Compute SHA-256 hash of a file."""
    h = hashlib.sha256()
    try:
        with file_path.open("rb") as f:
            while chunk := f.read(65536):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return ""


def compute_repo_fingerprints(repo_root: Path, file_paths: list[str]) -> dict[str, str]:
    """Compute mapping of rel_path -> SHA-256 for all scanned files."""
    fingerprints = {}
    for rel in file_paths:
        full = repo_root / rel
        if full.is_file():
            fingerprints[rel] = compute_file_fingerprint(full)
    return fingerprints


def diff_fingerprints(
    old_fingerprints: dict[str, str],
    new_fingerprints: dict[str, str],
) -> dict[str, set[str]]:
    """Determine changed, added, deleted, and unchanged files between two fingerprint snapshots."""
    old_keys = set(old_fingerprints.keys())
    new_keys = set(new_fingerprints.keys())

    added = new_keys - old_keys
    deleted = old_keys - new_keys
    common = old_keys & new_keys

    modified = {k for k in common if old_fingerprints[k] != new_fingerprints[k]}
    unchanged = {k for k in common if old_fingerprints[k] == new_fingerprints[k]}

    return {
        "added": added,
        "modified": modified,
        "deleted": deleted,
        "unchanged": unchanged,
        "requires_update": added | modified,
    }
