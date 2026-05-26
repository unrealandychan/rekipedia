"""Auto-apply safe refactor suggestions to source files.

Supports two auto-fixable smell types:
- ``dead_code``:  inserts a ``# reki: dead-code (flagged DATE)`` comment above the symbol.
- ``large_file``: inserts a comment block suggesting a module split.

All other smell types are treated as guidance-only (``action="skipped"``).
"""
from __future__ import annotations

import difflib
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

AUTO_FIXABLE: set[str] = {"dead_code", "large_file"}


@dataclass
class ApplyResult:
    smell_type: str
    file_path: str
    action: str   # "comment_added" | "stub_created" | "skipped"
    diff: str     # unified diff string
    applied: bool


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _today() -> str:
    return date.today().isoformat()


def _apply_dead_code(smell: dict[str, Any], dry_run: bool) -> ApplyResult:
    """Insert a dead-code marker comment above the symbol definition."""
    file_path: str = smell.get("file", "")
    symbol: str = smell.get("symbol", "")
    line_no: int | None = smell.get("line") or smell.get("metrics", {}).get("line")

    p = Path(file_path)
    if not p.exists():
        return ApplyResult(
            smell_type="dead_code",
            file_path=file_path,
            action="skipped",
            diff="",
            applied=False,
        )

    original_lines = p.read_text(encoding="utf-8").splitlines(keepends=True)

    # Try to locate the symbol definition line
    insert_before: int | None = None
    if line_no and 1 <= line_no <= len(original_lines):
        insert_before = line_no - 1  # 0-indexed
    else:
        # Scan for the symbol definition
        for idx, raw_line in enumerate(original_lines):
            stripped = raw_line.lstrip()
            if stripped.startswith(("def ", "class ", "async def ")) and symbol in raw_line:
                insert_before = idx
                break

    if insert_before is None:
        return ApplyResult(
            smell_type="dead_code",
            file_path=file_path,
            action="skipped",
            diff="",
            applied=False,
        )

    marker = f"# reki: dead-code (flagged {_today()})\n"
    new_lines = original_lines[:insert_before] + [marker] + original_lines[insert_before:]
    diff = "".join(
        difflib.unified_diff(original_lines, new_lines, fromfile=file_path, tofile=file_path)
    )

    if not dry_run:
        p.write_text("".join(new_lines), encoding="utf-8")

    return ApplyResult(
        smell_type="dead_code",
        file_path=file_path,
        action="comment_added",
        diff=diff,
        applied=not dry_run,
    )


def _apply_large_file(smell: dict[str, Any], dry_run: bool) -> ApplyResult:
    """Insert a split-suggestion comment block at the top of the file."""
    file_path: str = smell.get("file", "")
    metrics: dict = smell.get("metrics", {})
    line_count: int = metrics.get("line_count") or metrics.get("lines", 0)

    # Heuristic: suggest N = ceil(line_count / 300) modules
    import math
    n_modules = max(2, math.ceil(line_count / 300)) if line_count else 2

    p = Path(file_path)
    if not p.exists():
        return ApplyResult(
            smell_type="large_file",
            file_path=file_path,
            action="skipped",
            diff="",
            applied=False,
        )

    original_lines = p.read_text(encoding="utf-8").splitlines(keepends=True)

    comment_block = (
        f"# reki: consider splitting into {n_modules} modules"
        f" (flagged {_today()}, {line_count} lines)\n"
    )
    new_lines = [comment_block] + original_lines
    diff = "".join(
        difflib.unified_diff(original_lines, new_lines, fromfile=file_path, tofile=file_path)
    )

    if not dry_run:
        p.write_text("".join(new_lines), encoding="utf-8")

    return ApplyResult(
        smell_type="large_file",
        file_path=file_path,
        action="stub_created",
        diff=diff,
        applied=not dry_run,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def apply_smell(smell: dict[str, Any], dry_run: bool = False) -> ApplyResult:
    """Apply a single auto-fixable smell fix.

    Parameters
    ----------
    smell:
        A dict with at least ``"type"`` (or ``"kind"``) and ``"file"`` keys.
        May also include ``"symbol"``, ``"line"``, and ``"metrics"``.
    dry_run:
        When *True* the fix is computed but no files are written.

    Returns
    -------
    ApplyResult
        Contains the unified diff, action taken, and whether the fix was
        actually applied to disk.
    """
    smell_type: str = smell.get("type") or smell.get("kind") or ""

    if smell_type == "dead_code":
        return _apply_dead_code(smell, dry_run)
    if smell_type == "large_file":
        return _apply_large_file(smell, dry_run)

    # Non-auto-fixable
    return ApplyResult(
        smell_type=smell_type,
        file_path=smell.get("file", ""),
        action="skipped",
        diff="",
        applied=False,
    )


def apply_all(smells: list[dict[str, Any]], dry_run: bool = False) -> list[ApplyResult]:
    """Apply all auto-fixable smells, skipping non-auto-fixable ones.

    Parameters
    ----------
    smells:
        List of smell dicts (same format as accepted by :func:`apply_smell`).
    dry_run:
        When *True* no files are modified.

    Returns
    -------
    list[ApplyResult]
        One entry per input smell (including skipped ones).
    """
    return [apply_smell(smell, dry_run=dry_run) for smell in smells]
