"""Cloud SQL schema provider and DDL loader."""
from __future__ import annotations

from pathlib import Path

SCHEMA_DIR = Path(__file__).resolve().parent.parent.parent.parent / "schemas" / "cloud_sql"
SCHEMA_SQL_PATH = SCHEMA_DIR / "001_graph_first_pgvector.sql"


def get_cloud_sql_schema_ddl() -> str:
    """Return the raw PostgreSQL + pgvector DDL schema script."""
    if SCHEMA_SQL_PATH.exists():
        return SCHEMA_SQL_PATH.read_text(encoding="utf-8")
    # Embedded fallback
    return """
    CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
    CREATE EXTENSION IF NOT EXISTS vector;
    CREATE TABLE IF NOT EXISTS projects (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), user_id TEXT NOT NULL, repo_url TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS symbols (id TEXT NOT NULL, project_id UUID REFERENCES projects(id), name TEXT NOT NULL, file_path TEXT NOT NULL, embedding vector(768), PRIMARY KEY (id, project_id));
    CREATE TABLE IF NOT EXISTS relationships (id BIGSERIAL PRIMARY KEY, project_id UUID REFERENCES projects(id), from_symbol_id TEXT, to_symbol_id TEXT, relationship_type TEXT);
    """
