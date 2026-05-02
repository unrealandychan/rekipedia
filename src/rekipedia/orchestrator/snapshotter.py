"""Repository file-system snapshotter.

Walks a repo root, respects ignore patterns, and returns a list of
FileManifest objects with SHA-256 hashes.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pathspec

from rekipedia.models.contracts import FileManifest

_LANGUAGE_MAP: dict[str, str] = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".kt": "kotlin",
    ".rb": "ruby",
    ".md": "markdown",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".toml": "toml",
    ".sql": "sql",
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
    ".dockerfile": "docker",
    ".tf": "terraform",
    ".html": "html",
    ".css": "css",
    ".scss": "scss",
}

_DEFAULT_IGNORE = [
    ".git",
    ".rekipedia",
    "__pycache__",
    "*.pyc",
    "node_modules",
    "dist",
    "build",
    ".venv",
    "venv",
    ".env",
    "*.egg-info",
    ".DS_Store",
]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _detect_language(path: Path) -> str | None:
    suffix = path.suffix.lower()
    if path.name.lower() == "dockerfile":
        return "docker"
    return _LANGUAGE_MAP.get(suffix)

class Snapshotter:
    """Walk *repo_root* and produce a list of :class:`FileManifest` objects."""

    def __init__(
        self,
        repo_root: Path,
        extra_ignore: list[str] | None = None,
        languages: list[str] | None = None,
    ) -> None:
        self._root = repo_root.resolve()
        patterns = list(_DEFAULT_IGNORE) + (extra_ignore or [])
        self._spec = pathspec.PathSpec.from_lines("gitignore", patterns)
        # Normalise to lowercase set; None means "all languages"
        self._languages: set[str] | None = (
            {lang.lower() for lang in languages} if languages else None
        )

    def snapshot(self) -> list[FileManifest]:
        manifests: list[FileManifest] = []
        for file_path in self._root.rglob("*"):
            if not file_path.is_file():
                continue
            rel = file_path.relative_to(self._root)
            if self._spec.match_file(str(rel)):
                continue
            lang = _detect_language(file_path)
            if self._languages is not None and lang not in self._languages:
                continue
            manifests.append(
                FileManifest(
                    path=str(rel),
                    sha256=_sha256(file_path),
                    size_bytes=file_path.stat().st_size,
                    language=lang,
                )
            )
        return sorted(manifests, key=lambda m: m.path)
