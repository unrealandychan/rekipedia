"""Tests for rekipedia.rag modules."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from rekipedia.models.contracts import LLMConfig
from rekipedia.rag.scan_meta import patch_scan_meta, read_scan_meta, write_scan_meta


# ---------------------------------------------------------------------------
# scan_meta
# ---------------------------------------------------------------------------


def test_write_and_read_scan_meta(tmp_path: Path) -> None:
    path = write_scan_meta(
        tmp_path,
        repo_path="/repo",
        model="llama4",
        run_id="abc-123",
        file_count=42,
        page_count=9,
    )
    assert path.exists()
    meta = read_scan_meta(tmp_path)
    assert meta is not None
    assert meta["model"] == "llama4"
    assert meta["file_count"] == 42
    assert meta["page_count"] == 9
    assert meta["run_id"] == "abc-123"
    assert meta["embedded"] is False


def test_patch_scan_meta(tmp_path: Path) -> None:
    write_scan_meta(
        tmp_path,
        repo_path="/repo",
        model="llama4",
        run_id="abc",
        file_count=10,
        page_count=5,
    )
    patch_scan_meta(tmp_path, embedded=True, embed_model="text-embedding-3-small")
    meta = read_scan_meta(tmp_path)
    assert meta["embedded"] is True
    assert meta["embed_model"] == "text-embedding-3-small"
    # Existing fields preserved
    assert meta["model"] == "llama4"


def test_read_scan_meta_missing(tmp_path: Path) -> None:
    assert read_scan_meta(tmp_path) is None


# ---------------------------------------------------------------------------
# EmbedPipeline
# ---------------------------------------------------------------------------


def _fake_embed_response(texts: list[str], dim: int = 4):
    """Return a fake litellm embedding response dict-like."""
    rng = np.random.default_rng(0)
    vecs = rng.random((len(texts), dim), dtype=np.float32).tolist()
    items = [{"embedding": v} for v in vecs]
    resp = MagicMock()
    resp.data = items
    return resp


def _make_test_repo(tmp_path: Path) -> Path:
    """Create a minimal repo with a few source files."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "main.py").write_text("def hello():\n    print('hi')\n")
    (repo / "utils.py").write_text("def add(a, b):\n    return a + b\n")
    (repo / "README.md").write_text("# Test repo\n\nA minimal test repository.\n")
    return repo


def test_embed_pipeline_build_and_search(tmp_path: Path) -> None:
    from rekipedia.rag.embedder import EmbedPipeline

    repo = _make_test_repo(tmp_path)
    out_dir = tmp_path / ".rekipedia"
    out_dir.mkdir()

    llm_config = LLMConfig()

    with patch("rekipedia.rag.embedder._embed_batch") as mock_embed:
        mock_embed.side_effect = lambda texts, model, cfg: (
            np.random.default_rng(42).random((len(texts), 8)).astype(np.float32)
        )

        pipe = EmbedPipeline(out_dir, llm_config)
        assert not pipe.is_built()

        n = pipe.build(repo)
        assert n > 0
        assert pipe.is_built()

        # meta
        meta = pipe.meta()
        assert meta is not None
        assert meta["n_chunks"] == n
        assert meta["dim"] == 8

        # search
        results = pipe.search("add function", top_k=3)
        assert isinstance(results, list)
        assert len(results) <= 3
        for r in results:
            assert "file" in r
            assert "text" in r
            assert "score" in r


def test_embed_pipeline_search_no_index(tmp_path: Path) -> None:
    from rekipedia.rag.embedder import EmbedPipeline

    out_dir = tmp_path / ".rekipedia"
    out_dir.mkdir()
    pipe = EmbedPipeline(out_dir, LLMConfig())
    assert pipe.search("anything") == []


def test_embed_pipeline_skips_large_file(tmp_path: Path) -> None:
    from rekipedia.rag.embedder import _chunk_file, _MAX_CODE_CHARS

    f = tmp_path / "big.py"
    f.write_text("x = 1\n" * (_MAX_CODE_CHARS // 6 + 100))  # exceeds limit
    chunks = _chunk_file(f, tmp_path)
    assert chunks == []


def test_embed_pipeline_chunks_normal_file(tmp_path: Path) -> None:
    from rekipedia.rag.embedder import _chunk_file

    f = tmp_path / "small.py"
    f.write_text("def foo():\n    pass\n")
    chunks = _chunk_file(f, tmp_path)
    assert len(chunks) >= 1
    assert chunks[0]["file"] == "small.py"
    assert chunks[0]["is_code"] is True


def test_is_implementation_heuristic() -> None:
    from rekipedia.rag.embedder import _is_implementation

    assert _is_implementation("src/core/engine.py") is True
    assert _is_implementation("tests/test_engine.py") is False
    assert _is_implementation("test_utils.py") is False
    assert _is_implementation("src/utils.ts") is True
