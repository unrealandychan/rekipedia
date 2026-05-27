CREATE TABLE IF NOT EXISTS external_sources (
    id TEXT PRIMARY KEY,           -- e.g. "github_issue:owner/repo#123"
    source_type TEXT,
    source_id TEXT,
    title TEXT,
    body TEXT,
    url TEXT,
    state TEXT,
    labels TEXT,                   -- JSON array
    date TEXT,
    files_changed TEXT             -- JSON array
);

CREATE TABLE IF NOT EXISTS source_symbol_links (
    source_id TEXT,
    symbol_name TEXT,
    link_type TEXT,                -- "file_changed" | "mentioned"
    PRIMARY KEY (source_id, symbol_name, link_type)
);
