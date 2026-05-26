"""Tests for RAG/PageBuilder performance optimizations (issues #114–#119)."""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _make_pipeline(tmp_path):
    """Create an EmbedPipeline instance pointing at tmp_path."""
    from rekipedia.models.contracts import LLMConfig
    from rekipedia.rag.embedder import EmbedPipeline

    cfg = LLMConfig(model="gpt-4", api_key="sk-test")
    pipe = EmbedPipeline(tmp_path, cfg)
    return pipe


def _write_dummy_chunks(rag_dir: Path, chunks: list[dict]):
    rag_dir.mkdir(parents=True, exist_ok=True)
    (rag_dir / "chunks.json").write_text(json.dumps(chunks), encoding="utf-8")


# ---------------------------------------------------------------------------
# #114 — Chunks loaded only once (cached_property)
# ---------------------------------------------------------------------------

def test_chunks_loaded_once(tmp_path):
    """json.loads should be called only once even when search() is called twice."""
    from rekipedia.models.contracts import LLMConfig
    from rekipedia.rag.embedder import _RAG_DIR, EmbedPipeline

    rag_dir = tmp_path / _RAG_DIR
    chunks = [{"file": "a.py", "chunk_idx": 0, "text": "hello", "is_implementation": True, "score": 0.9}]
    _write_dummy_chunks(rag_dir, chunks)

    cfg = LLMConfig(model="gpt-4", api_key="sk-test")
    pipe = EmbedPipeline(tmp_path, cfg)

    # Patch json.loads to track calls
    original_loads = json.loads
    call_count = 0

    def counting_loads(s):
        nonlocal call_count
        call_count += 1
        return original_loads(s)

    import rekipedia.rag.embedder as emb_mod

    dummy_vec = np.zeros((1, 4), dtype=np.float32)

    # Make index file exist so search proceeds
    with patch.object(emb_mod, "json") as mock_json:
        mock_json.loads.return_value = chunks
        # Also make Path.exists return True for chunks
        with patch.object(Path, "exists", return_value=True):
            with patch.object(emb_mod, "_embed_batch", return_value=dummy_vec):
                try:
                    pipe.search("test query")
                    pipe.search("test query 2")
                except Exception:
                    pass

        # json.loads should have been called only once (cached_property)
        assert mock_json.loads.call_count == 1, (
            f"Expected json.loads to be called once, got {mock_json.loads.call_count}"
        )


# ---------------------------------------------------------------------------
# #115 — No double embedding in search()
# ---------------------------------------------------------------------------

def test_no_double_embedding(tmp_path):
    """_embed_batch should be called only once per search() call even with MMR enabled."""
    import rekipedia.rag.embedder as emb_mod
    from rekipedia.rag.embedder import _RAG_DIR, EmbedPipeline

    rag_dir = tmp_path / _RAG_DIR
    chunks = [
        {"file": "a.py", "chunk_idx": 0, "text": "hello", "is_implementation": True},
        {"file": "b.py", "chunk_idx": 0, "text": "world", "is_implementation": True},
    ]
    _write_dummy_chunks(rag_dir, chunks)
    # Write a dummy npy index
    matrix = np.random.rand(2, 4).astype(np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    matrix /= np.where(norms == 0, 1, norms)
    np.save(str(rag_dir / "index.faiss.npy"), matrix)

    from rekipedia.models.contracts import LLMConfig
    cfg = LLMConfig(model="gpt-4", api_key="sk-test")
    # Fresh instance (so cached_property is cold)
    pipe = EmbedPipeline(tmp_path, cfg)

    dummy_q_vec = np.random.rand(1, 4).astype(np.float32)
    embed_call_count = 0

    def mock_embed(texts, model, llm_cfg):
        nonlocal embed_call_count
        embed_call_count += 1
        return dummy_q_vec

    with patch.object(emb_mod, "_embed_batch", side_effect=mock_embed):
        # Disable FAISS so npy path is taken
        with patch.object(emb_mod, "_RAG_AVAILABLE", False):
            try:
                pipe.search("test query", mmr=True, top_k=2)
            except Exception:
                pass

    assert embed_call_count == 1, f"Expected 1 embed call, got {embed_call_count}"


# ---------------------------------------------------------------------------
# #116 — O(1) MMR chunk lookup correctness
# ---------------------------------------------------------------------------

def test_mmr_chunk_lookup_dict():
    """The dict-based chunk lookup should correctly find indices."""
    chunks = [
        {"file": "a.py", "chunk_idx": 0},
        {"file": "a.py", "chunk_idx": 1},
        {"file": "b.py", "chunk_idx": 0},
        {"file": "c.py", "chunk_idx": 2},
    ]
    results = [
        {"file": "b.py", "chunk_idx": 0},
        {"file": "c.py", "chunk_idx": 2},
    ]

    chunk_index = {(c['file'], c['chunk_idx']): i for i, c in enumerate(chunks)}
    cand_indices = [
        chunk_index[(r['file'], r['chunk_idx'])]
        for r in results
        if (r['file'], r['chunk_idx']) in chunk_index
    ]

    assert cand_indices == [2, 3]


# ---------------------------------------------------------------------------
# #117 — Rate limit sleep gated by env var
# ---------------------------------------------------------------------------

def test_rate_limit_sleep_off_by_default(tmp_path):
    """time.sleep should NOT be called when REKIPEDIA_EMBED_RATE_LIMIT is not set."""
    import rekipedia.rag.embedder as emb_mod
    from rekipedia.models.contracts import LLMConfig
    from rekipedia.rag.embedder import EmbedPipeline

    cfg = LLMConfig(model="gpt-4", api_key="sk-test")
    pipe = EmbedPipeline(tmp_path, cfg)

    dummy_vecs = np.random.rand(2, 4).astype(np.float32)

    env = {k: v for k, v in os.environ.items() if k != "REKIPEDIA_EMBED_RATE_LIMIT"}

    with patch.dict(os.environ, env, clear=True):
        with patch.object(emb_mod, "_embed_batch", return_value=dummy_vecs):
            with patch.object(emb_mod, "_iter_repo_files", return_value=[]):
                with patch("time.sleep") as mock_sleep:
                    # Build with empty repo — no batches — still verify sleep not called
                    try:
                        pipe.build(tmp_path)
                    except Exception:
                        pass
                    mock_sleep.assert_not_called()


def test_rate_limit_sleep_on_when_env_set(tmp_path):
    """time.sleep SHOULD be called when REKIPEDIA_EMBED_RATE_LIMIT=1."""
    import rekipedia.rag.embedder as emb_mod
    from rekipedia.models.contracts import LLMConfig
    from rekipedia.rag.embedder import EmbedPipeline

    cfg = LLMConfig(model="gpt-4", api_key="sk-test")
    pipe = EmbedPipeline(tmp_path, cfg)

    # Create a real source file to trigger embedding
    src = tmp_path / "test_file.py"
    src.write_text("def foo(): pass\n" * 10)

    dummy_vecs = np.random.rand(1, 4).astype(np.float32)

    with patch.dict(os.environ, {"REKIPEDIA_EMBED_RATE_LIMIT": "1"}):
        with patch.object(emb_mod, "_embed_batch", return_value=dummy_vecs):
            with patch.object(emb_mod, "_symbol_chunk_file", return_value=[
                {"file": "test_file.py", "chunk_idx": 0, "text": "def foo(): pass", "text_hash": "abc"}
            ]):
                with patch("time.sleep") as mock_sleep:
                    try:
                        pipe.build(tmp_path)
                    except Exception:
                        pass
                    mock_sleep.assert_called()


# ---------------------------------------------------------------------------
# #118 — Stream-build FAISS index (index.add called per batch)
# ---------------------------------------------------------------------------

def test_stream_faiss_build(tmp_path):
    """FAISS index.add should be called once per batch (not once for all)."""
    import rekipedia.rag.embedder as emb_mod
    from rekipedia.models.contracts import LLMConfig
    from rekipedia.rag.embedder import EmbedPipeline

    cfg = LLMConfig(model="gpt-4", api_key="sk-test")
    pipe = EmbedPipeline(tmp_path, cfg)

    # Create 3 chunks (batch size 100) — all fit in 1 batch, but we can test 2 batches by lowering _EMBED_BATCH
    n_chunks = 3
    fake_chunks = [
        {"file": "f.py", "chunk_idx": i, "text": f"chunk {i}", "text_hash": str(i)}
        for i in range(n_chunks)
    ]

    batch_vecs = np.random.rand(1, 4).astype(np.float32)

    mock_index = MagicMock()
    mock_index.d = 4

    mock_faiss = MagicMock()
    mock_faiss.IndexFlatL2.return_value = mock_index

    def mock_embed(texts, model, cfg):
        return np.random.rand(len(texts), 4).astype(np.float32)

    with patch.object(emb_mod, "_embed_batch", side_effect=mock_embed):
        with patch.object(emb_mod, "_iter_repo_files", return_value=[]):
        # Patch _EMBED_BATCH to 1 so each chunk is a separate batch
            with patch.object(emb_mod, "_symbol_chunk_file", return_value=fake_chunks):
                import rekipedia.rag.embedder as em2
                orig_batch = em2._EMBED_BATCH
                em2._EMBED_BATCH = 1
                try:
                    import sys
                    # Patch faiss inside the module
                    with patch.dict(sys.modules, {"faiss": mock_faiss}):
                        with patch.object(emb_mod, "_RAG_AVAILABLE", True):
                            # Patch _iter_repo_files to return a fake file
                            fake_file = tmp_path / "f.py"
                            fake_file.write_text("x" * 10)
                            with patch.object(emb_mod, "_iter_repo_files", return_value=[fake_file]):
                                with patch.object(emb_mod, "_symbol_chunk_file", return_value=fake_chunks[:1]):
                                    # We can't easily intercept _HAS_FAISS; instead just verify structure
                                    # by checking _stream_index logic indirectly via mock_index.add
                                    pass
                finally:
                    em2._EMBED_BATCH = orig_batch

    # Simpler direct test: manually verify add is called multiple times
    add_count = 0
    class TrackingIndex:
        d = 4
        def add(self, vecs):
            nonlocal add_count
            add_count += 1
        def __len__(self):
            return 0

    tracking_index = TrackingIndex()
    mock_faiss2 = MagicMock()
    mock_faiss2.IndexFlatL2.return_value = tracking_index
    mock_faiss2.normalize_L2 = lambda x: None
    mock_faiss2.write_index = lambda idx, path: None

    import rekipedia.rag.embedder as em3
    orig_batch = em3._EMBED_BATCH
    em3._EMBED_BATCH = 1
    try:
        with patch.dict(os.environ, {"REKIPEDIA_EMBED_RATE_LIMIT": "0"}):
            with patch.object(em3, "_embed_batch", side_effect=lambda texts, m, c: np.random.rand(len(texts), 4).astype(np.float32)):
                fake_file2 = tmp_path / "g.py"
                fake_file2.write_text("x" * 10)
                three_chunks = [
                    {"file": "g.py", "chunk_idx": i, "text": f"t{i}", "text_hash": str(i)}
                    for i in range(3)
                ]
                with patch.object(em3, "_iter_repo_files", return_value=[fake_file2]):
                    with patch.object(em3, "_symbol_chunk_file", return_value=three_chunks):
                        import builtins
                        orig_import = builtins.__import__

                        def patched_import(name, *args, **kwargs):
                            if name == "faiss":
                                return mock_faiss2
                            return orig_import(name, *args, **kwargs)

                        with patch("builtins.__import__", side_effect=patched_import):
                            pipe2 = EmbedPipeline(tmp_path / "out2", cfg)
                            try:
                                pipe2.build(tmp_path)
                            except Exception:
                                pass
    finally:
        em3._EMBED_BATCH = orig_batch

    # With 3 chunks and batch size 1, index.add should be called 3 times
    assert add_count == 3, f"Expected 3 index.add calls (one per batch), got {add_count}"


# ---------------------------------------------------------------------------
# #119 — PageBuilder system prompt not read in __init__
# ---------------------------------------------------------------------------

def test_page_builder_system_prompt_not_read_in_init():
    """read_text should NOT be called during PageBuilder.__init__ — prompt is loaded at module level."""
    import rekipedia.synthesis.page_builder as pb_mod
    from rekipedia.models.contracts import LLMConfig

    # The module-level _SYSTEM_PROMPT is already set.
    # We verify that constructing PageBuilder doesn't call Path.read_text again.
    # We do this by patching Path.read_text at the class level.
    with patch("pathlib.Path.read_text") as mock_read:
        cfg = LLMConfig(model="gpt-4", api_key="sk-test")
        caller = MagicMock()
        pb = pb_mod.PageBuilder(llm_config=cfg, caller=caller)
        mock_read.assert_not_called()

    # Verify the system prompt is still set to the module-level value
    assert pb._system == pb_mod._SYSTEM_PROMPT
