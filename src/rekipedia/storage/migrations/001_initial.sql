-- close-wiki: initial schema
-- Migration 001 — run automatically on first `close-wiki init`

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ─────────────────────────────────────────────
-- Meta / versioning
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER PRIMARY KEY,
    applied_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
INSERT OR IGNORE INTO schema_version (version) VALUES (1);

-- ─────────────────────────────────────────────
-- Run log
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    command      TEXT    NOT NULL,          -- 'init' | 'scan' | 'update'
    started_at   TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    finished_at  TEXT,
    status       TEXT    NOT NULL DEFAULT 'running',  -- 'running' | 'ok' | 'error'
    error        TEXT
);

-- ─────────────────────────────────────────────
-- Repository snapshot
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS repo_snapshot (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       INTEGER REFERENCES runs(id),
    repo_root    TEXT    NOT NULL,
    commit_sha   TEXT,
    branch       TEXT,
    scanned_at   TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- ─────────────────────────────────────────────
-- Files
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS files (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id  INTEGER NOT NULL REFERENCES repo_snapshot(id),
    path         TEXT    NOT NULL,          -- relative to repo root
    language     TEXT,
    size_bytes   INTEGER,
    sha256       TEXT    NOT NULL,
    last_seen_at TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    UNIQUE (snapshot_id, path)
);
CREATE INDEX IF NOT EXISTS idx_files_sha256 ON files(sha256);

-- ─────────────────────────────────────────────
-- Content hashes (dedup / change detection)
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS content_hashes (
    path         TEXT    NOT NULL,
    sha256       TEXT    NOT NULL,
    recorded_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    PRIMARY KEY (path)
);

-- ─────────────────────────────────────────────
-- Symbols (functions, classes, types …)
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS symbols (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id      INTEGER NOT NULL REFERENCES files(id),
    name         TEXT    NOT NULL,
    kind         TEXT    NOT NULL,          -- 'function' | 'class' | 'type' | 'variable' | …
    line_start   INTEGER,
    line_end     INTEGER,
    docstring    TEXT,
    signature    TEXT
);
CREATE INDEX IF NOT EXISTS idx_symbols_file ON symbols(file_id);

-- ─────────────────────────────────────────────
-- Relationships (imports, calls, inherits …)
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS relationships (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    from_symbol  INTEGER REFERENCES symbols(id),
    to_symbol    INTEGER REFERENCES symbols(id),
    kind         TEXT    NOT NULL,          -- 'import' | 'call' | 'inherits' | 'uses'
    file_id      INTEGER REFERENCES files(id)
);

-- ─────────────────────────────────────────────
-- Wiki pages
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS pages (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    slug         TEXT    NOT NULL UNIQUE,
    title        TEXT    NOT NULL,
    body_md      TEXT    NOT NULL,
    generated_at TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    run_id       INTEGER REFERENCES runs(id)
);

-- ─────────────────────────────────────────────
-- Chunks (for RAG / Q&A)
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS chunks (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    page_id              INTEGER REFERENCES pages(id),
    file_id              INTEGER REFERENCES files(id),
    text                 TEXT    NOT NULL,
    token_count          INTEGER,
    embedding_vector_ref TEXT    -- path to compressed sidecar JSON (Phase 4)
);

-- ─────────────────────────────────────────────
-- Diagrams (Mermaid source)
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS diagrams (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    page_id      INTEGER REFERENCES pages(id),
    kind         TEXT    NOT NULL,          -- 'flowchart' | 'classDiagram' | 'sequenceDiagram' …
    source_mmd   TEXT    NOT NULL,
    generated_at TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- ─────────────────────────────────────────────
-- Q&A cache
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS qa_cache (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    question     TEXT    NOT NULL,
    answer       TEXT    NOT NULL,
    sources      TEXT,                      -- JSON array of chunk ids
    model        TEXT,
    asked_at     TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- ─────────────────────────────────────────────
-- Generator config (per-run LLM settings)
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS generator_config (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       INTEGER REFERENCES runs(id),
    model        TEXT    NOT NULL,
    temperature  REAL    NOT NULL DEFAULT 0.2,
    base_url     TEXT
);

-- ─────────────────────────────────────────────
-- Ignore rules (merged from config.yml + .gitignore)
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ignore_rules (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern TEXT    NOT NULL UNIQUE,
    source  TEXT    NOT NULL DEFAULT 'config'  -- 'config' | 'gitignore' | 'user'
);
