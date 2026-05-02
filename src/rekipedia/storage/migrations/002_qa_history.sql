CREATE TABLE IF NOT EXISTS qa_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_path   TEXT    NOT NULL,
    question    TEXT    NOT NULL,
    answer      TEXT    NOT NULL,
    model       TEXT    NOT NULL DEFAULT '',
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
