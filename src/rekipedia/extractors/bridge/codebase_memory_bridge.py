"""Bridge and adapter for delegating ultra-large codebase indexing to codebase-memory-mcp."""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
from pathlib import Path
from typing import Any, ClassVar

from rekipedia.models.contracts import AnalysisResult, Relationship, Symbol


class CodebaseMemoryAdapter:
    """Adapter that converts codebase-memory-mcp symbol and relationship graphs into Rekipedia format."""

    KIND_MAP: ClassVar[dict[str, str]] = {
        "func": "function",
        "method": "function",
        "fn": "function",
        "cls": "class",
        "struct": "class",
        "interface": "interface",
        "trait": "interface",
        "type": "type",
        "enum": "type",
        "var": "variable",
        "const": "constant",
        "mod": "module",
        "module": "module",
        "endpoint": "endpoint",
    }

    REL_KIND_MAP: ClassVar[dict[str, str]] = {
        "call": "calls",
        "calls": "calls",
        "invokes": "calls",
        "import": "import",
        "imports": "import",
        "require": "import",
        "inherit": "inherits",
        "inherits": "inherits",
        "extends": "inherits",
        "implements": "inherits",
        "uses": "calls",
    }

    @classmethod
    def normalize_symbol(cls, raw: dict[str, Any]) -> Symbol:
        """Map raw codebase-memory symbol dict to Rekipedia Symbol contract."""
        name = raw.get("name") or raw.get("symbol") or raw.get("id") or "anonymous"
        raw_kind = (raw.get("kind") or raw.get("symbol_type") or "function").lower()
        kind = cls.KIND_MAP.get(raw_kind, raw_kind)
        file_path = raw.get("file") or raw.get("file_path") or raw.get("path") or ""
        line_start = int(raw.get("line_start") or raw.get("start_line") or raw.get("line") or 1)
        line_end = int(raw.get("line_end") or raw.get("end_line") or line_start)
        sig = raw.get("signature") or raw.get("sig")

        return Symbol(
            name=name,
            kind=kind,
            file=file_path,
            line_start=line_start,
            line_end=line_end,
            signature=sig,
        )

    @classmethod
    def normalize_relationship(cls, raw: dict[str, Any]) -> Relationship:
        """Map raw codebase-memory relationship dict to Rekipedia Relationship contract."""
        frm = raw.get("from") or raw.get("from_") or raw.get("source") or raw.get("from_symbol_id") or ""
        to = raw.get("to") or raw.get("target") or raw.get("to_symbol_id") or ""
        raw_kind = (raw.get("kind") or raw.get("relationship_type") or "calls").lower()
        kind = cls.REL_KIND_MAP.get(raw_kind, "calls")
        file_path = raw.get("file") or raw.get("file_path") or None
        conf = float(raw.get("confidence") or raw.get("confidence_score") or 1.0)
        ev_tag = raw.get("evidence_tag") or raw.get("confidence_level") or "EXTRACTED"
        if ev_tag not in ("EXTRACTED", "INFERRED", "AMBIGUOUS"):
            ev_tag = "EXTRACTED"

        return Relationship.model_validate({
            "from": frm,
            "to": to,
            "kind": kind,
            "file": file_path,
            "confidence": conf,
            "evidence_tag": ev_tag,
        })

    @classmethod
    def from_dict(cls, data: dict[str, Any], shard_id: str = "codebase-memory") -> AnalysisResult:
        """Construct AnalysisResult from loaded codebase-memory JSON dictionary."""
        raw_symbols = data.get("symbols") or data.get("nodes") or []
        raw_relationships = data.get("relationships") or data.get("edges") or []

        symbols = [cls.normalize_symbol(s) for s in raw_symbols if s]
        relationships = [cls.normalize_relationship(r) for r in raw_relationships if r]

        files_seen = list({s.file for s in symbols if s.file} | {r.file for r in relationships if r.file})
        entry_points = data.get("entry_points") or [f for f in files_seen if "main" in f or "index" in f or "app" in f]

        return AnalysisResult(
            shard_id=shard_id,
            files_seen=files_seen,
            entry_points=entry_points,
            symbols=symbols,
            relationships=relationships,
        )

    @classmethod
    def from_sqlite(cls, db_path: Path | str, shard_id: str = "codebase-memory") -> AnalysisResult:
        """Load symbols and relationships directly from a codebase-memory SQLite database."""
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()

        symbols: list[Symbol] = []
        relationships: list[Relationship] = []

        try:
            # Try loading symbols
            cursor.execute("SELECT name, kind, file, line_start, line_end, signature FROM symbols")
            for row in cursor.fetchall():
                symbols.append(
                    Symbol(
                        name=row[0],
                        kind=cls.KIND_MAP.get((row[1] or "").lower(), row[1] or "function"),
                        file=row[2] or "",
                        line_start=row[3] or 1,
                        line_end=row[4] or 1,
                        signature=row[5],
                    )
                )
        except sqlite3.OperationalError:
            # Fallback to alternative column names
            try:
                cursor.execute("SELECT id, symbol_type, file_path FROM symbols")
                for row in cursor.fetchall():
                    symbols.append(
                        Symbol(
                            name=row[0],
                            kind=cls.KIND_MAP.get((row[1] or "").lower(), "function"),
                            file=row[2] or "",
                            line_start=1,
                            line_end=1,
                        )
                    )
            except Exception:
                pass

        try:
            # Try loading relationships
            cursor.execute("SELECT from_, to_, kind, file, confidence FROM relationships")
            for row in cursor.fetchall():
                relationships.append(
                    Relationship.model_validate({
                        "from": row[0],
                        "to": row[1],
                        "kind": cls.REL_KIND_MAP.get((row[2] or "").lower(), "calls"),
                        "file": row[3],
                        "confidence": float(row[4] or 1.0),
                        "evidence_tag": "EXTRACTED",
                    })
                )
        except sqlite3.OperationalError:
            try:
                cursor.execute("SELECT from_symbol_id, to_symbol_id, relationship_type FROM relationships")
                for row in cursor.fetchall():
                    relationships.append(
                        Relationship.model_validate({
                            "from": row[0],
                            "to": row[1],
                            "kind": cls.REL_KIND_MAP.get((row[2] or "").lower(), "calls"),
                            "confidence": 1.0,
                            "evidence_tag": "EXTRACTED",
                        })
                    )
            except Exception:
                pass

        conn.close()

        files_seen = list({s.file for s in symbols if s.file})
        entry_points = [f for f in files_seen if "main" in f or "index" in f]

        return AnalysisResult(
            shard_id=shard_id,
            files_seen=files_seen,
            entry_points=entry_points,
            symbols=symbols,
            relationships=relationships,
        )

    @classmethod
    def execute_bridge(
        cls,
        repo_root: Path,
        export_path: Path | None = None,
    ) -> AnalysisResult:
        """Run codebase-memory-mcp binary if available, or import from provided export file."""
        # 1. If explicit export file provided or set in env var
        export_env = os.environ.get("REKIPEDIA_CODEBASE_MEMORY_EXPORT")
        target_export = export_path or (Path(export_env) if export_env else None)

        if target_export and target_export.exists():
            if target_export.suffix in (".db", ".sqlite", ".sqlite3"):
                return cls.from_sqlite(target_export)
            raw_text = target_export.read_text(encoding="utf-8")
            return cls.from_dict(json.loads(raw_text))

        # 2. Check for binary on PATH
        binary = shutil.which("codebase-memory-mcp") or shutil.which("codebase-memory")
        if not binary:
            raise FileNotFoundError(
                "Neither codebase-memory-mcp binary was found on PATH nor was REKIPEDIA_CODEBASE_MEMORY_EXPORT provided.\n"
                "Install codebase-memory-mcp or specify an export path via REKIPEDIA_CODEBASE_MEMORY_EXPORT."
            )

        # 3. Execute binary to generate export
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
            tmp_json = Path(tmp.name)

        try:
            cmd = [binary, "index", str(repo_root), "--export", str(tmp_json)]
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            if tmp_json.exists():
                data = json.loads(tmp_json.read_text(encoding="utf-8"))
                return cls.from_dict(data)
            raise RuntimeError("codebase-memory-mcp completed but export file was not generated.")
        finally:
            if tmp_json.exists():
                tmp_json.unlink(missing_ok=True)
