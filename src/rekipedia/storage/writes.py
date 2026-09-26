"""Write (upsert) queries for rekipedia storage."""
from __future__ import annotations

import contextlib
from typing import Any

from rekipedia.storage._helpers import _now


class WritesMixin:
    """Mixin providing all write/upsert operations."""

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
        """Batch upsert files with a single commit."""
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
        """Batch upsert wiki pages with a single commit."""
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

    def upsert_wiki_revision(self, slug: str, run_id: str, title: str, content: str) -> None:
        """Save a wiki page revision to the database."""
        now = _now()
        try:
            self._c.execute(
                """
                INSERT INTO wiki_revisions (slug, run_id, title, content, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(slug) DO UPDATE SET
                    run_id=excluded.run_id,
                    title=excluded.title,
                    content=excluded.content,
                    updated_at=excluded.updated_at
                """,
                (slug, run_id, title, content, now)
            )
            self._conn.commit()
        except Exception as exc:
            import logging
            logging.getLogger("rekipedia.storage").warning(f"Failed to upsert wiki revision for {slug}: {exc}")

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

    def upsert_hyperedges(self, run_id: str, hyperedges: list[Any]) -> None:
        """Upsert hyperedges representing N-ary relationships (design patterns, shared concepts)."""
        if not hyperedges:
            return
        self._c.execute(
            """
            CREATE TABLE IF NOT EXISTS scan_hyperedges (
                run_id TEXT,
                id TEXT,
                concept TEXT NOT NULL,
                description TEXT,
                confidence TEXT DEFAULT 'INFERRED',
                pattern_type TEXT,
                PRIMARY KEY(run_id, id)
            )
            """
        )
        self._c.execute(
            """
            CREATE TABLE IF NOT EXISTS scan_hyperedge_members (
                run_id TEXT,
                hyperedge_id TEXT,
                symbol_id TEXT NOT NULL,
                PRIMARY KEY(run_id, hyperedge_id, symbol_id)
            )
            """
        )
        edge_rows = []
        member_rows = []
        for h in hyperedges:
            if hasattr(h, "model_dump"):
                d = h.model_dump()
            elif hasattr(h, "to_dict"):
                d = h.to_dict()
            elif isinstance(h, dict):
                d = h
            else:
                d = {"id": getattr(h, "id", ""), "concept": getattr(h, "concept", ""), "nodes": getattr(h, "nodes", [])}
            edge_id = str(d.get("id") or f"hyperedge_{len(edge_rows)}")
            concept = str(d.get("concept", ""))
            desc = str(d.get("description", ""))
            confidence = str(d.get("confidence", "INFERRED"))
            pattern_type = str(d.get("pattern_type") or "design_pattern")
            edge_rows.append((run_id, edge_id, concept, desc, confidence, pattern_type))
            for sym_id in d.get("nodes", []):
                member_rows.append((run_id, edge_id, str(sym_id)))

        self._c.executemany(
            """
            INSERT OR REPLACE INTO scan_hyperedges(run_id, id, concept, description, confidence, pattern_type)
            VALUES(?, ?, ?, ?, ?, ?)
            """,
            edge_rows,
        )
        if member_rows:
            self._c.executemany(
                """
                INSERT OR REPLACE INTO scan_hyperedge_members(run_id, hyperedge_id, symbol_id)
                VALUES(?, ?, ?)
                """,
                member_rows,
            )
        self._c.commit()

    def upsert_document_chunks(self, run_id: str, chunks: list[dict]) -> None:
        """Insert document chunks for a run."""
        import json as _json
        self._c.executemany(
            """
            INSERT INTO document_chunks (run_id, doc_path, page_number, text, bbox_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (
                    run_id,
                    c["doc_path"],
                    c.get("page_number", 1),
                    c["text"],
                    _json.dumps(c.get("bounding_box") or {}) if c.get("bounding_box") else None,
                )
                for c in chunks
            ],
        )
        self._c.commit()

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

    def save_qa(self, repo_path: str, question: str, answer: str, model: str = "") -> int:
        """Persist a Q&A pair. Returns the new row id."""
        cur = self._c.execute(
            "INSERT INTO qa_history (repo_path, question, answer, model) VALUES (?, ?, ?, ?)",
            (repo_path, question, answer, model),
        )
        self._c.commit()
        return cur.lastrowid

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

    def delete_note(self, note_id: str) -> bool:
        """Delete a note by id. Returns True if deleted."""
        cur = self._c.execute(
            "DELETE FROM tech_lead_notes WHERE id = ?", (note_id,)
        )
        self._c.commit()
        return cur.rowcount > 0

    def upsert_rag_chunks(self, run_id: str, chunks: list[dict]) -> None:
        """Persist RAG chunk provenance records for *run_id*."""
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

    def copy_unchanged_symbols(
        self, from_run_id: str, to_run_id: str, exclude_paths: set[str]
    ) -> int:
        """Copy symbols from *from_run_id* to *to_run_id*, skipping *exclude_paths*."""
        if "scan_symbols" not in self._table_names():
            return 0
        try:
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

    def carry_forward_rag_chunks(
        self,
        from_run_id: int | str,
        to_run_id: int | str,
        file_paths: list[str],
    ) -> int:
        """Copy RAG chunk provenance from *from_run_id* to *to_run_id* for *file_paths*."""
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

    def save_qa_symbol_mentions(self, qa_id: int, symbol_names: list[str]) -> None:
        """Save symbol mentions for a given Q&A ID."""
        try:
            for name in symbol_names:
                self._c.execute(
                    "INSERT OR IGNORE INTO qa_symbol_mentions (qa_id, symbol_name) VALUES (?, ?)",
                    (qa_id, name),
                )
            self._c.commit()
        except Exception as exc:
            with contextlib.suppress(Exception):
                self._c.execute("ROLLBACK")
            raise RuntimeError(f"save_qa_symbol_mentions failed: {exc}") from exc
