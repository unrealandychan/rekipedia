"""IndexBackend protocol — common interface for rekipedia RAG backends.

Both the legacy (Python/FAISS/SQLite) and CocoIndex (Postgres/pgvector)
backends implement this protocol, enabling hot-swappable engines via
.rekipedia/config.yml ``engine:`` key.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class Document:
    """Unit of content to be indexed."""

    id: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SearchResult:
    """A single retrieved result from a similarity search."""

    id: str
    text: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)
    # CocoIndex lineage reference, e.g. "src/auth.py L42-L88"
    source_ref: str | None = None


@dataclass
class IndexStats:
    """Metadata about the current index state."""

    total_documents: int
    last_updated_at: str | None
    backend_name: str
    extra: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class IndexBackend(Protocol):
    """Unified protocol for rekipedia RAG index backends.

    Implementations
    ---------------
    LegacyIndexBackend
        Custom Python + FAISS + SQLite.  Zero infra — works anywhere.
        Default when ``engine: legacy`` (or omitted) in config.yml.

    CocoIndexBackend
        CocoIndex + Postgres + pgvector.  Incremental delta processing,
        full source lineage.  Opt-in via ``engine: cocoindex``.
        Requires: ``pip install rekipedia[cocoindex]`` + PostgreSQL.

    All mutating methods are idempotent — safe to call multiple times with
    the same arguments.
    """

    @property
    def name(self) -> str:
        """Human-readable backend identifier, e.g. ``"legacy-faiss-sqlite"``."""
        ...

    # ── Lifecycle ──────────────────────────────────────────────────────────

    def setup(self) -> None:
        """One-time initialisation: create tables, FAISS indices, schemas.

        Must be idempotent — safe to call on an already-initialised backend.
        """
        ...

    def teardown(self) -> None:
        """Release resources (connections, file handles, etc.).

        Does **not** delete stored data — use :meth:`destroy` for that.
        """
        ...

    def destroy(self) -> None:
        """Permanently delete all indexed data managed by this backend.

        Use with caution.  Idempotent.
        """
        ...

    # ── Writes ─────────────────────────────────────────────────────────────

    def upsert(self, documents: list[Document]) -> None:
        """Insert or update documents.

        - **Legacy:** embeds via LiteLLM then writes to FAISS + SQLite.
        - **CocoIndex:** triggers incremental update; unchanged docs are
          no-ops (delta detection handled internally).
        """
        ...

    def delete(self, ids: list[str]) -> None:
        """Remove documents by ID.  Silently ignores unknown IDs."""
        ...

    def update_all(self, source_path: str | None = None) -> None:
        """Full incremental refresh from source.

        - **Legacy:** re-scans *source_path*, re-embeds changed files.
        - **CocoIndex:** calls ``flow.update()`` — CocoIndex handles delta.
        """
        ...

    # ── Reads ──────────────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        """Semantic similarity search.

        Returns up to *top_k* results sorted by descending relevance score.
        """
        ...

    def get(self, doc_id: str) -> Document | None:
        """Fetch a single document by ID.  Returns ``None`` if not found."""
        ...

    # ── Introspection ──────────────────────────────────────────────────────

    def stats(self) -> IndexStats:
        """Return metadata about the current index state."""
        ...

    def health_check(self) -> bool:
        """Return ``True`` if the backend is operational.

        Must be fast (< 100 ms) and must not modify state.
        """
        ...
