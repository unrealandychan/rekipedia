"""Cloud Run Hybrid Retrieval: combines pgvector dense semantic search with deterministic 1-hop graph expansion."""
from __future__ import annotations

from typing import Any


def merge_and_rerank(
    vector_results: list[dict[str, Any]],
    graph_neighbors: list[dict[str, Any]],
    vector_weight: float = 0.7,
    graph_weight: float = 0.3,
) -> list[dict[str, Any]]:
    """Merge vector search hits with graph neighbors, re-ranking by blended relevance.

    Args:
        vector_results: Results from pgvector search, each having 'id', 'score' (0..1), etc.
        graph_neighbors: Neighboring nodes reached via 1-hop structural relationships.
        vector_weight: Weight assigned to semantic vector score (default 0.7).
        graph_weight: Weight assigned to structural graph proximity (default 0.3).

    Returns:
        List of combined results sorted descending by combined_score.
    """
    merged: dict[str, dict[str, Any]] = {}

    # 1. Process vector results
    for rank, item in enumerate(vector_results):
        node_id = item["id"]
        v_score = float(item.get("score", 1.0 / (rank + 1)))
        entry = dict(item)
        entry["vector_score"] = v_score
        entry["graph_boost"] = 0.0
        entry["combined_score"] = v_score * vector_weight
        entry["retrieval_source"] = "vector"
        merged[node_id] = entry

    # 2. Process graph neighbors (1-hop expansion)
    for neighbor in graph_neighbors:
        node_id = neighbor["id"]
        conf = float(neighbor.get("confidence_score", 1.0))
        if node_id in merged:
            # Node was retrieved both semantically and structurally -> apply graph boost
            merged[node_id]["graph_boost"] = conf * graph_weight
            merged[node_id]["combined_score"] += conf * graph_weight
            merged[node_id]["retrieval_source"] = "hybrid"
        else:
            # Node was only found via graph proximity
            entry = dict(neighbor)
            entry["vector_score"] = 0.0
            entry["graph_boost"] = conf * graph_weight
            entry["combined_score"] = conf * graph_weight
            entry["retrieval_source"] = "graph_expansion"
            merged[node_id] = entry

    ranked = sorted(merged.values(), key=lambda x: x["combined_score"], reverse=True)
    return ranked


async def execute_hybrid_search(
    db_conn: Any,  # noqa: ANN401
    project_id: str,
    query_embedding: list[float],
    top_k: int = 10,
    confidence_threshold: float = 0.5,
) -> list[dict[str, Any]]:
    """Execute hybrid retrieval against PostgreSQL + pgvector Cloud SQL.

    1. Vector search: find semantically similar symbols via pgvector cosine distance.
    2. Graph expansion: for each hit, fetch 1-hop neighbors via relationships table.
    3. Merge + re-rank: combine scores into unified, ranked context.
    """
    embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"

    # Step 1: pgvector ANN search
    vector_query = """
        SELECT id, name, summary, symbol_type, file_path, layer, 1 - (embedding <=> $1::vector) AS score
        FROM symbols
        WHERE project_id = $2
        ORDER BY embedding <=> $1::vector
        LIMIT $3
    """
    vector_results = await db_conn.fetch(vector_query, embedding_str, project_id, top_k)
    vector_dicts = [dict(r) for r in vector_results]

    if not vector_dicts:
        return []

    # Step 2: 1-hop graph expansion
    symbol_ids = [r["id"] for r in vector_dicts]
    graph_query = """
        SELECT DISTINCT s.id, s.name, s.summary, s.symbol_type, s.file_path, s.layer,
                        r.confidence_score, r.relationship_type
        FROM symbols s
        JOIN relationships r ON s.id = r.to_symbol_id
        WHERE r.from_symbol_id = ANY($1)
          AND s.project_id = $2
          AND r.confidence_score >= $3
    """
    neighbors = await db_conn.fetch(graph_query, symbol_ids, project_id, confidence_threshold)
    neighbor_dicts = [dict(r) for r in neighbors]

    # Step 3: Merge and re-rank
    return merge_and_rerank(vector_dicts, neighbor_dicts)
