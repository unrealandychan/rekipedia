"""Pydantic v2 contracts shared across the entire rekipedia package."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


# ─────────────────────────────────────────────
# LLM configuration (mirrors config.yml llm: block)
# ─────────────────────────────────────────────

class LLMConfig(BaseModel):
    model: str = "ollama/llama4"
    api_key: str = ""
    base_url: str = ""
    temperature: float = 0.2
    # Embedding model / provider (separate from the generation LLM)
    # If embed_model is empty, EmbedPipeline falls back to REKIPEDIA_EMBED_MODEL env var.
    embed_model: str = ""
    embed_provider: str = ""  # e.g. "openai", "ollama", "azure" — used to build litellm model string
    embed_api_key: str = ""   # separate API key for embed provider (falls back to api_key)
    embed_base_url: str = ""  # separate base URL for embed provider (falls back to base_url)


# ─────────────────────────────────────────────
# File manifest entry (snapshotter output)
# ─────────────────────────────────────────────

class FileManifest(BaseModel):
    path: str
    sha256: str
    size_bytes: int
    language: str | None = None


# ─────────────────────────────────────────────
# Analysis result (Docker sandbox contract)
# ─────────────────────────────────────────────

SymbolKind = Literal[
    "function", "class", "type", "variable",
    "interface", "enum", "module", "other",
]

RelationshipKind = Literal["import", "call", "inherits", "uses", "re-exports"]


class Symbol(BaseModel):
    name: str
    kind: SymbolKind
    file: str
    line_start: int | None = None
    line_end: int | None = None
    signature: str | None = None
    docstring: str | None = None


class Relationship(BaseModel):
    from_: str = Field(alias="from")
    to: str
    kind: RelationshipKind
    file: str | None = None

    model_config = {"populate_by_name": True}


class AnalysisResult(BaseModel):
    shard_id: str
    files_seen: list[str]
    entry_points: list[str]
    symbols: list[Symbol] = Field(default_factory=list)
    relationships: list[Relationship] = Field(default_factory=list)
    build_commands: list[str] = Field(default_factory=list)
    test_commands: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    evidence: dict[str, str] = Field(default_factory=dict)


# ─────────────────────────────────────────────
# Shard descriptor (orchestrator input)
# ─────────────────────────────────────────────

class Shard(BaseModel):
    shard_id: str
    root: str                    # absolute path to shard directory
    files: list[FileManifest]
    llm: LLMConfig = Field(default_factory=LLMConfig)
    extra: dict[str, Any] = Field(default_factory=dict)
