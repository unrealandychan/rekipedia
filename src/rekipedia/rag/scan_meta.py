"""scan_meta.json — records model/timestamp/version after each scan.

Written to .rekipedia/scan_meta.json after a successful scan.
Read by `ask` and `embed` to detect stale indexes or model changes.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import rekipedia

_FILENAME = "scan_meta.json"


def write_scan_meta(
    output_dir: Path,
    *,
    repo_path: str,
    model: str,
    run_id: str,
    file_count: int,
    page_count: int,
    embed_model: str = "",
    embedded: bool = False,
) -> Path:
    """Write scan metadata to *output_dir/scan_meta.json*."""
    meta = {
        "rekipedia_version": rekipedia.__version__,
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "repo_path": repo_path,
        "run_id": run_id,
        "model": model,
        "file_count": file_count,
        "page_count": page_count,
        "embed_model": embed_model,
        "embedded": embedded,
    }
    path = output_dir / _FILENAME
    path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def read_scan_meta(output_dir: Path) -> dict | None:
    """Read scan metadata, or return None if not present."""
    path = output_dir / _FILENAME
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def patch_scan_meta(output_dir: Path, **kwargs) -> None:
    """Update specific fields in an existing scan_meta.json."""
    meta = read_scan_meta(output_dir) or {}
    meta.update(kwargs)
    path = output_dir / _FILENAME
    path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
