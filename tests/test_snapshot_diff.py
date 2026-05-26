"""Tests for snapshot save/load/diff functionality."""
from __future__ import annotations

from rekipedia.models.contracts import AnalysisResult
from rekipedia.orchestrator.snapshot import (
    diff_snapshots,
    list_snapshots,
    load_snapshot,
    save_snapshot,
)


def make_ar(symbols=None, relationships=None):
    return AnalysisResult(
        shard_id="all",
        files_seen=[],
        entry_points=[],
        symbols=symbols or [],
        relationships=relationships or [],
        build_commands=[],
        test_commands=[],
        risks=[],
    )


def test_save_snapshot_creates_file(tmp_path):
    ar = make_ar()
    snap_path = save_snapshot(ar, tmp_path)
    assert snap_path.exists()
    assert snap_path.suffix == ".json"
    assert ".rekipedia/snapshots" in str(snap_path)


def test_load_snapshot_roundtrip(tmp_path):
    ar = make_ar()
    snap_path = save_snapshot(ar, tmp_path)
    data = load_snapshot(snap_path)
    assert "timestamp" in data
    assert "symbols" in data
    assert "relationships" in data
    assert data["symbols"] == []
    assert data["relationships"] == []


def test_list_snapshots(tmp_path):
    import time
    ar = make_ar()
    save_snapshot(ar, tmp_path)
    time.sleep(1)
    save_snapshot(ar, tmp_path)
    snaps = list_snapshots(tmp_path)
    assert len(snaps) >= 2


def test_diff_snapshots_added_symbols():
    snap_a = {"symbols": [{"name": "foo", "kind": "function"}], "relationships": []}
    snap_b = {"symbols": [{"name": "foo", "kind": "function"}, {"name": "bar", "kind": "class"}], "relationships": []}
    result = diff_snapshots(snap_a, snap_b)
    assert result["summary"]["symbols_added"] == 1
    assert result["summary"]["symbols_removed"] == 0
    assert result["symbols"]["added"][0]["name"] == "bar"


def test_diff_snapshots_removed_symbols():
    snap_a = {"symbols": [{"name": "foo"}, {"name": "bar"}], "relationships": []}
    snap_b = {"symbols": [{"name": "foo"}], "relationships": []}
    result = diff_snapshots(snap_a, snap_b)
    assert result["summary"]["symbols_removed"] == 1
    assert result["symbols"]["removed"][0]["name"] == "bar"


def test_diff_snapshots_modified_symbols():
    snap_a = {"symbols": [{"name": "foo", "kind": "function"}], "relationships": []}
    snap_b = {"symbols": [{"name": "foo", "kind": "class"}], "relationships": []}
    result = diff_snapshots(snap_a, snap_b)
    assert result["summary"]["symbols_modified"] == 1


def test_diff_snapshots_relationships():
    snap_a = {"symbols": [], "relationships": [{"from_": "A", "to": "B", "kind": "calls"}]}
    snap_b = {"symbols": [], "relationships": [
        {"from_": "A", "to": "B", "kind": "calls"},
        {"from_": "B", "to": "C", "kind": "imports"},
    ]}
    result = diff_snapshots(snap_a, snap_b)
    assert result["summary"]["relationships_added"] == 1
    assert result["summary"]["relationships_removed"] == 0


def test_diff_snapshots_removed_relationships():
    snap_a = {"symbols": [], "relationships": [
        {"from_": "A", "to": "B", "kind": "calls"},
        {"from_": "B", "to": "C", "kind": "imports"},
    ]}
    snap_b = {"symbols": [], "relationships": [{"from_": "A", "to": "B", "kind": "calls"}]}
    result = diff_snapshots(snap_a, snap_b)
    assert result["summary"]["relationships_removed"] == 1
