"""Hyperedge data contract for representing N-ary relationships (design patterns, shared concepts)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Hyperedge(BaseModel):
    """An N-ary relationship connecting 3 or more symbols sharing a common concept or pattern."""

    id: str  # Stable unique identifier, e.g. "pattern::repository_pattern"
    concept: str  # Human-readable concept, e.g. "Repository Pattern", "Observer Pattern"
    nodes: list[str] = Field(default_factory=list)  # Symbol names/IDs (minimum 3 nodes)
    description: str = ""  # Explanation of how the symbols participate in this concept
    confidence: Literal["EXTRACTED", "INFERRED"] = "INFERRED"
    pattern_type: str | None = "design_pattern"  # "design_pattern" | "architectural_motif" | "shared_concept"

    def to_dict(self) -> dict:
        return self.model_dump()
