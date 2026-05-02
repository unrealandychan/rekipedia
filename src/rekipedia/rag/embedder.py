"""RAG embedder — chunk source files, embed via litellm, persist FAISS index.

Layout inside .rekipedia/:
    rag/
        index.faiss      — FAISS flat L2 index
        chunks.json      — parallel list of chunk metadata
        embed_meta.json  — embedding model + dimension + timestamp

Usage::

    from rekipedia.rag.embedder import EmbedPipeline
    pipe = EmbedPipeline(output_dir, llm_config)
    pipe.build(repo_root)           # full build
    results = pipe.search("how does auth work?", top_k=8)
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Iterator

try:
    import numpy as np
    _NUMPY_AVAILABLE = True
except ImportError:
    _NUMPY_AVAILABLE = False

try:
    import faiss  # noqa: F401
    _RAG_AVAILABLE = _NUMPY_AVAILABLE
except ImportError:
    _RAG_AVAILABLE = False
    np = None  # type: ignore[assignment]

from rekipedia.models.contracts import LLMConfig

logger = logging.getLogger("rekipedia.rag.embedder")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Default embedding model (OpenAI-compatible, cheap + fast)
_DEFAULT_EMBED_MODEL = os.environ.get(
    "REKIPEDIA_EMBED_MODEL", "text-embedding-3-small"
)

# Max chars per chunk (~512 tokens @ 4 chars/token)
_CHUNK_CHARS = 2_000
# Overlap between adjacent chunks
_OVERLAP_CHARS = 200
# Max file size to embed — configurable via env vars (skip giant files to avoid bad chunks)
# Defaults: ~80K tokens for code, ~8K tokens for docs (same heuristic as deepwiki-open)
_MAX_CODE_CHARS = int(os.environ.get("REKIPEDIA_MAX_CODE_CHARS", "320000"))   # ~80K tokens
_MAX_DOC_CHARS  = int(os.environ.get("REKIPEDIA_MAX_DOC_CHARS",  "32000"))    # ~8K tokens

# Batch size for embedding API calls
_EMBED_BATCH = 100

# File extensions to embed
_CODE_EXTS = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs",
    ".java", ".kt", ".rb", ".swift", ".cs", ".cpp", ".c", ".h",
    ".html", ".css", ".scss",
}
_DOC_EXTS = {".md", ".txt", ".rst", ".yaml", ".yml", ".toml", ".json"}

# Dirs/files to skip
_SKIP_DIRS = {
    ".git", ".rekipedia", "__pycache__", "node_modules",
    "dist", "build", ".venv", "venv", ".mypy_cache", ".pytest_cache",
    "*.egg-info",
}

_RAG_DIR = "rag"
_INDEX_FILE = "index.faiss"
_CHUNKS_FILE = "chunks.json"
_EMBED_META_FILE = "embed_meta.json"


# ---------------------------------------------------------------------------
# Chunker
# ---------------------------------------------------------------------------

def _is_implementation(path: str) -> bool:
    """Heuristic: True for core logic files, False for tests/configs.
    Borrowed from deepwiki-open's data_pipeline.py.
    """
    p = path.lower()
    parts = Path(p).parts
    return not any(
        part.startswith("test") or part in ("tests", "spec", "specs", "__tests__")
        for part in parts
    )


def _iter_repo_files(repo_root: Path) -> Iterator[Path]:
    """Walk repo, yielding files eligible for embedding."""
    skip = _SKIP_DIRS

    for f in sorted(repo_root.rglob("*")):
        if not f.is_file():
            continue
        # Skip if any ancestor dir matches skip set
        if any(part in skip or part.endswith(".egg-info") for part in f.parts):
            continue
        ext = f.suffix.lower()
        if ext not in _CODE_EXTS and ext not in _DOC_EXTS:
            continue
        yield f


def _chunk_file(path: Path, repo_root: Path) -> list[dict]:
    """Split file into overlapping text chunks with metadata."""
    ext = path.suffix.lower()
    is_doc = ext in _DOC_EXTS
    max_chars = _MAX_DOC_CHARS if is_doc else _MAX_CODE_CHARS

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []

    if len(text) > max_chars:
        logger.debug("Skipping %s — too large (%d chars)", path, len(text))
        return []

    rel = str(path.relative_to(repo_root))
    impl = _is_implementation(rel)
    chunks = []
    start = 0
    idx = 0

    while start < len(text):
        end = min(start + _CHUNK_CHARS, len(text))
        chunk_text = text[start:end]
        if chunk_text.strip():
            chunks.append({
                "file": rel,
                "chunk_idx": idx,
                "start_char": start,
                "text": chunk_text,
                "is_code": not is_doc,
                "is_implementation": impl,
                "ext": ext,
            })
        start += _CHUNK_CHARS - _OVERLAP_CHARS
        idx += 1

    return chunks


# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------

def _embed_batch(texts: list[str], model: str, llm_config: LLMConfig) -> np.ndarray:
    """Call embedding API and return (N, D) float32 array.

    When a custom base_url is configured (e.g. LiteLLM proxy), bypass litellm
    and call the OpenAI-compatible endpoint directly — litellm overrides base_url
    when it recognises provider prefixes like 'openai/'.
    """
    api_key = getattr(llm_config, "embed_api_key", None) or llm_config.api_key
    base_url = getattr(llm_config, "embed_base_url", None) or llm_config.base_url

    if base_url:
        import httpx, certifi  # noqa: PLC0415
        url = base_url.rstrip("/") + "/embeddings"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key or 'no-key'}",
        }
        payload = {"model": model, "input": texts}
        try:
            r = httpx.post(url, json=payload, headers=headers, timeout=60,
                           verify=certifi.where())
            logger.debug("Embed proxy status=%s content-type=%s body_preview=%r",
                         r.status_code,
                         r.headers.get("content-type", ""),
                         r.text[:500])
            r.raise_for_status()
            data = r.json()
            vecs = [item["embedding"] for item in data["data"]]
        except Exception as exc:
            logger.error("Embed proxy error: %s", exc)
            raise
    else:
        import litellm  # noqa: PLC0415
        kwargs: dict = {"model": model, "input": texts}
        if api_key:
            kwargs["api_key"] = api_key
        resp = litellm.embedding(**kwargs)
        vecs = [item["embedding"] for item in resp.data]

    return np.array(vecs, dtype=np.float32)


# ---------------------------------------------------------------------------
# EmbedPipeline
# ---------------------------------------------------------------------------

class EmbedPipeline:
    """Build and query a FAISS index over a repository's source files."""

    def __init__(self, output_dir: Path, llm_config: LLMConfig) -> None:
        self._out = output_dir / _RAG_DIR
        self._cfg = llm_config
        # Resolve embed model: CLI flag → config field → env var → default
        raw_model = (
            os.environ.get("REKIPEDIA_EMBED_MODEL")
            or getattr(llm_config, "embed_model", None)
            or _DEFAULT_EMBED_MODEL
        )
        # If user specified a provider, build the litellm model string: "provider/model"
        provider = (
            os.environ.get("REKIPEDIA_EMBED_PROVIDER")
            or getattr(llm_config, "embed_provider", "")
        )
        # When a custom base_url is set (e.g. LiteLLM proxy), skip the provider
        # prefix — the proxy is OpenAI-compatible and handles routing itself.
        # Only add "provider/model" when hitting the provider directly.
        has_custom_base = bool(
            getattr(llm_config, "embed_base_url", None) or llm_config.base_url
        )
        if provider and "/" not in raw_model and not has_custom_base:
            self._model = f"{provider}/{raw_model}"
        else:
            self._model = raw_model

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def build(
        self,
        repo_root: Path,
        progress_cb=None,
    ) -> int:
        """Chunk all eligible files, embed, save FAISS index + chunks.json.

        Returns number of chunks embedded.
        """
        try:
            import faiss as _faiss  # noqa: PLC0415
            _HAS_FAISS = True
        except ImportError:
            _faiss = None
            _HAS_FAISS = False

        self._out.mkdir(parents=True, exist_ok=True)

        # 1. Collect chunks — track skipped files
        if progress_cb:
            progress_cb("📂 Collecting source files for embedding…")
        all_chunks: list[dict] = []
        files = list(_iter_repo_files(repo_root))
        skipped_too_large = 0
        for f in files:
            ext = f.suffix.lower()
            is_doc = ext in _DOC_EXTS
            max_chars = _MAX_DOC_CHARS if is_doc else _MAX_CODE_CHARS
            try:
                size = f.stat().st_size
            except OSError:
                size = 0
            if size > max_chars:
                skipped_too_large += 1
                logger.debug("Skipping %s — too large (%d chars > %d limit)", f, size, max_chars)
                continue
            all_chunks.extend(_chunk_file(f, repo_root))

        n = len(all_chunks)
        if n == 0:
            logger.warning("No chunks to embed in %s", repo_root)
            return 0

        if progress_cb:
            skip_msg = f" ({skipped_too_large} files skipped — too large)" if skipped_too_large else ""
            progress_cb(f"🔢 Embedding {n} chunks from {len(files) - skipped_too_large} files{skip_msg}…")

        # 2. Embed in batches
        all_vecs: list[np.ndarray] = []
        texts = [c["text"] for c in all_chunks]

        for i in range(0, n, _EMBED_BATCH):
            batch = texts[i : i + _EMBED_BATCH]
            if progress_cb:
                progress_cb(
                    f"🔢 Embedding chunks {i+1}–{min(i+len(batch), n)} / {n}…"
                )
            try:
                vecs = _embed_batch(batch, self._model, self._cfg)
                all_vecs.append(vecs)
            except Exception as exc:
                logger.error("Embedding batch %d failed: %s", i // _EMBED_BATCH, exc)
                # Fill with zeros so index stays aligned — marked invalid
                dim = all_vecs[-1].shape[1] if all_vecs else 1536
                all_vecs.append(np.zeros((len(batch), dim), dtype=np.float32))
            # Respect rate limits
            time.sleep(0.1)

        matrix = np.vstack(all_vecs)  # (N, D)
        dim = matrix.shape[1]

        # 3. Build index
        if progress_cb:
            progress_cb(f"🗄  Building index (dim={dim}, n={n})…")
        if _HAS_FAISS:
            index = _faiss.IndexFlatL2(dim)
            _faiss.normalize_L2(matrix)
            index.add(matrix)
            _faiss.write_index(index, str(self._out / _INDEX_FILE))
        else:
            # numpy fallback — normalise + save raw matrix
            norms = np.linalg.norm(matrix, axis=1, keepdims=True)
            matrix /= np.where(norms == 0, 1, norms)
            np.save(str(self._out / _INDEX_FILE) + ".npy", matrix)
        (self._out / _CHUNKS_FILE).write_text(
            json.dumps(all_chunks, ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        (self._out / _EMBED_META_FILE).write_text(
            json.dumps(
                {
                    "model": self._model,
                    "dim": dim,
                    "n_chunks": n,
                    "built_at": _ts(),
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        logger.info("EmbedPipeline: indexed %d chunks (dim=%d)", n, dim)
        if progress_cb:
            progress_cb(f"✅ FAISS index ready — {n} chunks, dim={dim}")
        return n

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(self, query: str, top_k: int = 8) -> list[dict]:
        """Return top-k most relevant chunks for *query*.

        Each result dict has: file, chunk_idx, text, score, is_implementation.
        Returns [] if no index exists.
        """
        try:
            import faiss as _faiss  # noqa: PLC0415
            _HAS_FAISS = True
        except ImportError:
            _faiss = None
            _HAS_FAISS = False

        index_path = self._out / _INDEX_FILE
        npy_path = Path(str(index_path) + ".npy")
        chunks_path = self._out / _CHUNKS_FILE

        if not chunks_path.exists():
            return []
        if not index_path.exists() and not npy_path.exists():
            return []

        try:
            chunks = json.loads(chunks_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Failed to load chunks: %s", exc)
            return []

        try:
            q_vec = _embed_batch([query], self._model, self._cfg)  # (1, D)
            if _HAS_FAISS and index_path.exists():
                index = _faiss.read_index(str(index_path))
                _faiss.normalize_L2(q_vec)
                distances, indices = index.search(q_vec, top_k)
                results = []
                for dist, idx in zip(distances[0], indices[0]):
                    if idx < 0 or idx >= len(chunks):
                        continue
                    chunk = dict(chunks[idx])
                    chunk["score"] = float(1.0 - dist / 2.0)
                    results.append(chunk)
            elif npy_path.exists():
                # numpy brute-force cosine
                matrix = np.load(str(npy_path))
                q = q_vec[0]
                q /= max(np.linalg.norm(q), 1e-9)
                scores = matrix @ q
                top_idx = np.argsort(scores)[::-1][:top_k]
                results = []
                for idx in top_idx:
                    chunk = dict(chunks[int(idx)])
                    chunk["score"] = float(scores[idx])
                    results.append(chunk)
            else:
                return []
        except Exception as exc:
            logger.warning("Search failed: %s", exc)
            return []

        # Prioritise implementation files over tests/docs
        results.sort(key=lambda c: (not c.get("is_implementation", True), -c["score"]))
        return results

    # ------------------------------------------------------------------
    # Introspect
    # ------------------------------------------------------------------

    def meta(self) -> dict | None:
        p = self._out / _EMBED_META_FILE
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None

    def is_built(self) -> bool:
        return (self._out / _INDEX_FILE).exists()


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _ts() -> str:
    from datetime import datetime, timezone  # noqa: PLC0415
    return datetime.now(timezone.utc).isoformat()
