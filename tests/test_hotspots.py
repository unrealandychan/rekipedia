"""Tests for reki hotspots — hub & bridge node detection."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers — build an in-memory-like SqliteStore with mock data
# ---------------------------------------------------------------------------

def _make_store_with_data():
    """Create a temporary SqliteStore with mock symbols and relationships."""
    from rekipedia.storage.sqlite_store import SqliteStore

    tmp = tempfile.mkdtemp()
    db_path = Path(tmp) / "store.db"
    store = SqliteStore(db_path)
    store.open()

    run_id = "test-run-001"
    store.upsert_run(run_id, tmp)

    # Upsert symbols
    symbols = [
        {"name": "Scanner.scan", "kind": "method", "file": "scanner.py", "line": 10, "docstring": ""},
        {"name": "SqliteStore.__init__", "kind": "method", "file": "storage/sqlite_store.py", "line": 20, "docstring": ""},
        {"name": "run_ask", "kind": "function", "file": "orchestrator/run_ask.py", "line": 5, "docstring": ""},
        {"name": "parse_args", "kind": "function", "file": "cli/main.py", "line": 1, "docstring": ""},
        {"name": "leaf_func", "kind": "function", "file": "utils.py", "line": 1, "docstring": ""},
    ]
    store.upsert_symbols(run_id, symbols)

    # Build relationships:
    # Scanner.scan: in=3 (called by A, B, C), out=5 (calls D,E,F,G,H) → total=8, bridge=15
    # run_ask: in=4, out=4 → total=8, bridge=16 (top bridge)
    # SqliteStore.__init__: in=5, out=2 → total=7
    # parse_args: in=1, out=3 → total=4
    # leaf_func: in=6, out=0 → total=6
    rels = []
    # Scanner.scan gets called by 3 sources
    for i in range(3):
        rels.append({"from_": f"caller_{i}", "to": "Scanner.scan", "kind": "calls", "file": "x.py", "confidence": 1.0, "evidence_tag": ""})
    # Scanner.scan calls 5 things
    for i in range(5):
        rels.append({"from_": "Scanner.scan", "to": f"callee_{i}", "kind": "calls", "file": "scanner.py", "confidence": 1.0, "evidence_tag": ""})

    # run_ask: in=4, out=4
    for i in range(4):
        rels.append({"from_": f"src_{i}", "to": "run_ask", "kind": "calls", "file": "x.py", "confidence": 1.0, "evidence_tag": ""})
    for i in range(4):
        rels.append({"from_": "run_ask", "to": f"tgt_{i}", "kind": "calls", "file": "x.py", "confidence": 1.0, "evidence_tag": ""})

    # SqliteStore.__init__: in=5, out=2
    for i in range(5):
        rels.append({"from_": f"init_caller_{i}", "to": "SqliteStore.__init__", "kind": "calls", "file": "x.py", "confidence": 1.0, "evidence_tag": ""})
    for i in range(2):
        rels.append({"from_": "SqliteStore.__init__", "to": f"init_dep_{i}", "kind": "calls", "file": "x.py", "confidence": 1.0, "evidence_tag": ""})

    # parse_args: in=1, out=3
    rels.append({"from_": "main", "to": "parse_args", "kind": "calls", "file": "x.py", "confidence": 1.0, "evidence_tag": ""})
    for i in range(3):
        rels.append({"from_": "parse_args", "to": f"opt_{i}", "kind": "calls", "file": "x.py", "confidence": 1.0, "evidence_tag": ""})

    # leaf_func: in=6, out=0
    for i in range(6):
        rels.append({"from_": f"leaf_caller_{i}", "to": "leaf_func", "kind": "calls", "file": "x.py", "confidence": 1.0, "evidence_tag": ""})

    store.upsert_relationships(run_id, rels)
    return store, run_id, db_path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestGetHubNodes:
    def test_returns_top_n_by_degree(self):
        from rekipedia.analysis.graph_analysis import get_hub_nodes

        store, run_id, _ = _make_store_with_data()
        try:
            hubs = get_hub_nodes(store, run_id, top_n=3)
            assert len(hubs) == 3
            # top nodes should be sorted descending by total_degree
            degrees = [h["total_degree"] for h in hubs]
            assert degrees == sorted(degrees, reverse=True)
        finally:
            store.close()

    def test_contains_required_fields(self):
        from rekipedia.analysis.graph_analysis import get_hub_nodes

        store, run_id, _ = _make_store_with_data()
        try:
            hubs = get_hub_nodes(store, run_id, top_n=5)
            for h in hubs:
                assert "name" in h
                assert "in_degree" in h
                assert "out_degree" in h
                assert "total_degree" in h
                assert h["total_degree"] == h["in_degree"] + h["out_degree"]
        finally:
            store.close()

    def test_top_n_respected(self):
        from rekipedia.analysis.graph_analysis import get_hub_nodes

        store, run_id, _ = _make_store_with_data()
        try:
            hubs = get_hub_nodes(store, run_id, top_n=2)
            assert len(hubs) <= 2
        finally:
            store.close()

    def test_empty_store_returns_empty(self):
        from rekipedia.analysis.graph_analysis import get_hub_nodes
        from rekipedia.storage.sqlite_store import SqliteStore

        tmp = tempfile.mkdtemp()
        db_path = Path(tmp) / "empty.db"
        with SqliteStore(db_path) as store:
            store.upsert_run("run-empty", tmp)
            hubs = get_hub_nodes(store, "run-empty", top_n=10)
        assert hubs == []


class TestGetBridgeNodes:
    def test_returns_top_n_by_bridge_score(self):
        from rekipedia.analysis.graph_analysis import get_bridge_nodes

        store, run_id, _ = _make_store_with_data()
        try:
            bridges = get_bridge_nodes(store, run_id, top_n=3)
            scores = [b["bridge_score"] for b in bridges]
            assert scores == sorted(scores, reverse=True)
        finally:
            store.close()

    def test_bridge_score_is_in_times_out(self):
        from rekipedia.analysis.graph_analysis import get_bridge_nodes

        store, run_id, _ = _make_store_with_data()
        try:
            bridges = get_bridge_nodes(store, run_id, top_n=10)
            for b in bridges:
                assert b["bridge_score"] == b["in_degree"] * b["out_degree"]
                assert b["in_degree"] >= 1
                assert b["out_degree"] >= 1
        finally:
            store.close()

    def test_leaf_nodes_excluded(self):
        """Nodes with only in_degree or only out_degree should not appear."""
        from rekipedia.analysis.graph_analysis import get_bridge_nodes

        store, run_id, _ = _make_store_with_data()
        try:
            bridges = get_bridge_nodes(store, run_id, top_n=20)
            names = {b["name"] for b in bridges}
            # leaf_func has out_degree=0 so should not be a bridge
            assert "leaf_func" not in names
        finally:
            store.close()

    def test_contains_required_fields(self):
        from rekipedia.analysis.graph_analysis import get_bridge_nodes

        store, run_id, _ = _make_store_with_data()
        try:
            bridges = get_bridge_nodes(store, run_id, top_n=5)
            for b in bridges:
                assert "name" in b
                assert "in_degree" in b
                assert "out_degree" in b
                assert "bridge_score" in b
        finally:
            store.close()


class TestHotspotsCli:
    def test_table_output_runs_without_error(self, tmp_path):
        from click.testing import CliRunner

        from rekipedia.cli.hotspots import hotspots_cmd
        from rekipedia.storage.sqlite_store import SqliteStore

        # Create a minimal store
        db_dir = tmp_path / ".rekipedia"
        db_dir.mkdir()
        db_path = db_dir / "store.db"
        with SqliteStore(db_path) as store:
            run_id = "r1"
            store.upsert_run(run_id, str(tmp_path), status="success")
            store.upsert_symbols(run_id, [{"name": "foo", "kind": "function", "file": "a.py", "line": 1, "docstring": ""}])
            store.upsert_relationships(run_id, [
                {"from_": "bar", "to": "foo", "kind": "calls", "file": "b.py", "confidence": 1.0, "evidence_tag": ""},
                {"from_": "foo", "to": "baz", "kind": "calls", "file": "a.py", "confidence": 1.0, "evidence_tag": ""},
            ])

        runner = CliRunner()
        result = runner.invoke(hotspots_cmd, [str(tmp_path), "--top", "5", "--format", "table"])
        assert result.exit_code == 0, result.output

    def test_json_output_is_valid_json(self, tmp_path):
        from click.testing import CliRunner

        from rekipedia.cli.hotspots import hotspots_cmd
        from rekipedia.storage.sqlite_store import SqliteStore

        db_dir = tmp_path / ".rekipedia"
        db_dir.mkdir()
        db_path = db_dir / "store.db"
        with SqliteStore(db_path) as store:
            run_id = "r2"
            store.upsert_run(run_id, str(tmp_path), status="success")
            store.upsert_symbols(run_id, [{"name": "alpha", "kind": "function", "file": "a.py", "line": 1, "docstring": ""}])
            store.upsert_relationships(run_id, [
                {"from_": "x", "to": "alpha", "kind": "calls", "file": "x.py", "confidence": 1.0, "evidence_tag": ""},
                {"from_": "alpha", "to": "y", "kind": "calls", "file": "a.py", "confidence": 1.0, "evidence_tag": ""},
            ])

        runner = CliRunner()
        result = runner.invoke(hotspots_cmd, [str(tmp_path), "--format", "json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert "hub_nodes" in data
        assert "bridge_nodes" in data

    def test_md_output_contains_headers(self, tmp_path):
        from click.testing import CliRunner

        from rekipedia.cli.hotspots import hotspots_cmd
        from rekipedia.storage.sqlite_store import SqliteStore

        db_dir = tmp_path / ".rekipedia"
        db_dir.mkdir()
        db_path = db_dir / "store.db"
        with SqliteStore(db_path) as store:
            run_id = "r3"
            store.upsert_run(run_id, str(tmp_path), status="success")

        runner = CliRunner()
        result = runner.invoke(hotspots_cmd, [str(tmp_path), "--format", "md"])
        assert result.exit_code == 0
        assert "# Architectural Hotspots" in result.output
        assert "Hub Nodes" in result.output
        assert "Bridge Nodes" in result.output
