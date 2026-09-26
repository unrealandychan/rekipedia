-- rekipedia-cloud: Graph-First Cloud SQL Schema (PostgreSQL 16 + pgvector)
-- Supports deterministic graph traversal alongside dense semantic vector retrieval.

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS vector;

-- ── 1. Projects & Tenant Isolation ───────────────────────────────────────────
CREATE TABLE IF NOT EXISTS projects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL,                          -- Auth provider (e.g. Clerk user ID)
    repo_url TEXT NOT NULL,
    display_name TEXT,
    last_scanned_at TIMESTAMPTZ,
    scan_status TEXT DEFAULT 'pending',             -- 'pending' | 'scanning' | 'ready' | 'error'
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ── 2. Communities (Louvain / Leiden clusters) ──────────────────────────────
CREATE TABLE IF NOT EXISTS communities (
    id INTEGER NOT NULL,
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
    label TEXT,                                     -- Plain-language cluster name
    cohesion_score REAL DEFAULT 0.0,                -- intra_edges / max_possible_intra_edges
    symbol_count INTEGER DEFAULT 0,
    PRIMARY KEY (id, project_id)
);

-- ── 3. Symbols (Graph Nodes) ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS symbols (
    id TEXT NOT NULL,                               -- Stable ID: "file_path::SymbolName"
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    symbol_type TEXT,                               -- 'function' | 'class' | 'interface' | 'module'
    file_path TEXT NOT NULL,
    layer TEXT,                                     -- 'API' | 'Service' | 'Repository' | 'Model' | 'Utility'
    community_id INTEGER,                           -- Reference to communities(id, project_id)
    fingerprint TEXT,                               -- SHA-256 for incremental file change skipping
    summary TEXT,                                   -- LLM-generated architectural summary
    embedding vector(768),                          -- Vertex AI text-embedding-005 (768 dims)
    confidence_level TEXT DEFAULT 'EXTRACTED',      -- 'EXTRACTED' | 'INFERRED' | 'AMBIGUOUS'
    confidence_score REAL DEFAULT 1.0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (id, project_id)
);

-- ── 4. Relationships (Graph Edges) ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS relationships (
    id BIGSERIAL PRIMARY KEY,
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
    from_symbol_id TEXT NOT NULL,
    to_symbol_id TEXT NOT NULL,
    relationship_type TEXT NOT NULL,                -- 'imports' | 'calls' | 'inherits' | 'uses'
    confidence_level TEXT DEFAULT 'EXTRACTED',      -- 'EXTRACTED' | 'INFERRED' | 'AMBIGUOUS'
    confidence_score REAL DEFAULT 1.0
);

-- ── 5. Hyperedges (N-ary Design Patterns) ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS hyperedges (
    id TEXT NOT NULL,
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
    concept TEXT NOT NULL,
    description TEXT,
    confidence_level TEXT DEFAULT 'INFERRED',
    pattern_type TEXT DEFAULT 'design_pattern',
    PRIMARY KEY (id, project_id)
);

CREATE TABLE IF NOT EXISTS hyperedge_members (
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
    hyperedge_id TEXT NOT NULL,
    symbol_id TEXT NOT NULL,
    PRIMARY KEY (project_id, hyperedge_id, symbol_id)
);

-- ── 6. Performance Indexes ───────────────────────────────────────────────────
-- Vector similarity index (ivfflat with cosine distance)
CREATE INDEX IF NOT EXISTS idx_symbols_embedding_cosine
    ON symbols USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- Graph & lookup indexes
CREATE INDEX IF NOT EXISTS idx_symbols_project_community
    ON symbols (project_id, community_id);

CREATE INDEX IF NOT EXISTS idx_symbols_project_layer
    ON symbols (project_id, layer);

CREATE INDEX IF NOT EXISTS idx_symbols_project_fingerprint
    ON symbols (project_id, fingerprint);

CREATE INDEX IF NOT EXISTS idx_relationships_from
    ON relationships (project_id, from_symbol_id);

CREATE INDEX IF NOT EXISTS idx_relationships_to
    ON relationships (project_id, to_symbol_id);
