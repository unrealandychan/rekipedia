"""Tests for RAG MMR deduplication (issue #55)."""
import pytest


def test_mmr_requires_numpy():
    try:
        import numpy as np
    except ImportError:
        pytest.skip("numpy not available")

    import numpy as np

    from rekipedia.rag.embedder import _mmr

    # 10 vectors: first 5 are near-duplicates of [1, 0, 0]
    # last 5 are diverse (orthogonal directions)
    # Query is [1, 0, 0] so all near-dupes are most relevant
    rng = np.random.default_rng(42)
    base = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    # Make near-duplicates very close to base
    duplicates = np.array([base + rng.normal(0, 0.001, 3) for _ in range(5)], dtype=np.float32)
    diverse = np.array([
        [0.0, 1.0, 0.0],
        [0.0, 0.0, 1.0],
        [-1.0, 0.0, 0.0],
        [0.0, -1.0, 0.0],
        [0.707, 0.707, 0.0],
    ], dtype=np.float32)
    candidates = np.vstack([duplicates, diverse])
    query = base.copy()

    selected = _mmr(query, candidates, top_k=5, lambda_=0.3)
    assert len(selected) == 5

    # Count how many from the duplicate cluster (indices 0-4) were selected
    from_cluster = sum(1 for i in selected if i < 5)
    # MMR with low lambda should diversify heavily — pick at most 2 from cluster
    assert from_cluster <= 2, f"MMR selected {from_cluster} near-duplicates, expected ≤ 2"


def test_mmr_returns_all_when_small():
    try:
        import numpy as np
    except ImportError:
        pytest.skip("numpy not available")

    import numpy as np

    from rekipedia.rag.embedder import _mmr

    vecs = np.eye(3, dtype=np.float32)
    query = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    selected = _mmr(query, vecs, top_k=5)
    assert set(selected) == {0, 1, 2}


def test_mmr_top_k_count():
    try:
        import numpy as np
    except ImportError:
        pytest.skip("numpy not available")

    import numpy as np

    from rekipedia.rag.embedder import _mmr

    rng = np.random.default_rng(0)
    vecs = rng.random((20, 4)).astype(np.float32)
    query = rng.random(4).astype(np.float32)
    selected = _mmr(query, vecs, top_k=7)
    assert len(selected) == 7
    assert len(set(selected)) == 7  # no duplicates
