"""rekipedia backends package.

Available backends
------------------
- ``legacy``     — Python + FAISS + SQLite (default, zero infra)
- ``cocoindex``  — CocoIndex + Postgres + pgvector (opt-in)

Both backends implement :class:`close_wiki.backends.protocol.IndexBackend`.
"""
from close_wiki.backends.protocol import Document, IndexBackend, IndexStats, SearchResult

__all__ = ["Document", "IndexBackend", "IndexStats", "SearchResult"]
