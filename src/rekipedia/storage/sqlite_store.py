"""Persistence layer for rekipedia.

Uses Turso (pyturso) when available — MVCC engine, cross-platform pre-built
wheels for macOS and Linux x86_64.  Falls back transparently to the stdlib
``sqlite3`` module on platforms where a pyturso wheel is not yet available
(e.g. Linux aarch64, Windows).  The public API of SqliteStore is identical
in both modes.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import turso as _db

    def _connect(path: str) -> Any:
        return _db.connect(path)

    _BACKEND = "turso"
except ImportError:  # pragma: no cover — only hit on platforms without a wheel
    import sqlite3 as _db_sqlite3  # type: ignore[assignment]

    def _connect(path: str) -> Any:  # type: ignore[misc]
        conn = _db_sqlite3.connect(path, isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    _BACKEND = "sqlite3"


_MIGRATIONS_DIR = Path(__file__).parent / "migrations"

# Type alias — the connection object type differs between backends.
_Conn = Any


class SqliteStore:
    """Wraps a database connection for the rekipedia store.

    Uses Turso (pyturso) when available; falls back to stdlib sqlite3.
    Usage::

        store = SqliteStore(Path(".rekipedia/store.db"))
        store.open()
        # … use store methods …
        store.close()

    Also usable as a context manager::

        with SqliteStore(path) as store:
            store.upsert_run(run_id, repo_path)
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._conn: _Conn | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def open(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = _connect(str(self._path))
        self._apply_migrations()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "SqliteStore":
        self.open()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @property
    def _c(self) -> _Conn:
        if self._conn is None:
            raise RuntimeError("SqliteStore is not open. Call open() first.")
        return self._conn

    @property
    def db(self) -> _Conn:
        """Raw Turso connection. Prefer the typed helper methods over direct access."""
        return self._c

    def table_names(self) -> set[str]:
        """Return names of all user tables in the database."""
        return self._table_names()

    def _table_names(self) -> set[str]:
        rows = self._c.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        return {r[0] for r in rows}

    def current_schema_version(self) -> int:
        try:
            row = self._c.execute("SELECT MAX(version) FROM schema_version").fetchone()
            return row[0] or 0
        except Exception:
            return 0

    # ------------------------------------------------------------------
    # Migrations
    # ------------------------------------------------------------------

    def _apply_migrations(self) -> None:
        current = self.current_schema_version()
        sql_files = sorted(_MIGRATIONS_DIR.glob("*.sql"))
        for sql_file in sql_files:
            version = int(sql_file.stem.split("_")[0])
            if version > current:
                sql = sql_file.read_text(encoding="utf-8")
                for stmt in sql.split(";"):
                    # Strip leading comment lines so blocks like
                    # "-- comment\nCREATE TABLE ..." are not skipped.
                    lines = [line for line in stmt.splitlines() if not line.strip().startswith("--")]
                    stmt = "\n".join(lines).strip()
                    if stmt:
                        self._conn.execute(stmt)
                self._conn.commit()

    # ------------------------------------------------------------------
    # Run lifecycle
    # ------------------------------------------------------------------

    def upsert_run(self, run_id: str, repo_path: str, status: str = "running") -> None:
        self._c.execute(
            """
            CREATE TABLE IF NOT EXISTS scan_runs (
                id TEXT PRIMARY KEY,
                repo_path TEXT,
                status TEXT,
                started_at TEXT,
                finished_at TEXT
            )
            """
        )
        self._c.execute(
            """
            INSERT INTO scan_runs (id, repo_path, status, started_at, finished_at)
            VALUES (?, ?, ?, ?, NULL)
            ON CONFLICT(id) DO UPDATE SET
                repo_path=excluded.repo_path,
                status=excluded.status,
                started_at=excluded.started_at
            """,
            [run_id, repo_path, status, _now()],
        )
        self._c.commit()

    def update_run_status(self, run_id: str, status: str) -> None:
        self._c.execute(
            "UPDATE scan_runs SET status=?, finished_at=? WHERE id=?",
            [status, _now(), run_id],
        )
        self._c.commit()

    # ------------------------------------------------------------------
    # Snapshot + files
    # ------------------------------------------------------------------

    def upsert_snapshot(self, run_id: str, files: list[dict[str, Any]]) -> None:
        self._c.execute(
            """
            CREATE TABLE IF NOT EXISTS scan_snapshots (
                run_id TEXT PRIMARY KEY,
                file_count INTEGER,
                created_at TEXT
            )
            """
        )
        self._c.execute(
            """
            INSERT INTO scan_snapshots(run_id, file_count, created_at) VALUES(?, ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET
                file_count=excluded.file_count,
                created_at=excluded.created_at
            """,
            [run_id, len(files), _now()],
        )
        self._c.commit()

    def upsert_file(self, run_id: str, path: str, sha256: str, size_bytes: int, language: str | None) -> None:
        self._c.execute(
            """
            CREATE TABLE IF NOT EXISTS scan_files (
                run_id TEXT,
                path TEXT,
                sha256 TEXT,
                size_bytes INTEGER,
                language TEXT,
                PRIMARY KEY(run_id, path)
            )
            """
        )
        self._c.execute(
            """
            INSERT INTO scan_files(run_id, path, sha256, size_bytes, language) VALUES(?, ?, ?, ?, ?)
            ON CONFLICT(run_id, path) DO UPDATE SET
                sha256=excluded.sha256,
                size_bytes=excluded.size_bytes,
                language=excluded.language
            """,
            [run_id, path, sha256, size_bytes, language],
        )
        self._c.commit()

    # ------------------------------------------------------------------
    # Symbols + relationships
    # ------------------------------------------------------------------

    def upsert_symbols(self, run_id: str, symbols: list[dict[str, Any]]) -> None:
        if not symbols:
            return
        self._c.execute(
            """
            CREATE TABLE IF NOT EXISTS scan_symbols (
                run_id TEXT,
                name TEXT,
                kind TEXT,
                file TEXT,
                line_start INTEGER,
                line_end INTEGER,
                signature TEXT,
                docstring TEXT,
                PRIMARY KEY(run_id, name, file)
            )
            """
        )
        rows = [
            (
                run_id,
                s.get("name", ""),
                s.get("kind", ""),
                s.get("file", ""),
                s.get("line_start"),
                s.get("line_end"),
                s.get("signature"),
                s.get("docstring"),
            )
            for s in symbols
        ]
        self._c.executemany(
            """
            INSERT OR REPLACE INTO scan_symbols(run_id, name, kind, file, line_start, line_end, signature, docstring)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        self._c.commit()

    def upsert_relationships(self, run_id: str, relationships: list[dict[str, Any]]) -> None:
        if not relationships:
            return
        self._c.execute(
            """
            CREATE TABLE IF NOT EXISTS scan_relationships (
                run_id TEXT,
                from_ TEXT,
                "to" TEXT,
                kind TEXT,
                file TEXT,
                confidence REAL DEFAULT 1.0,
                evidence_tag TEXT DEFAULT 'EXTRACTED',
                PRIMARY KEY(run_id, from_, "to", kind)
            )
            """
        )
        rows = [
            (
                run_id,
                r.get("from") or r.get("from_", ""),
                r.get("to", ""),
                r.get("kind", ""),
                r.get("file"),
                r.get("confidence", 1.0),
                r.get("evidence_tag", "EXTRACTED"),
            )
            for r in relationships
        ]
        self._c.executemany(
            """
            INSERT OR REPLACE INTO scan_relationships(run_id, from_, "to", kind, file, confidence, evidence_tag)
            VALUES(?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        self._c.commit()

    # ------------------------------------------------------------------
    # Wiki pages + diagrams
    # ------------------------------------------------------------------

    def upsert_page(self, run_id: str, slug: str, title: str, content: str, pinned: bool = False) -> None:
        self._c.execute(
            """
            CREATE TABLE IF NOT EXISTS scan_wiki_pages (
                run_id TEXT,
                slug TEXT,
                title TEXT,
                content TEXT,
                pinned INTEGER,
                updated_at TEXT,
                PRIMARY KEY(run_id, slug)
            )
            """
        )
        self._c.execute(
            """
            INSERT INTO scan_wiki_pages(run_id, slug, title, content, pinned, updated_at)
            VALUES(?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id, slug) DO UPDATE SET
                title=excluded.title,
                content=excluded.content,
                pinned=excluded.pinned,
                updated_at=excluded.updated_at
            """,
            [run_id, slug, title, content, int(pinned), _now()],
        )
        self._c.commit()

    def upsert_diagram(self, run_id: str, name: str, diagram_type: str, content: str) -> None:
        self._c.execute(
            """
            CREATE TABLE IF NOT EXISTS scan_diagrams (
                run_id TEXT,
                name TEXT,
                type TEXT,
                content TEXT,
                updated_at TEXT,
                PRIMARY KEY(run_id, name)
            )
            """
        )
        self._c.execute(
            """
            INSERT INTO scan_diagrams(run_id, name, type, content, updated_at)
            VALUES(?, ?, ?, ?, ?)
            ON CONFLICT(run_id, name) DO UPDATE SET
                type=excluded.type,
                content=excluded.content,
                updated_at=excluded.updated_at
            """,
            [run_id, name, diagram_type, content, _now()],
        )
        self._c.commit()

    # ------------------------------------------------------------------
    # Read helpers
    # ------------------------------------------------------------------

    def get_all_symbols(self, run_id: str) -> list[dict[str, Any]]:
        if "scan_symbols" not in self._table_names():
            return []
        return list(self._c.execute(
            "SELECT * FROM scan_symbols WHERE run_id = ?", [run_id]
        ).fetchall())

    def get_all_relationships(self, run_id: str) -> list[dict[str, Any]]:
        if "scan_relationships" not in self._table_names():
            return []
        rows = self._c.execute(
            'SELECT from_, "to", kind, file, confidence, evidence_tag'
            " FROM scan_relationships WHERE run_id = ?",
            [run_id],
        ).fetchall()
        return [
            {
                "from_": r[0],
                "to": r[1],
                "kind": r[2],
                "file": r[3],
                "confidence": r[4],
                "evidence_tag": r[5],
            }
            for r in rows
        ]

    def upsert_rationale_notes(self, run_id: str, notes: list[dict[str, Any]]) -> None:
        if not notes:
            return
        self._c.execute(
            """
            CREATE TABLE IF NOT EXISTS scan_rationale (
                run_id TEXT,
                tag TEXT,
                content TEXT,
                file TEXT,
                line INTEGER,
                PRIMARY KEY(run_id, file, line)
            )
            """
        )
        rows = [
            (run_id, n.get("tag", ""), n.get("content", ""), n.get("file", ""), n.get("line", 0))
            for n in notes
        ]
        self._c.executemany(
            """
            INSERT OR REPLACE INTO scan_rationale(run_id, tag, content, file, line)
            VALUES(?, ?, ?, ?, ?)
            """,
            rows,
        )
        self._c.commit()

    def get_rationale_notes(self, run_id: str) -> list[dict[str, Any]]:
        if "scan_rationale" not in self._table_names():
            return []
        rows = self._c.execute(
            "SELECT tag, content, file, line FROM scan_rationale WHERE run_id = ?", [run_id]
        ).fetchall()
        return [{"tag": r[0], "content": r[1], "file": r[2], "line": r[3]} for r in rows]

    def get_relationships_for_run(self, run_id: str) -> list[dict]:
        """Return all scan_relationships rows for *run_id* as plain dicts."""
        if "scan_relationships" not in self._table_names():
            return []
        rows = self._c.execute(
            'SELECT from_, "to", kind FROM scan_relationships WHERE run_id = ?',
            [run_id],
        ).fetchall()
        return [{"from_": r[0], "to": r[1], "kind": r[2]} for r in rows]

    def get_god_nodes(self, run_id: str, top_n: int = 10) -> list[tuple[str, int]]:
        """Return top_n god nodes (symbol name, degree) for the given run."""
        from rekipedia.analysis.graph_analysis import compute_god_nodes

        rels = self.get_relationships_for_run(run_id)

        # Create lightweight proxy objects compatible with compute_god_nodes
        class _Rel:
            __slots__ = ("from_", "to")

            def __init__(self, d: dict) -> None:
                self.from_ = d["from_"]
                self.to = d["to"]

        return compute_god_nodes([_Rel(r) for r in rels], top_n=top_n)

    def get_pages(self, run_id: str) -> list[dict[str, Any]]:
        if "scan_wiki_pages" not in self._table_names():
            return []
        return list(self._c.execute(
            "SELECT * FROM scan_wiki_pages WHERE run_id = ?", [run_id]
        ).fetchall())

    # ------------------------------------------------------------------
    # Incremental update helpers (Phase 3)
    # ------------------------------------------------------------------

    def get_latest_run_id(self, repo_path: str) -> str | None:
        """Return the id of the last successful scan_run for *repo_path*, or None."""
        if "scan_runs" not in self._table_names():
            return None
        row = self._c.execute(
            "SELECT id FROM scan_runs WHERE repo_path = ? AND status = 'success'"
            " ORDER BY started_at DESC LIMIT 1",
            [repo_path],
        ).fetchone()
        return row[0] if row else None

    def get_files_for_run(self, run_id: str) -> list[dict[str, Any]]:
        """Return all scan_files rows for *run_id* as plain dicts."""
        if "scan_files" not in self._table_names():
            return []
        rows = self._c.execute(
            "SELECT path, sha256, size_bytes, language FROM scan_files WHERE run_id = ?",
            [run_id],
        ).fetchall()
        return [{"path": r[0], "sha256": r[1], "size_bytes": r[2], "language": r[3]} for r in rows]

    def copy_unchanged_symbols(
        self, from_run_id: str, to_run_id: str, exclude_paths: set[str]
    ) -> int:
        """Copy symbols from *from_run_id* to *to_run_id*, skipping *exclude_paths*.

        Returns the number of rows copied.
        """
        if "scan_symbols" not in self._table_names():
            return 0
        all_rows = self._c.execute(
            "SELECT name, kind, file, line_start, line_end, signature, docstring"
            " FROM scan_symbols WHERE run_id = ?",
            [from_run_id],
        ).fetchall()
        to_copy = [r for r in all_rows if r[2] not in exclude_paths]
        if to_copy:
            self._c.executemany(
                """
                INSERT OR REPLACE INTO scan_symbols(run_id, name, kind, file, line_start, line_end, signature, docstring)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [(to_run_id, r[0], r[1], r[2], r[3], r[4], r[5], r[6]) for r in to_copy],
            )
            self._c.commit()
        return len(to_copy)

    def copy_unchanged_relationships(
        self, from_run_id: str, to_run_id: str, exclude_paths: set[str]
    ) -> int:
        """Copy relationships from *from_run_id* to *to_run_id*, skipping *exclude_paths*."""
        if "scan_relationships" not in self._table_names():
            return 0
        all_rows = self._c.execute(
            'SELECT "from_", "to", "kind", "file" FROM scan_relationships WHERE run_id = ?',
            [from_run_id],
        ).fetchall()
        to_copy = [r for r in all_rows if r[3] not in exclude_paths]
        if to_copy:
            self._c.executemany(
                """
                INSERT OR REPLACE INTO scan_relationships(run_id, from_, "to", kind, file)
                VALUES(?, ?, ?, ?, ?)
                """,
                [(to_run_id, r[0], r[1], r[2], r[3]) for r in to_copy],
            )
            self._c.commit()
        return len(to_copy)


    # ── Q&A history ───────────────────────────────────────────────────

    def save_qa(self, repo_path: str, question: str, answer: str, model: str = "") -> int:
        """Persist a Q&A pair. Returns the new row id."""
        cur = self._c.execute(
            "INSERT INTO qa_history (repo_path, question, answer, model) VALUES (?, ?, ?, ?)",
            (repo_path, question, answer, model),
        )
        self._c.commit()
        return cur.lastrowid

    def get_qa_history(self, repo_path: str, limit: int = 50) -> list[dict]:
        """Return recent Q&A pairs for a repo, newest first."""
        rows = self._c.execute(
            "SELECT id, question, answer, model, created_at FROM qa_history "
            "WHERE repo_path = ? ORDER BY id DESC LIMIT ?",
            (repo_path, limit),
        ).fetchall()
        return [
            {"id": r[0], "question": r[1], "answer": r[2], "model": r[3], "created_at": r[4]}
            for r in rows
        ]


# ── helpers ──────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
