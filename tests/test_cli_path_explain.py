"""Tests for reki path and reki explain CLI commands."""
from __future__ import annotations

import json
from pathlib import Path
from click.testing import CliRunner
import pytest

from rekipedia.cli import main
from rekipedia.models.contracts import Relationship, Symbol
from rekipedia.models.hyperedge import Hyperedge
from rekipedia.storage.sqlite_store import SqliteStore


@pytest.fixture
def test_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    dot_reki = repo / ".rekipedia"
    dot_reki.mkdir()
    db_file = dot_reki / "store.db"

    run_id = "test_run_1"
    with SqliteStore(db_file) as store:
        store.upsert_run(run_id, str(repo), status="success")

        symbols = [
            {"name": "App", "kind": "class", "file": "src/app.py", "line_start": 10, "line_end": 50},
            {"name": "Router", "kind": "class", "file": "src/router.py", "line_start": 5, "line_end": 30},
            {"name": "AuthService", "kind": "class", "file": "src/auth.py", "line_start": 1, "line_end": 20},
            {"name": "UserRepo", "kind": "class", "file": "src/repo.py", "line_start": 1, "line_end": 25},
        ]
        store.upsert_symbols(run_id, symbols)

        rels = [
            {"from": "App", "to": "Router", "kind": "calls", "file": "src/app.py", "confidence": 1.0, "evidence_tag": "EXTRACTED"},
            {"from": "Router", "to": "AuthService", "kind": "calls", "file": "src/router.py", "confidence": 0.9, "evidence_tag": "INFERRED"},
            {"from": "AuthService", "to": "UserRepo", "kind": "calls", "file": "src/auth.py", "confidence": 1.0, "evidence_tag": "EXTRACTED"},
        ]
        store.upsert_relationships(run_id, rels)

        notes = [
            {"tag": "NOTE", "content": "Critical authentication entry point", "file": "src/auth.py", "line": 5}
        ]
        store.upsert_rationale_notes(run_id, notes)

        hypers = [
            Hyperedge(id="p1", concept="Repository Pattern", nodes=["UserRepo", "OrderRepo", "ItemRepo"])
        ]
        store.upsert_hyperedges(run_id, hypers)

    return repo


def test_cli_path_found(test_repo: Path):
    runner = CliRunner()
    result = runner.invoke(main, ["path", "App", "UserRepo", "--repo", str(test_repo), "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["reachable"] is True
    assert data["length"] == 3
    assert data["path"] == ["App", "Router", "AuthService", "UserRepo"]
    assert len(data["hops"]) == 3
    assert data["hops"][1]["kind"] == "calls"
    assert data["hops"][1]["evidence_tag"] == "INFERRED"


def test_cli_path_unreachable(test_repo: Path):
    runner = CliRunner()
    result = runner.invoke(main, ["path", "UserRepo", "App", "--repo", str(test_repo), "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["reachable"] is False


def test_cli_explain_symbol_found(test_repo: Path):
    runner = CliRunner()
    result = runner.invoke(main, ["explain", "AuthService", "--repo", str(test_repo), "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["found"] is True
    assert data["symbol"] == "AuthService"
    assert data["kind"] == "class"
    assert data["in_degree"] == 1
    assert data["out_degree"] == 1
    assert data["callers"][0]["symbol"] == "Router"
    assert data["callees"][0]["symbol"] == "UserRepo"
    assert len(data["rationale_notes"]) == 1
    assert data["rationale_notes"][0]["tag"] == "NOTE"


def test_cli_explain_hyperedge_membership(test_repo: Path):
    runner = CliRunner()
    result = runner.invoke(main, ["explain", "UserRepo", "--repo", str(test_repo), "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["found"] is True
    assert len(data["hyperedges"]) == 1
    assert data["hyperedges"][0]["concept"] == "Repository Pattern"
