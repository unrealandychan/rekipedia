"""Tests for reki tour — guided learning walkthrough by dependency depth (#147)."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from rekipedia.analysis.tour import build_tour
from rekipedia.cli.tour import tour_cmd

# ── helpers ────────────────────────────────────────────────────────────────

def _make_symbols(*triples):
    """triples: (name, file, kind)"""
    return [{"name": n, "file": f, "kind": k, "line_start": 1} for n, f, k in triples]


def _make_symbol_rows(*triples):
    """triples: (name, file, kind) in scan_symbols tuple layout."""
    return [("run-123", n, k, f, 1, 1, None, None) for n, f, k in triples]


def _make_rels(*triples):
    """triples: (from_, to, kind)"""
    return [{"from_": fr, "to": t, "kind": k, "file": "", "confidence": 1.0, "evidence_tag": ""} for fr, t, k in triples]


def _make_store_mock(symbols, relationships):
    store = MagicMock()
    store.__enter__ = lambda s: s
    store.__exit__ = MagicMock(return_value=False)
    store.get_latest_run_id.return_value = "run-123"
    store.get_all_symbols.return_value = symbols
    store.get_all_relationships.return_value = relationships
    return store


# ── unit: build_tour ──────────────────────────────────────────────────────

class TestBuildTour:
    def test_build_tour_empty_store(self, tmp_path):
        store = _make_store_mock([], [])
        result = build_tour(store, "run-123", tmp_path)
        assert result["total_files"] == 0
        assert "phases" in result
        assert isinstance(result["phases"], list)

    def test_build_tour_phases(self, tmp_path):
        symbols = _make_symbols(
            ("BaseModel", "src/models.py", "class"),
            ("process", "src/logic.py", "function"),
            ("run_app", "src/main.py", "function"),
        )
        rels = _make_rels(
            ("process", "BaseModel", "uses"),
            ("run_app", "process", "calls"),
        )
        store = _make_store_mock(symbols, rels)
        result = build_tour(store, "run-123", tmp_path)
        assert result["total_files"] == 3
        assert len(result["phases"]) == 4  # all 4 phases included
        # at least one phase has files
        total_file_entries = sum(len(p["files"]) for p in result["phases"])
        assert total_file_entries == 3

    def test_tour_topological_order(self, tmp_path):
        """File with no deps should appear in a lower phase than its dependent."""
        symbols = _make_symbols(
            ("BaseModel", "src/models.py", "class"),
            ("run_app", "src/main.py", "function"),
        )
        rels = _make_rels(
            ("run_app", "BaseModel", "uses"),
        )
        store = _make_store_mock(symbols, rels)
        result = build_tour(store, "run-123", tmp_path)

        # find phase for each file
        phase_of = {}
        for phase in result["phases"]:
            for f in phase["files"]:
                phase_of[f["path"]] = phase["phase"]

        assert "src/models.py" in phase_of
        assert "src/main.py" in phase_of
        # models.py has no deps → lower phase
        assert phase_of["src/models.py"] < phase_of["src/main.py"]

    def test_build_tour_accepts_tuple_symbol_rows(self, tmp_path):
        symbols = _make_symbol_rows(
            ("BaseModel", "src/models.py", "class"),
            ("process", "src/logic.py", "function"),
            ("run_app", "src/main.py", "function"),
        )
        rels = _make_rels(
            ("process", "BaseModel", "uses"),
            ("run_app", "process", "calls"),
        )
        store = _make_store_mock(symbols, rels)
        result = build_tour(store, "run-123", tmp_path)
        assert result["total_files"] == 3


# ── CLI tests ─────────────────────────────────────────────────────────────

class TestTourCmd:
    runner = CliRunner()

    def _invoke(self, args, db_exists=True, store=None):
        symbols = _make_symbols(
            ("BaseModel", "src/models.py", "class"),
            ("process", "src/logic.py", "function"),
            ("run_app", "src/main.py", "function"),
        )
        rels = _make_rels(
            ("process", "BaseModel", "uses"),
            ("run_app", "process", "calls"),
        )
        _store = store or _make_store_mock(symbols, rels)
        with (
            patch("rekipedia.storage.sqlite_store.SqliteStore", return_value=_store),
            patch.object(Path, "exists", return_value=db_exists),
        ):
            return self.runner.invoke(tour_cmd, args, catch_exceptions=False)

    def test_tour_cli_text_output(self):
        result = self._invoke(["."])
        assert result.exit_code == 0
        assert "Phase" in result.output

    def test_tour_cli_json_output(self):
        result = self._invoke([".", "--format", "json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "phases" in data
        assert "total_files" in data

    def test_tour_cli_no_scan(self):
        result = self._invoke(["."], db_exists=False)
        assert result.exit_code != 0 or "reki scan" in result.output or "No scan" in result.output

    def test_tour_cli_output_file(self):
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
            out_path = f.name
        result = self._invoke([".", "--output", out_path])
        assert result.exit_code == 0
        assert Path(out_path).exists()
        content = Path(out_path).read_text()
        assert len(content) > 0

    def test_tour_cli_json_output_file(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            out_path = f.name
        result = self._invoke([".", "--format", "json", "--output", out_path])
        assert result.exit_code == 0
        data = json.loads(Path(out_path).read_text())
        assert "phases" in data
