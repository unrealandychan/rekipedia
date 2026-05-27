"""Git history extractor for rekipedia.

Parses ``git log`` output into structured :class:`GitCommit` objects so that
commit messages can be stored alongside code symbols and surfaced during
``reki ask`` queries.
"""
from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("rekipedia.git_extractor")

_DEFAULT_MAX_COMMITS = 500


@dataclass
class GitCommit:
    """Structured representation of a single git commit.

    Attributes:
        hash: Full 40-character commit hash.
        short_hash: Abbreviated 7-character commit hash.
        author: Commit author name.
        date: Commit date in ISO 8601 format.
        message: Full commit message (subject + body).
        files_changed: List of file paths touched by this commit.
    """

    hash: str
    short_hash: str
    author: str
    date: str
    message: str
    files_changed: list[str] = field(default_factory=list)


def extract_commits(
    repo_path: str | Path,
    max_commits: int = _DEFAULT_MAX_COMMITS,
) -> list[GitCommit]:
    """Parse ``git log`` output from *repo_path* into :class:`GitCommit` objects.

    Args:
        repo_path: Path to the repository root (must contain a ``.git`` dir).
        max_commits: Maximum number of commits to return (default: 500).

    Returns:
        List of :class:`GitCommit` objects, newest-first.
        Returns an empty list if the directory is not a git repo or has no
        commits (no exception is raised).
    """
    repo_path = Path(repo_path)

    cmd = [
        "git",
        "-C",
        str(repo_path),
        "log",
        f"--format=%H|%h|%an|%aI|%s%n%b",
        "--name-only",
        "--no-merges",
        f"-{max_commits}",
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        logger.debug("git not available or timed out: %s", exc)
        return []

    if result.returncode != 0:
        logger.debug("git log failed (rc=%d): %s", result.returncode, result.stderr.strip())
        return []

    return _parse_git_log(result.stdout)


def _parse_git_log(output: str) -> list[GitCommit]:
    """Parse the raw text output of ``git log`` into :class:`GitCommit` objects.

    Args:
        output: Raw stdout from the ``git log`` command.

    Returns:
        Parsed list of :class:`GitCommit` objects.
    """
    commits: list[GitCommit] = []
    current: GitCommit | None = None
    body_lines: list[str] = []
    in_files = False

    for raw_line in output.splitlines():
        line = raw_line.rstrip()

        # Attempt to parse as a header line: HASH|short|author|date|subject
        if "|" in line and len(line.split("|", 4)) >= 4:
            parts = line.split("|", 4)
            # Validate that first part looks like a full hash (40 hex chars)
            if len(parts[0]) == 40 and all(c in "0123456789abcdefABCDEF" for c in parts[0]):
                # Save previous commit
                if current is not None:
                    if body_lines:
                        current.message = current.message + "\n" + "\n".join(body_lines).strip()
                    commits.append(current)

                subject = parts[4] if len(parts) > 4 else ""
                current = GitCommit(
                    hash=parts[0],
                    short_hash=parts[1],
                    author=parts[2],
                    date=parts[3],
                    message=subject,
                    files_changed=[],
                )
                body_lines = []
                in_files = False
                continue

        if current is None:
            continue

        # Empty line separates commit message body from file list
        if line == "":
            in_files = True
            continue

        if in_files:
            # Non-empty lines after the blank are file paths
            if line:
                current.files_changed.append(line)
        else:
            # Still in the commit message body
            body_lines.append(line)

    # Don't forget the last commit
    if current is not None:
        if body_lines:
            current.message = current.message + "\n" + "\n".join(body_lines).strip()
        commits.append(current)

    return commits


def commits_to_dicts(commits: list[GitCommit]) -> list[dict]:
    """Convert a list of :class:`GitCommit` objects to plain dicts for storage.

    Args:
        commits: List of :class:`GitCommit` objects.

    Returns:
        List of dicts suitable for :meth:`~rekipedia.storage.sqlite_store.SqliteStore.store_commits`.
    """
    return [
        {
            "hash": c.hash,
            "short_hash": c.short_hash,
            "author": c.author,
            "date": c.date,
            "message": c.message,
            "files_changed": json.dumps(c.files_changed),
        }
        for c in commits
    ]
