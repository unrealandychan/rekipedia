"""Base class and common utilities for Tree-sitter based language extractors."""
from __future__ import annotations

from abc import abstractmethod
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from rekipedia.extractors.base import BaseExtractor
from rekipedia.models.contracts import AnalysisResult, RationaleNote, Relationship, Symbol


class BaseTreeSitterExtractor(BaseExtractor):
    """Abstract base extractor powered by Tree-sitter AST parsing."""

    def __init__(self, language: Any = None) -> None:
        self._language = language
        self._parser: Any = None
        if language is not None:
            from tree_sitter import Parser
            self._parser = Parser(language)

    @property
    def parser(self) -> Any:
        return self._parser

    @staticmethod
    def node_text(node: Any, src: bytes) -> str:
        """Return decoded text of a tree-sitter node."""
        return src[node.start_byte : node.end_byte].decode("utf-8", errors="replace")

    @staticmethod
    def walk(node: Any) -> Iterator[Any]:
        """Depth-first traversal of all named descendant nodes in the tree."""
        stack = list(getattr(node, "named_children", []))
        while stack:
            cur = stack.pop(0)
            yield cur
            stack = list(getattr(cur, "named_children", [])) + stack

    @staticmethod
    def line_start(node: Any) -> int:
        """Return 1-based start line of a node."""
        return int(node.start_point[0]) + 1

    @staticmethod
    def line_end(node: Any) -> int:
        """Return 1-based end line of a node."""
        return int(node.end_point[0]) + 1

    @abstractmethod
    def can_handle(self, path: Path) -> bool:
        """Return True if this extractor can process the given file."""

    @abstractmethod
    def extract(self, path: Path, repo_root: Path) -> AnalysisResult:
        """Extract symbols and relationships from source file."""
