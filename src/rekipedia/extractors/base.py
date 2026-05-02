"""Base interface for all language extractors."""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from rekipedia.models.contracts import AnalysisResult


class BaseExtractor(ABC):
    """Extract symbols and relationships from source files."""

    @abstractmethod
    def can_handle(self, path: Path) -> bool:
        """Return True if this extractor can process the given file."""

    @abstractmethod
    def extract(self, path: Path, repo_root: Path) -> AnalysisResult:
        """Extract symbols/relationships from *path* and return an AnalysisResult.

        The result's ``shard_id`` should be the relative path string.
        """
