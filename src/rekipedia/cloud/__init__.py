"""rekipedia-cloud integrations: Cloud SQL schemas, hybrid retrieval, and incremental sync."""
from rekipedia.cloud.retrieval import execute_hybrid_search, merge_and_rerank
from rekipedia.cloud.schema import get_cloud_sql_schema_ddl
from rekipedia.cloud.sync import (
    GCS_ARTIFACT_SPEC,
    compute_repo_fingerprints,
    diff_fingerprints,
)

__all__ = [
    "GCS_ARTIFACT_SPEC",
    "compute_repo_fingerprints",
    "diff_fingerprints",
    "execute_hybrid_search",
    "get_cloud_sql_schema_ddl",
    "merge_and_rerank",
]
