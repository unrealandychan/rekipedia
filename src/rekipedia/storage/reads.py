"""Read queries for rekipedia storage."""
from __future__ import annotations

from typing import Any


class ReadsMixin:
    """Mixin providing all read/query operations."""

    def get_all_symbols(self, run_id: str) -> list[dict[str, Any]]:
        if "scan_symbols" not in self._table_names():
            return []
        rows = self._c.execute(
            "SELECT name, kind, file, line_start, line_end, signature, docstring"
            " FROM scan_symbols WHERE run_id = ?",
            [run_id],
        ).fetchall()
        return [
            {
                "name": r[0],
                "kind": r[1],
                "file": r[2],
                "line_start": r[3],
                "line_end": r[4],
                "signature": r[5],
                "docstring": r[6],
            }
            for r in rows
        ]

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

    def get_rationale_notes(self, run_id: str) -> list[dict[str, Any]]:
        if "scan_rationale" not in self._table_names():
            return []
        rows = self._c.execute(
            "SELECT tag, content, file, line FROM scan_rationale WHERE run_id = ?", [run_id]
        ).fetchall()
        return [{"tag": r[0], "content": r[1], "file": r[2], "line": r[3]} for r in rows]

    def get_hyperedges(self, run_id: str) -> list[dict[str, Any]]:
        """Return all hyperedges and their member symbols for *run_id*."""
        if "scan_hyperedges" not in self._table_names():
            return []
        rows = self._c.execute(
            "SELECT id, concept, description, confidence, pattern_type FROM scan_hyperedges WHERE run_id = ?",
            [run_id],
        ).fetchall()
        if not rows:
            return []

        # Fetch members
        members_map: dict[str, list[str]] = {}
        if "scan_hyperedge_members" in self._table_names():
            member_rows = self._c.execute(
                "SELECT hyperedge_id, symbol_id FROM scan_hyperedge_members WHERE run_id = ?",
                [run_id],
            ).fetchall()
            for hid, sym in member_rows:
                members_map.setdefault(hid, []).append(sym)

        result = []
        for r in rows:
            hid = r[0]
            result.append({
                "id": hid,
                "concept": r[1],
                "description": r[2] or "",
                "confidence": r[3] or "INFERRED",
                "pattern_type": r[4] or "design_pattern",
                "nodes": members_map.get(hid, []),
            })
        return result

    def get_relationships_for_run(self, run_id: str) -> list[dict]:
        """Return all scan_relationships rows for *run_id* as plain dicts."""
        if "scan_relationships" not in self._table_names():
            return []
        rows = self._c.execute(
            'SELECT from_, "to", kind FROM scan_relationships WHERE run_id = ?',
            [run_id],
        ).fetchall()
        return [{"from_": r[0], "to": r[1], "kind": r[2]} for r in rows]

    def get_pages(self, run_id: str) -> list[dict[str, Any]]:
        if "scan_wiki_pages" not in self._table_names():
            return []
        return list(self._c.execute(
            "SELECT * FROM scan_wiki_pages WHERE run_id = ?", [run_id]
        ).fetchall())

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

    def get_two_latest_run_ids(self, repo_path: str) -> tuple[str | None, str | None]:
        """Return (latest_run_id, previous_run_id) for *repo_path*.

        Returns (latest, None) when only one run exists, (None, None) when none.

        Args:
            repo_path: Absolute path of the scanned repository.

        Returns:
            Tuple of (latest_run_id, previous_run_id).  Either may be None.
        """
        if "scan_runs" not in self._table_names():
            return None, None
        rows = self._c.execute(
            "SELECT id FROM scan_runs WHERE repo_path = ? AND status = 'success'"
            " ORDER BY started_at DESC LIMIT 2",
            [repo_path],
        ).fetchall()
        if not rows:
            return None, None
        latest = rows[0][0]
        previous = rows[1][0] if len(rows) > 1 else None
        return latest, previous

    def latest_run_id(self) -> str | None:
        """Return the id of the most recent successful scan_run across all repos."""
        if "scan_runs" not in self._table_names():
            return None
        row = self._c.execute(
            "SELECT id FROM scan_runs WHERE status = 'success'"
            " ORDER BY started_at DESC LIMIT 1",
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

    def get_notes(self, tags: str | None = None) -> list[dict]:
        return self.list_notes(tags=tags)

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

    def get_document_chunks(self, run_id: str, doc_path: str | None = None) -> list[dict]:
        """Return document chunks for a run, optionally filtered by doc_path."""
        import json as _json
        if doc_path:
            rows = self._c.execute(
                "SELECT doc_path, page_number, text, bbox_json FROM document_chunks "
                "WHERE run_id = ? AND doc_path = ? ORDER BY page_number",
                (run_id, doc_path),
            ).fetchall()
        else:
            rows = self._c.execute(
                "SELECT doc_path, page_number, text, bbox_json FROM document_chunks "
                "WHERE run_id = ? ORDER BY doc_path, page_number",
                (run_id,),
            ).fetchall()
        return [
            {
                "doc_path": r[0],
                "page_number": r[1],
                "text": r[2],
                "bounding_box": _json.loads(r[3]) if r[3] else {},
            }
            for r in rows
        ]

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

    def get_frequent_symbols(self, repo_path: str, limit: int = 20) -> list[str]:
        """Return the most frequently asked symbol names for *repo_path*."""
        if "qa_symbol_mentions" not in self._table_names():
            return []
        rows = self._c.execute(
            """
            SELECT symbol_name, COUNT(*) as count
            FROM qa_symbol_mentions m
            JOIN qa_history h ON m.qa_id = h.id
            WHERE h.repo_path = ?
            GROUP BY symbol_name
            ORDER BY count DESC
            LIMIT ?
            """,
            [repo_path, limit],
        ).fetchall()
        return [r[0] for r in rows]
