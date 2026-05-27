-- Migration 006: git commit history tables
CREATE TABLE IF NOT EXISTS git_commits (
    hash TEXT PRIMARY KEY,
    short_hash TEXT,
    author TEXT,
    date TEXT,
    message TEXT,
    files_changed TEXT  -- JSON array
);

CREATE TABLE IF NOT EXISTS git_file_commits (
    file_path TEXT,
    commit_hash TEXT,
    PRIMARY KEY (file_path, commit_hash)
);
