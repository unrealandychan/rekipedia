"""Tests for rekipedia.rag modules."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

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
    from rekipedia.rag.embedder import _MAX_CODE_CHARS, _chunk_file

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


# ---------------------------------------------------------------------------
# Issue #75: chunk-level provenance
# ---------------------------------------------------------------------------


def test_chunk_file_includes_line_provenance(tmp_path: Path) -> None:
    """_chunk_file should include start_line, end_line, text_hash in each chunk."""
    from rekipedia.rag.embedder import _chunk_file

    f = tmp_path / "foo.py"
    f.write_text("line1\nline2\nline3\n" * 100)  # enough for multiple chunks
    chunks = _chunk_file(f, tmp_path)
    assert len(chunks) > 0
    for c in chunks:
        assert "start_line" in c
        assert "end_line" in c
        assert "text_hash" in c
        assert "end_char" in c
        assert c["start_line"] >= 1
        assert c["end_line"] >= c["start_line"]
        assert len(c["text_hash"]) == 64  # SHA-256 hex


def test_chunk_file_first_chunk_starts_at_line_1(tmp_path: Path) -> None:
    from rekipedia.rag.embedder import _chunk_file

    f = tmp_path / "foo.py"
    f.write_text("def hello():\n    pass\n")
    chunks = _chunk_file(f, tmp_path)
    assert chunks[0]["start_line"] == 1


def test_sqlite_store_upsert_and_get_rag_chunks(tmp_path: Path) -> None:
    """upsert_rag_chunks + get_rag_chunks_by_file round-trip."""
    from rekipedia.storage.sqlite_store import SqliteStore

    store = SqliteStore(tmp_path / "store.db")
    store.open()
    run_id = "run-test-001"
    store.upsert_run(run_id, "/tmp/repo")
    chunks = [
        {"file_path": "foo.py", "chunk_idx": 0, "start_line": 1, "end_line": 10,
         "start_char": 0, "end_char": 200, "text_hash": "abc123", "is_code": True, "is_implementation": True},
        {"file_path": "foo.py", "chunk_idx": 1, "start_line": 9, "end_line": 20,
         "start_char": 180, "end_char": 400, "text_hash": "def456", "is_code": True, "is_implementation": True},
    ]
    store.upsert_rag_chunks(run_id, chunks)
    result = store.get_rag_chunks_by_file(run_id, "foo.py")
    assert len(result) == 2
    assert result[0]["start_line"] == 1
    assert result[0]["text_hash"] == "abc123"
    assert result[1]["chunk_idx"] == 1
    store.close()


def test_sqlite_store_get_all_rag_chunks(tmp_path: Path) -> None:
    from rekipedia.storage.sqlite_store import SqliteStore

    store = SqliteStore(tmp_path / "store.db")
    store.open()
    run_id = "run-test-002"
    store.upsert_run(run_id, "/tmp/repo")
    chunks = [
        {"file_path": "a.py", "chunk_idx": 0, "start_line": 1, "end_line": 5,
         "start_char": 0, "end_char": 100, "text_hash": "aaa", "is_code": True, "is_implementation": True},
        {"file_path": "b.py", "chunk_idx": 0, "start_line": 1, "end_line": 3,
         "start_char": 0, "end_char": 50, "text_hash": "bbb", "is_code": True, "is_implementation": False},
    ]
    store.upsert_rag_chunks(run_id, chunks)
    all_chunks = store.get_all_rag_chunks(run_id)
    assert len(all_chunks) == 2
    files = {c["file_path"] for c in all_chunks}
    assert files == {"a.py", "b.py"}
    store.close()


def test_embed_pipeline_persists_provenance(tmp_path: Path) -> None:
    """EmbedPipeline.build() should call upsert_rag_chunks when store is provided."""
    from unittest.mock import MagicMock
    from unittest.mock import patch as mpatch

    from rekipedia.rag.embedder import EmbedPipeline

    store = MagicMock()
    pipeline = EmbedPipeline(tmp_path, LLMConfig(), store=store, run_id="run-42")
    # Create fake repo with one file
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "foo.py").write_text("def hello():\n    pass\n")
    mock_embed = MagicMock(return_value=np.array([[0.1] * 1536], dtype="float32"))
    with mpatch("rekipedia.rag.embedder._embed_batch", mock_embed):
        pipeline.build(repo)
    store.upsert_rag_chunks.assert_called_once()
    args = store.upsert_rag_chunks.call_args[0]
    assert args[0] == "run-42"  # run_id
    provenance = args[1]
    assert len(provenance) >= 1
    assert "start_line" in provenance[0]
    assert "text_hash" in provenance[0]


# ---------------------------------------------------------------------------
# update() tests
# ---------------------------------------------------------------------------

def test_embed_pipeline_update_skips_unchanged_files(tmp_path):
    """update() should only re-embed chunks from changed files."""
    from unittest.mock import patch as mpatch2

    from rekipedia.models.contracts import LLMConfig as LC
    from rekipedia.rag.embedder import EmbedPipeline

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "unchanged.py").write_text("def foo():\n    pass\n" * 50)
    (repo / "changed.py").write_text("def bar():\n    pass\n" * 50)

    pipeline = EmbedPipeline(tmp_path, LC())

    fake_vec = np.array([[0.1] * 1536], dtype="float32")
    embed_call_count = []

    def mock_embed(texts, model, cfg):
        embed_call_count.append(len(texts))
        return np.tile(fake_vec, (len(texts), 1))

    with mpatch2("rekipedia.rag.embedder._embed_batch", mock_embed):
        total = pipeline.build(repo)

    calls_on_build = sum(embed_call_count)
    embed_call_count.clear()

    # Update with only "changed.py" as changed
    (repo / "changed.py").write_text("def bar_v2():\n    pass\n" * 50)

    with mpatch2("rekipedia.rag.embedder._embed_batch", mock_embed):
        re_embedded = pipeline.update(
            repo_root=repo,
            changed_files=["changed.py"],
            last_run_id=None,
            new_run_id=None,
        )

    calls_on_update = sum(embed_call_count)
    assert re_embedded < total
    assert calls_on_update < calls_on_build


def test_embed_pipeline_update_falls_back_to_build_if_no_index(tmp_path):
    """update() should fall back to build() if no existing index found."""
    from unittest.mock import patch as mpatch2

    from rekipedia.models.contracts import LLMConfig as LC
    from rekipedia.rag.embedder import EmbedPipeline

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "foo.py").write_text("def hello():\n    pass\n")

    pipeline = EmbedPipeline(tmp_path, LC())
    fake_vec = np.array([[0.1] * 1536], dtype="float32")
    with mpatch2("rekipedia.rag.embedder._embed_batch", lambda t, m, c: np.tile(fake_vec, (len(t), 1))):
        n = pipeline.update(repo, ["foo.py"], None, None)

    assert n > 0
    assert pipeline.is_built()


def test_carry_forward_rag_chunks(tmp_path):
    import uuid

    from rekipedia.storage.sqlite_store import SqliteStore

    store = SqliteStore(tmp_path / "store.db")
    store.open()
    run1 = str(uuid.uuid4())
    run2 = str(uuid.uuid4())
    store.upsert_run(run1, "/repo")
    store.upsert_run(run2, "/repo")
    chunks = [
        {"file_path": "a.py", "chunk_idx": 0, "start_line": 1, "end_line": 5,
         "start_char": 0, "end_char": 100, "text_hash": "aaa", "is_code": True, "is_implementation": True},
        {"file_path": "b.py", "chunk_idx": 0, "start_line": 1, "end_line": 3,
         "start_char": 0, "end_char": 50, "text_hash": "bbb", "is_code": True, "is_implementation": False},
    ]
    store.upsert_rag_chunks(run1, chunks)
    n = store.carry_forward_rag_chunks(run1, run2, ["a.py"])
    assert n == 1
    result = store.get_rag_chunks_by_file(run2, "a.py")
    assert len(result) == 1
    assert result[0]["text_hash"] == "aaa"
    result_b = store.get_rag_chunks_by_file(run2, "b.py")
    assert len(result_b) == 0
    store.close()


# ---------------------------------------------------------------------------
# _symbol_chunk_file tests
# ---------------------------------------------------------------------------

from rekipedia.rag.embedder import _symbol_chunk_file  # noqa: E402


def test_symbol_chunk_file_python_basic(tmp_path):
    """Symbol chunker should produce chunks for a Python file with functions."""
    content = '''
def alpha():
    """Alpha function."""
    return 1

def beta():
    """Beta function."""
    x = 1 + 2
    return x

class Gamma:
    def method_one(self):
        pass
    
    def method_two(self):
        pass
'''
    f = tmp_path / "sample.py"
    f.write_text(content)
    chunks = _symbol_chunk_file(f, tmp_path)
    # Should produce at least 1 chunk
    assert len(chunks) >= 1
    # All chunks have required fields
    for c in chunks:
        assert "start_line" in c
        assert "end_line" in c
        assert "text_hash" in c
        assert "file" in c
        assert c["start_line"] >= 1


def test_symbol_chunk_file_fallback_for_unsupported_ext(tmp_path):
    """Symbol chunker should fall back to char-based for unsupported file types."""
    f = tmp_path / "README.md"
    f.write_text("# Hello\n\nThis is a readme.\n" * 100)
    chunks = _symbol_chunk_file(f, tmp_path)
    assert len(chunks) >= 1
    for c in chunks:
        assert "text_hash" in c


def test_symbol_chunk_file_fallback_on_tssitter_missing(tmp_path, monkeypatch):
    """Symbol chunker should fall back gracefully if tree-sitter is not installed."""
    import sys
    # Simulate tree_sitter_python not available
    monkeypatch.setitem(sys.modules, "tree_sitter_python", None)
    f = tmp_path / "code.py"
    f.write_text("def foo():\n    pass\n" * 20)
    chunks = _symbol_chunk_file(f, tmp_path)
    assert len(chunks) >= 1


def test_symbol_chunk_file_large_function_splits(tmp_path):
    """A single very large function should be split into multiple chunks."""
    big_func = "def big_fn():\n" + "    x = 1\n" * 1000
    f = tmp_path / "big.py"
    f.write_text(big_func)
    chunks = _symbol_chunk_file(f, tmp_path)
    assert len(chunks) >= 2  # too big for one chunk
