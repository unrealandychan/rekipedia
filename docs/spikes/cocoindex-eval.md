# Spike: CocoIndex as Optional RAG Backend

**Issue:** #79
**Date:** 2026-05-16
**Status:** Complete — Recommendation below

---

## 1. What Is CocoIndex?

CocoIndex (`pip install cocoindex`) is an incremental data-indexing framework for AI/LLM applications backed by a **Rust core** and a declarative Python API. Mental model: `Target = F(Source)` — only the Δ (delta) is re-processed on each update.

### Core Architecture

| Layer | Description |
|---|---|
| **Sources** | Local FS, S3/GCS, Git repos, Postgres, APIs, queues |
| **Transforms** | Pure Python `@cocoindex.op.function()` or built-ins (`SplitRecursively`, `SentenceTransformerEmbed`, `EmbedText`, `ExtractByLlm`) |
| **Targets** | Postgres+pgvector, LanceDB, Qdrant, Neo4j, Kuzu, Kafka, **Custom** (via spec+connector protocol) |
| **Control Plane** | Rust-managed: live cache, pipeline versioning, lineage graph, task scheduler, retries, DLQ |

### Delta Detection

The engine hashes `hash(input)` + `hash(code)` for every function call. On a typical incremental re-run, **~0.1% of records are reprocessed** — the rest hit cache.

---

## 2. Python API Sample

```python
import cocoindex

@cocoindex.flow_def(name="CodeEmbedding")
def code_embedding_flow(flow_builder, data_scope):
    data_scope["files"] = flow_builder.add_source(
        cocoindex.sources.LocalFile(path="./src", included_patterns=["*.py", "*.go"])
    )
    doc_embeddings = data_scope.add_collector()

    with data_scope["files"].row() as file:
        file["chunks"] = file["content"].transform(
            cocoindex.functions.SplitRecursively(),
            language=file["extension"],
            chunk_size=1000,
            chunk_overlap=300
        )
        with file["chunks"].row() as chunk:
            chunk["embedding"] = chunk["text"].transform(
                cocoindex.functions.SentenceTransformerEmbed(
                    model="sentence-transformers/all-MiniLM-L6-v2"
                )
            )
            doc_embeddings.collect(filename=file["filename"], text=chunk["text"], embedding=chunk["embedding"])

    doc_embeddings.export(
        "doc_embeddings",
        cocoindex.storages.Postgres(),
        primary_key_fields=["filename", "location"],
        vector_indexes=[cocoindex.VectorIndex("embedding", cocoindex.VectorSimilarityMetric.COSINE_SIMILARITY)]
    )

cocoindex.init()
code_embedding_flow.update()  # idempotent backfill
```

---

## 3. CocoIndex vs rekipedia Legacy Pipeline

| Dimension | Legacy (Python/FAISS/SQLite) | CocoIndex (Postgres/pgvector) |
|---|---|---|
| **Freshness** | Batch re-index only | Sub-second delta; live mode continuous |
| **Delta detection** | None — full re-embed every run | Built-in hash-based; ~0.1% reprocessed |
| **Embedding cost** | 100% of corpus each run | Only changed files |
| **Lineage** | None | Full byte-level source provenance |
| **Concurrency** | Manual asyncio/ThreadPoolExecutor | Rust-native parallelism |
| **Error handling** | DIY try/except | Retries, backoff, DLQ, per-record isolation |
| **Storage** | SQLite + FAISS (zero infra) | **Requires PostgreSQL** |
| **Portability** | Single file, runs anywhere | Needs running Postgres |
| **Boilerplate** | High (all glue hand-written) | ~50 lines declarative Python |
| **Custom logic** | Full Python | Full Python via `@cocoindex.op.function()` |

**Verdict:** CocoIndex wins decisively on freshness, cost-at-scale, lineage, and reliability. Legacy wins on **portability** — zero deps, works on any machine or CI.

---

## 4. Blockers & Limitations

### 🔴 No SQLite Control-Plane Support
CocoIndex requires **PostgreSQL** for its control-plane state (delta cache, pipeline catalog, lineage graph). There is no SQLite alternative. SQLite-only or embedded deployments are **not supported** without significant custom work.

*Impact for rekipedia:* CocoIndex **cannot replace** the legacy backend for zero-infrastructure users. It must be strictly **opt-in** with Postgres as a hard prerequisite.

### 🟡 LiteLLM Embedding Bug (open issue cocoindex-code#122)
`cocoindex[litellm]` fails with OpenAI-compatible embedding endpoints because the request serializes `encoding_format: null`. Providers reject the request.
- **Workaround:** Use `LlmApiType.OPENAI` + custom `address` instead of `LITE_LLM`.
- **Status:** Open as of May 2026; local patch identified but not merged.

### 🟡 LiteLLM API Type Does Not Cover Embeddings
`LlmApiType.LITE_LLM` only supports text generation. LiteLLM-proxied embeddings must go through `LlmApiType.OPENAI` pointed at a custom address. Subtle footgun for local model users.

### 🟢 No CGO / No Go Dependencies
CocoIndex is Python + Rust only. Pre-compiled wheels — `pip install cocoindex` just works. No C/C++ build toolchain required.

### 🟡 Postgres Is a Hard Runtime Dependency
No `DATABASE_URL` abstraction over other databases. Step 1 in the quickstart is "Install Postgres."

### 🟢 Python ≥ 3.11 Required
rekipedia already requires Python ≥ 3.11 — no conflict.

### 🟢 License Compatible
Apache 2.0 — fully compatible with proprietary rekipedia licensing.

---

## 5. Installation Plan

```toml
# pyproject.toml — optional extra
[project.optional-dependencies]
cocoindex = [
    "cocoindex>=0.1.58",
    "psycopg[binary]>=3.1",
]
```

```bash
pip install "rekipedia[cocoindex]"
```

CocoIndex is **never** imported in the base install. The `CocoIndexBackend` class guard-imports it:

```python
def __init__(self, ...):
    try:
        import cocoindex  # noqa: F401
    except ImportError:
        raise RuntimeError(
            "CocoIndex backend requires `pip install rekipedia[cocoindex]`"
        )
```

---

## 6. Drafted `IndexBackend` Protocol

```python
# src/close_wiki/backends/protocol.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class Document:
    """Unit of content to be indexed."""
    id: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SearchResult:
    """A single retrieved result."""
    id: str
    text: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)
    # CocoIndex lineage ref, e.g. "src/auth.py L42"
    source_ref: str | None = None


@dataclass
class IndexStats:
    total_documents: int
    last_updated_at: str | None
    backend_name: str
    extra: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class IndexBackend(Protocol):
    """
    Unified protocol for RAG index backends.

    Implementations:
    - LegacyIndexBackend   — custom Python + FAISS + SQLite (zero infra)
    - CocoIndexBackend     — CocoIndex + Postgres + pgvector (production)

    All mutating methods are idempotent.
    """

    @property
    def name(self) -> str:
        """Human-readable backend identifier."""
        ...

    # ── Lifecycle ──────────────────────────────────────────────────────────

    def setup(self) -> None:
        """One-time init: create tables, indices, schemas. Idempotent."""
        ...

    def teardown(self) -> None:
        """Release resources. Does NOT delete data."""
        ...

    def destroy(self) -> None:
        """Permanently delete all indexed data. Idempotent."""
        ...

    # ── Writes ─────────────────────────────────────────────────────────────

    def upsert(self, documents: list[Document]) -> None:
        """
        Insert or update documents.
        - Legacy: embeds then writes to FAISS + SQLite.
        - CocoIndex: triggers incremental update; unchanged docs are no-ops.
        """
        ...

    def delete(self, ids: list[str]) -> None:
        """Remove documents by ID."""
        ...

    def update_all(self, source_path: str | None = None) -> None:
        """
        Full incremental refresh from source.
        - Legacy: re-scan source_path, re-embed changed files.
        - CocoIndex: calls flow.update() — delta handled internally.
        """
        ...

    # ── Reads ──────────────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        """Semantic similarity search. Returns up to top_k results."""
        ...

    def get(self, doc_id: str) -> Document | None:
        """Fetch a single document by ID."""
        ...

    # ── Introspection ──────────────────────────────────────────────────────

    def stats(self) -> IndexStats:
        """Return metadata about the current index state."""
        ...

    def health_check(self) -> bool:
        """Returns True if backend is operational. Must be fast (<100ms)."""
        ...
```

---

## 7. Config Switching (`.rekipedia/config.yml`)

```yaml
# Default — zero infra required
engine: legacy

# Opt-in — requires PostgreSQL + pip install rekipedia[cocoindex]
# engine: cocoindex
# cocoindex:
#   database_url: "postgresql://user:pass@localhost:5432/rekipedia"
#   embedding_model: "sentence-transformers/all-MiniLM-L6-v2"
```

Backend is resolved at startup:

```python
def load_backend(config: Config) -> IndexBackend:
    if config.engine == "cocoindex":
        from close_wiki.backends.cocoindex_backend import CocoIndexBackend
        return CocoIndexBackend(config.cocoindex)
    return LegacyIndexBackend(config.db_path, config.llm)
```

---

## 8. Recommendation

### ✅ Proceed with CocoIndex as optional backend (Issue #80)

**Why:**
- CocoIndex is production-ready, actively maintained (v0.1.x → daily releases), Apache 2.0
- The `IndexBackend` protocol cleanly decouples both backends — existing users are unaffected
- Delta-only processing is a genuine win for large repos: 10× cheaper embeddings on `reki update`
- Full source lineage improves answer quality in agentic mode (Issue #94)

**Constraints:**
1. **Postgres is required** — document clearly. CocoIndex is `engine: cocoindex` opt-in, never default.
2. **LiteLLM embedding bug** — add a note in CocoIndexBackend docs to use `OPENAI` type + custom address instead of `LITE_LLM` until upstream fix.
3. **Custom SQLite target** is feasible for the *data* plane (writes) but the control plane still needs Postgres — do not advertise as "SQLite-compatible."

### Effort Estimate for #80 (full CocoIndexBackend implementation)
| Task | Estimate |
|---|---|
| `IndexBackend` protocol + `LegacyIndexBackend` wrapper | 1 day |
| `CocoIndexBackend` (flow definition + search + lifecycle) | 2 days |
| Config loading + CLI flag `--engine` | 0.5 day |
| Tests (mock Postgres with `testcontainers`) | 1 day |
| Docs + migration guide | 0.5 day |
| **Total** | **~5 days** |

---

*Spike completed by: Hermes Agent | rekipedia Issue #79*
