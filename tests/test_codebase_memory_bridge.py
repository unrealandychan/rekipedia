"""Tests for Issue #247: Hybrid Engine Bridge (codebase-memory-mcp adapter)."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
import pytest

from rekipedia.extractors.bridge.codebase_memory_bridge import CodebaseMemoryAdapter


def test_codebase_memory_from_dict_normalization():
    """Verify symbol and relationship normalization from codebase-memory dict."""
    data = {
        "symbols": [
            {
                "name": "KernelInit",
                "kind": "fn",
                "file": "init/main.c",
                "line_start": 42,
                "line_end": 100,
                "signature": "void KernelInit(void)",
            },
            {
                "symbol": "DeviceDriver",
                "symbol_type": "struct",
                "path": "drivers/base.c",
                "start_line": 200,
            },
        ],
        "relationships": [
            {
                "from": "KernelInit",
                "to": "DeviceDriver",
                "kind": "calls",
                "file": "init/main.c",
                "confidence": 0.95,
                "evidence_tag": "EXTRACTED",
            },
            {
                "from_symbol_id": "DeviceDriver",
                "to_symbol_id": "BaseDevice",
                "relationship_type": "extends",
                "confidence_score": 1.0,
            },
        ],
    }

    result = CodebaseMemoryAdapter.from_dict(data)
    assert len(result.symbols) == 2
    assert len(result.relationships) == 2

    s1 = next(s for s in result.symbols if s.name == "KernelInit")
    assert s1.kind == "function"
    assert s1.file == "init/main.c"
    assert s1.line_start == 42
    assert s1.line_end == 100

    s2 = next(s for s in result.symbols if s.name == "DeviceDriver")
    assert s2.kind == "class"
    assert s2.file == "drivers/base.c"

    r1 = next(r for r in result.relationships if r.from_ == "KernelInit")
    assert r1.to == "DeviceDriver"
    assert r1.kind == "calls"
    assert r1.confidence == 0.95

    r2 = next(r for r in result.relationships if r.from_ == "DeviceDriver")
    assert r2.to == "BaseDevice"
    assert r2.kind == "inherits"


def test_codebase_memory_from_sqlite(tmp_path: Path):
    """Verify loading symbols and relationships directly from codebase-memory SQLite DB."""
    db_file = tmp_path / "codebase_memory.db"
    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE symbols (
            name TEXT,
            kind TEXT,
            file TEXT,
            line_start INTEGER,
            line_end INTEGER,
            signature TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE relationships (
            from_ TEXT,
            to_ TEXT,
            kind TEXT,
            file TEXT,
            confidence REAL
        )
    """)

    cur.execute(
        "INSERT INTO symbols VALUES (?, ?, ?, ?, ?, ?)",
        ("sys_open", "func", "fs/open.c", 10, 50, "int sys_open(const char *path)"),
    )
    cur.execute(
        "INSERT INTO relationships VALUES (?, ?, ?, ?, ?)",
        ("sys_open", "do_sys_open", "call", "fs/open.c", 1.0),
    )
    conn.commit()
    conn.close()

    result = CodebaseMemoryAdapter.from_sqlite(db_file)
    assert len(result.symbols) == 1
    assert len(result.relationships) == 1

    s = result.symbols[0]
    assert s.name == "sys_open"
    assert s.kind == "function"
    assert s.file == "fs/open.c"

    r = result.relationships[0]
    assert r.from_ == "sys_open"
    assert r.to == "do_sys_open"
    assert r.kind == "calls"


def test_execute_bridge_with_export_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Verify execute_bridge reads export when pointed by REKIPEDIA_CODEBASE_MEMORY_EXPORT."""
    json_export = tmp_path / "export.json"
    json_export.write_text(
        json.dumps({
            "symbols": [{"name": "fast_parse", "kind": "function", "file": "src/parse.c"}],
            "relationships": [],
        }),
        encoding="utf-8",
    )

    monkeypatch.setenv("REKIPEDIA_CODEBASE_MEMORY_EXPORT", str(json_export))
    result = CodebaseMemoryAdapter.execute_bridge(tmp_path)
    assert len(result.symbols) == 1
    assert result.symbols[0].name == "fast_parse"


def test_execute_bridge_missing_binary_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Verify FileNotFoundError is raised when binary and export are missing."""
    monkeypatch.delenv("REKIPEDIA_CODEBASE_MEMORY_EXPORT", raising=False)
    monkeypatch.setattr("shutil.which", lambda cmd: None)

    with pytest.raises(FileNotFoundError, match="codebase-memory-mcp binary"):
        CodebaseMemoryAdapter.execute_bridge(tmp_path)
