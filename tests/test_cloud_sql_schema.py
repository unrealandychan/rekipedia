"""Tests for Issue #232: Graph-First Cloud SQL Schema and Hybrid Retrieval."""
from __future__ import annotations

from pathlib import Path
import pytest

from rekipedia.cloud.schema import get_cloud_sql_schema_ddl
from rekipedia.cloud.retrieval import merge_and_rerank
from rekipedia.cloud.sync import (
    compute_repo_fingerprints,
    diff_fingerprints,
    GCS_ARTIFACT_SPEC,
)


def test_cloud_sql_schema_ddl_completeness():
    """Verify DDL script defines all required tables, columns, and vector indexes."""
    ddl = get_cloud_sql_schema_ddl()

    # Core tables
    assert "CREATE TABLE IF NOT EXISTS projects" in ddl
    assert "CREATE TABLE IF NOT EXISTS symbols" in ddl
    assert "CREATE TABLE IF NOT EXISTS relationships" in ddl
    assert "CREATE TABLE IF NOT EXISTS communities" in ddl
    assert "CREATE TABLE IF NOT EXISTS hyperedges" in ddl

    # Required symbol columns
    assert "community_id INTEGER" in ddl
    assert "layer TEXT" in ddl
    assert "fingerprint TEXT" in ddl
    assert "confidence_level TEXT" in ddl
    assert "embedding vector(768)" in ddl

    # Required relationship columns
    assert "confidence_level TEXT" in ddl
    assert "confidence_score REAL" in ddl

    # Vector index
    assert "ivfflat (embedding vector_cosine_ops)" in ddl


def test_merge_and_rerank_scoring():
    """Verify hybrid merge applies correct weighting and boosts co-occurring symbols."""
    vector_results = [
        {"id": "sym_A", "score": 0.9, "name": "SymA"},
        {"id": "sym_B", "score": 0.6, "name": "SymB"},
    ]
    graph_neighbors = [
        {"id": "sym_B", "confidence_score": 1.0, "name": "SymB"},
        {"id": "sym_C", "confidence_score": 0.8, "name": "SymC"},
    ]

    ranked = merge_and_rerank(vector_results, graph_neighbors, vector_weight=0.7, graph_weight=0.3)
    assert len(ranked) == 3

    # sym_B received both vector (0.6 * 0.7 = 0.42) and graph boost (1.0 * 0.3 = 0.3) -> 0.72
    # sym_A received vector (0.9 * 0.7 = 0.63)
    # sym_C received only graph (0.8 * 0.3 = 0.24)
    ranked_map = {item["id"]: item for item in ranked}
    assert ranked_map["sym_B"]["combined_score"] == pytest.approx(0.72, abs=1e-4)
    assert ranked_map["sym_B"]["retrieval_source"] == "hybrid"

    assert ranked_map["sym_A"]["combined_score"] == pytest.approx(0.63, abs=1e-4)
    assert ranked_map["sym_A"]["retrieval_source"] == "vector"

    assert ranked_map["sym_C"]["combined_score"] == pytest.approx(0.24, abs=1e-4)
    assert ranked_map["sym_C"]["retrieval_source"] == "graph_expansion"

    # Sorted order: sym_B, sym_A, sym_C
    assert [r["id"] for r in ranked] == ["sym_B", "sym_A", "sym_C"]


def test_diff_fingerprints_incremental_sync(tmp_path: Path):
    """Verify SHA-256 fingerprint diffing correctly classifies modified, added, deleted files."""
    f1 = tmp_path / "a.py"
    f2 = tmp_path / "b.py"
    f3 = tmp_path / "c.py"

    f1.write_text("print('hello')")
    f2.write_text("print('world')")

    old_fp = compute_repo_fingerprints(tmp_path, ["a.py", "b.py"])

    # Modify b.py, delete a.py, add c.py
    f2.write_text("print('world modified')")
    f3.write_text("print('new')")

    new_fp = compute_repo_fingerprints(tmp_path, ["b.py", "c.py"])

    diff = diff_fingerprints(old_fp, new_fp)
    assert diff["added"] == {"c.py"}
    assert diff["modified"] == {"b.py"}
    assert diff["deleted"] == {"a.py"}
    assert diff["requires_update"] == {"b.py", "c.py"}
    assert "gs://rekipedia-artifacts" in GCS_ARTIFACT_SPEC
