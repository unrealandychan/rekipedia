"""Persistence layer for rekipedia.

Uses Turso (pyturso) when available — MVCC engine, cross-platform pre-built
wheels for macOS and Linux x86_64.  Falls back transparently to the stdlib
``sqlite3`` module on platforms where a pyturso wheel is not yet available
(e.g. Linux aarch64, Windows).  The public API of SqliteStore is identical
in both modes.
"""
from __future__ import annotations

import contextlib
import functools  # noqa: F401 — used for future lru_cache if needed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    import turso as _db

    def _connect(path: str) -> Any:
        conn = _db.connect(path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=-64000")
        conn.execute("PRAGMA temp_store=MEMORY")
        return conn

    _BACKEND = "turso"
except ImportError:  # pragma: no cover — only hit on platforms without a wheel
    import sqlite3 as _db_sqlite3  # type: ignore[assignment]

    def _connect(path: str) -> Any:  # type: ignore[misc]
        conn = _db_sqlite3.connect(path, isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=-64000")
        conn.execute("PRAGMA temp_store=MEMORY")
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

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._conn: _Conn | None = None
        self._known_tables: set | None = None

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

    def __enter__(self) -> SqliteStore:
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
        if self._known_tables is not None:
            return self._known_tables
        rows = self._c.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        self._known_tables = {r[0] for r in rows}
        return self._known_tables

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
        # Invalidate table name cache after migrations
        self._known_tables = None

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

    def upsert_files_batch(self, run_id: str, files: list) -> None:
        """Batch upsert files with a single commit. Each item needs .path, .sha256, .size_bytes, .language."""
        if not files:
            return
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
        rows = [(run_id, f.path, f.sha256, f.size_bytes, f.language) for f in files]
        try:
            self._c.executemany(
                """
                INSERT INTO scan_files(run_id, path, sha256, size_bytes, language) VALUES(?, ?, ?, ?, ?)
                ON CONFLICT(run_id, path) DO UPDATE SET
                    sha256=excluded.sha256,
                    size_bytes=excluded.size_bytes,
                    language=excluded.language
                """,
                rows,
            )
            self._c.commit()
        except Exception as exc:
            with contextlib.suppress(Exception):
                self._c.execute("ROLLBACK")
            raise RuntimeError(f"upsert_files_batch failed: {exc}") from exc

    def upsert_pages_batch(self, run_id: str, pages: dict) -> None:
        """Batch upsert wiki pages with a single commit. pages is {slug: (title, content)} or {slug: content}."""
        if not pages:
            return
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
        now = _now()
        rows = []
        for slug, value in pages.items():
            if isinstance(value, tuple):
                title, content = value
            else:
                title = slug.replace("-", " ").title()
                content = value
            rows.append((run_id, slug, title, content, 0, now))
        try:
            self._c.executemany(
                """
                INSERT INTO scan_wiki_pages(run_id, slug, title, content, pinned, updated_at)
                VALUES(?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, slug) DO UPDATE SET
                    title=excluded.title,
                    content=excluded.content,
                    pinned=excluded.pinned,
                    updated_at=excluded.updated_at
                """,
                rows,
            )
            self._c.commit()
        except Exception as exc:
            with contextlib.suppress(Exception):
                self._c.execute("ROLLBACK")
            raise RuntimeError(f"upsert_pages_batch failed: {exc}") from exc

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
        try:
            # Get column names dynamically
            col_rows = self._c.execute("PRAGMA table_info(scan_symbols)").fetchall()
            all_cols = [r[1] for r in col_rows]
            non_run_cols = [c for c in all_cols if c != "run_id"]
            cols_str = ", ".join(non_run_cols)
            if exclude_paths:
                placeholders = ",".join("?" * len(exclude_paths))
                sql = (
                    f"INSERT OR REPLACE INTO scan_symbols (run_id, {cols_str})"
                    f" SELECT ?, {cols_str}"
                    f" FROM scan_symbols WHERE run_id = ? AND file NOT IN ({placeholders})"
                )
                params = [to_run_id, from_run_id, *exclude_paths]
            else:
                sql = (
                    f"INSERT OR REPLACE INTO scan_symbols (run_id, {cols_str})"
                    f" SELECT ?, {cols_str}"
                    f" FROM scan_symbols WHERE run_id = ?"
                )
                params = [to_run_id, from_run_id]
            self._c.execute(sql, params)
            self._c.commit()
            # turso may return incorrect rowcount for INSERT SELECT; query actual count
            actual = self._c.execute(
                "SELECT COUNT(*) FROM scan_symbols WHERE run_id = ?", [to_run_id]
            ).fetchone()
            return actual[0] if actual else 0
        except Exception as exc:
            with contextlib.suppress(Exception):
                self._c.execute("ROLLBACK")
            raise RuntimeError(f"copy_unchanged_symbols failed: {exc}") from exc

    def copy_unchanged_relationships(
        self, from_run_id: str, to_run_id: str, exclude_paths: set[str]
    ) -> int:
        """Copy relationships from *from_run_id* to *to_run_id*, skipping *exclude_paths*."""
        if "scan_relationships" not in self._table_names():
            return 0
        try:
            col_rows = self._c.execute("PRAGMA table_info(scan_relationships)").fetchall()
            all_cols = [r[1] for r in col_rows]
            non_run_cols = [c for c in all_cols if c != "run_id"]
            # Quote column names for safety (e.g., "to")
            quoted_non_run = ", ".join(f'"{c}"' for c in non_run_cols)
            if exclude_paths:
                placeholders = ",".join("?" * len(exclude_paths))
                sql = (
                    f'INSERT OR REPLACE INTO scan_relationships (run_id, {quoted_non_run})'
                    f' SELECT ?, {quoted_non_run}'
                    f' FROM scan_relationships WHERE run_id = ? AND file NOT IN ({placeholders})'
                )
                params = [to_run_id, from_run_id, *exclude_paths]
            else:
                sql = (
                    f'INSERT OR REPLACE INTO scan_relationships (run_id, {quoted_non_run})'
                    f' SELECT ?, {quoted_non_run}'
                    f' FROM scan_relationships WHERE run_id = ?'
                )
                params = [to_run_id, from_run_id]
            self._c.execute(sql, params)
            self._c.commit()
            actual = self._c.execute(
                "SELECT COUNT(*) FROM scan_relationships WHERE run_id = ?", [to_run_id]
            ).fetchone()
            return actual[0] if actual else 0
        except Exception as exc:
            with contextlib.suppress(Exception):
                self._c.execute("ROLLBACK")
            raise RuntimeError(f"copy_unchanged_relationships failed: {exc}") from exc

    def upsert_page_sources(self, run_id: str, page_slug: str, file_paths: list[str]) -> None:
        """Record which source files contributed to *page_slug* in *run_id*."""
        if not file_paths:
            self._c.commit()
            return
        rows = [(run_id, page_slug, fp) for fp in file_paths]
        try:
            self._c.executemany(
                "INSERT OR REPLACE INTO page_sources (run_id, page_slug, file_path) VALUES (?, ?, ?)",
                rows,
            )
            self._c.commit()
        except Exception as exc:
            with contextlib.suppress(Exception):
                self._c.execute("ROLLBACK")
            raise RuntimeError(f"upsert_page_sources failed: {exc}") from exc

    def get_pages_for_files(self, run_id: str, file_paths: list[str]) -> set[str]:
        """Return set of page slugs whose sources include any of *file_paths* in *run_id*."""
        if not file_paths:
            return set()
        if "page_sources" not in self._table_names():
            return set()
        placeholders = ",".join("?" * len(file_paths))
        rows = self._c.execute(
            f"SELECT DISTINCT page_slug FROM page_sources WHERE run_id = ? AND file_path IN ({placeholders})",
            [run_id, *file_paths],
        ).fetchall()
        return {r[0] for r in rows}

    def get_all_page_slugs(self, run_id: str) -> list[str]:
        """Return all page slugs stored for *run_id*."""
        if "scan_wiki_pages" not in self._table_names():
            return []
        rows = self._c.execute(
            "SELECT slug FROM scan_wiki_pages WHERE run_id = ?",
            [run_id],
        ).fetchall()
        return [r[0] for r in rows]

    def carry_forward_page_sources(self, from_run_id: str, to_run_id: str, page_slugs: list[str]) -> None:
        """Copy page_sources entries from *from_run_id* to *to_run_id* for *page_slugs*."""
        if not page_slugs:
            return
        if "page_sources" not in self._table_names():
            return
        placeholders = ",".join("?" * len(page_slugs))
        rows = self._c.execute(
            f"SELECT page_slug, file_path FROM page_sources WHERE run_id = ? AND page_slug IN ({placeholders})",
            [from_run_id, *page_slugs],
        ).fetchall()
        for r in rows:
            self._c.execute(
                "INSERT OR REPLACE INTO page_sources (run_id, page_slug, file_path) VALUES (?, ?, ?)",
                (to_run_id, r[0], r[1]),
            )
        self._c.commit()

    def copy_pages(self, from_run_id: str, to_run_id: str, page_slugs: list[str]) -> None:
        """Copy wiki pages from *from_run_id* to *to_run_id* for *page_slugs*."""
        if not page_slugs:
            return
        if "scan_wiki_pages" not in self._table_names():
            return
        placeholders = ",".join("?" * len(page_slugs))
        rows = self._c.execute(
            f"SELECT slug, title, content, pinned FROM scan_wiki_pages WHERE run_id = ? AND slug IN ({placeholders})",
            [from_run_id, *page_slugs],
        ).fetchall()
        for r in rows:
            self._c.execute(
                """
                INSERT OR REPLACE INTO scan_wiki_pages(run_id, slug, title, content, pinned, updated_at)
                VALUES(?, ?, ?, ?, ?, ?)
                """,
                [to_run_id, r[0], r[1], r[2], r[3], _now()],
            )
        self._c.commit()

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

    # ── Tech Lead Notes ───────────────────────────────────────────────

    def upsert_note(
        self,
        content: str,
        tags: str = "",
        source: str = "manual",
        note_id: str | None = None,
    ) -> str:
        """Insert or update a tech lead note. Returns the note id."""
        import uuid as _uuid
        now = _now()
        if note_id is None:
            note_id = str(_uuid.uuid4())
        self._c.execute(
            """
            INSERT INTO tech_lead_notes (id, content, tags, source, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                content=excluded.content,
                tags=excluded.tags,
                source=excluded.source,
                updated_at=excluded.updated_at
            """,
            (note_id, content, tags, source, now, now),
        )
        self._c.commit()
        return note_id

    def list_notes(self, tags: str | None = None) -> list[dict]:
        """Return all notes, optionally filtered by a tag."""
        rows = self._c.execute(
            "SELECT id, content, tags, source, created_at, updated_at FROM tech_lead_notes "
            "ORDER BY created_at DESC"
        ).fetchall()
        result = [
            {
                "id": r[0],
                "content": r[1],
                "tags": r[2],
                "source": r[3],
                "created_at": r[4],
                "updated_at": r[5],
            }
            for r in rows
        ]
        if tags:
            filter_tag = tags.strip().lower()
            result = [
                n for n in result
                if any(t.strip().lower() == filter_tag for t in n["tags"].split(",") if t.strip())
            ]
        return result

    # Alias for backwards compat / spec name
    def get_notes(self, tags: str | None = None) -> list[dict]:
        return self.list_notes(tags=tags)

    def delete_note(self, note_id: str) -> bool:
        """Delete a note by id. Returns True if deleted."""
        cur = self._c.execute(
            "DELETE FROM tech_lead_notes WHERE id = ?", (note_id,)
        )
        self._c.commit()
        return cur.rowcount > 0

    def get_note(self, note_id: str) -> dict | None:
        """Fetch a single note by id."""
        row = self._c.execute(
            "SELECT id, content, tags, source, created_at, updated_at FROM tech_lead_notes WHERE id = ?",
            (note_id,),
        ).fetchone()
        if row is None:
            return None
        return {"id": row[0], "content": row[1], "tags": row[2], "source": row[3],
                "created_at": row[4], "updated_at": row[5]}

    # ------------------------------------------------------------------
    # RAG chunk provenance (issue #75)
    # ------------------------------------------------------------------

    def upsert_rag_chunks(self, run_id: str, chunks: list[dict]) -> None:
        """Persist RAG chunk provenance records for *run_id*.

        Each dict must have: file_path, chunk_idx, start_line, end_line,
        start_char, end_char, text_hash, is_code, is_implementation.
        """
        for chunk in chunks:
            self._c.execute(
                """
                INSERT OR REPLACE INTO rag_chunks
                    (run_id, file_path, chunk_idx, start_line, end_line,
                     start_char, end_char, text_hash, is_code, is_implementation)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    chunk["file_path"],
                    chunk["chunk_idx"],
                    chunk["start_line"],
                    chunk["end_line"],
                    chunk["start_char"],
                    chunk["end_char"],
                    chunk["text_hash"],
                    int(chunk.get("is_code", True)),
                    int(chunk.get("is_implementation", True)),
                ),
            )
        self._c.commit()

    def get_rag_chunks_by_file(self, run_id: str, file_path: str) -> list[dict]:
        """Return all RAG chunk provenance records for *file_path* in *run_id*."""
        rows = self._c.execute(
            """
            SELECT file_path, chunk_idx, start_line, end_line,
                   start_char, end_char, text_hash, is_code, is_implementation
            FROM rag_chunks
            WHERE run_id = ? AND file_path = ?
            ORDER BY chunk_idx
            """,
            (run_id, file_path),
        ).fetchall()
        return [
            {
                "file_path": r[0],
                "chunk_idx": r[1],
                "start_line": r[2],
                "end_line": r[3],
                "start_char": r[4],
                "end_char": r[5],
                "text_hash": r[6],
                "is_code": bool(r[7]),
                "is_implementation": bool(r[8]),
            }
            for r in rows
        ]

    def carry_forward_rag_chunks(
        self,
        from_run_id: int | str,
        to_run_id: int | str,
        file_paths: list[str],
    ) -> int:
        """Copy RAG chunk provenance from *from_run_id* to *to_run_id* for *file_paths*.

        Used by incremental embed: unchanged files keep their provenance records.
        Returns number of rows copied.
        """
        if not file_paths:
            return 0
        placeholders = ",".join("?" * len(file_paths))
        rows = self._c.execute(
            f"""
            SELECT file_path, chunk_idx, start_line, end_line,
                   start_char, end_char, text_hash, is_code, is_implementation
            FROM rag_chunks
            WHERE run_id = ? AND file_path IN ({placeholders})
            """,
            [from_run_id, *file_paths],
        ).fetchall()
        for r in rows:
            self._c.execute(
                """
                INSERT OR REPLACE INTO rag_chunks
                    (run_id, file_path, chunk_idx, start_line, end_line,
                     start_char, end_char, text_hash, is_code, is_implementation)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (to_run_id, r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8]),
            )
        self._c.commit()
        return len(rows)

    def get_all_rag_chunks(self, run_id: str) -> list[dict]:
        """Return all RAG chunk provenance records for *run_id*."""
        rows = self._c.execute(
            """
            SELECT file_path, chunk_idx, start_line, end_line,
                   start_char, end_char, text_hash, is_code, is_implementation
            FROM rag_chunks
            WHERE run_id = ?
            ORDER BY file_path, chunk_idx
            """,
            (run_id,),
        ).fetchall()
        return [
            {
                "file_path": r[0],
                "chunk_idx": r[1],
                "start_line": r[2],
                "end_line": r[3],
                "start_char": r[4],
                "end_char": r[5],
                "text_hash": r[6],
                "is_code": bool(r[7]),
                "is_implementation": bool(r[8]),
            }
            for r in rows
        ]


# ── helpers ──────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(UTC).isoformat()
