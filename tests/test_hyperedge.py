"""Tests for Hyperedge support: N-ary relationships, design patterns, and architectural motifs."""
from __future__ import annotations

import json
from pathlib import Path
import pytest

from rekipedia.models.contracts import AnalysisResult, Relationship, Symbol
from rekipedia.models.hyperedge import Hyperedge
from rekipedia.analysis.hyperedge_detector import detect_structural_hyperedges, detect_hyperedges
from rekipedia.storage.sqlite_store import SqliteStore
from rekipedia.exporters.json_export import JsonExporter
from rekipedia.synthesis.page_builder import format_design_patterns_section


def test_hyperedge_model_instantiation():
    """Verify Hyperedge model creation and field serialization."""
    h = Hyperedge(
        id="pattern::repository",
        concept="Repository Pattern",
        nodes=["UserRepository", "OrderRepository", "ProductRepository"],
        description="Encapsulates data access behind repository interfaces.",
        confidence="EXTRACTED",
        pattern_type="design_pattern",
    )
    assert h.id == "pattern::repository"
    assert h.concept == "Repository Pattern"
    assert len(h.nodes) == 3
    assert h.confidence == "EXTRACTED"
    assert h.pattern_type == "design_pattern"

    d = h.to_dict()
    assert d["id"] == "pattern::repository"
    assert d["nodes"] == ["UserRepository", "OrderRepository", "ProductRepository"]


def test_detect_structural_hyperedges_naming_motifs():
    """Verify detection of Repository, Service, and Controller naming motifs with 3+ symbols."""
    symbols = [
        Symbol(name="UserRepository", kind="class", file="src/repos/user.py"),
        Symbol(name="OrderRepository", kind="class", file="src/repos/order.py"),
        Symbol(name="ProductRepository", kind="class", file="src/repos/product.py"),
        Symbol(name="AuthService", kind="class", file="src/services/auth.py"),
        Symbol(name="PaymentService", kind="class", file="src/services/pay.py"),
        Symbol(name="NotificationService", kind="class", file="src/services/notify.py"),
        Symbol(name="LoneClass", kind="class", file="src/single.py"),
    ]
    relationships = []

    hyperedges = detect_structural_hyperedges(symbols, relationships, min_nodes=3)
    concepts = {h.concept: h for h in hyperedges}

    assert "Repository Pattern" in concepts
    repo_edge = concepts["Repository Pattern"]
    assert set(repo_edge.nodes) == {"UserRepository", "OrderRepository", "ProductRepository"}
    assert repo_edge.confidence == "EXTRACTED"
    assert repo_edge.pattern_type == "design_pattern"

    assert "Service Layer Pattern" in concepts
    service_edge = concepts["Service Layer Pattern"]
    assert set(service_edge.nodes) == {"AuthService", "PaymentService", "NotificationService"}


def test_detect_structural_hyperedges_inheritance_clusters():
    """Verify detection of clusters sharing a common base class (3+ symbols)."""
    symbols = [
        Symbol(name="BaseRunner", kind="class", file="runner/base.py"),
        Symbol(name="DockerRunner", kind="class", file="runner/docker.py"),
        Symbol(name="LocalRunner", kind="class", file="runner/local.py"),
        Symbol(name="RemoteRunner", kind="class", file="runner/remote.py"),
    ]
    relationships = [
        Relationship(**{"from": "DockerRunner", "to": "BaseRunner", "kind": "inherits"}),
        Relationship(**{"from": "LocalRunner", "to": "BaseRunner", "kind": "inherits"}),
        Relationship(**{"from": "RemoteRunner", "to": "BaseRunner", "kind": "inherits"}),
    ]

    hyperedges = detect_structural_hyperedges(symbols, relationships, min_nodes=3)
    inheritance_edges = [h for h in hyperedges if "BaseRunner" in h.concept]
    assert len(inheritance_edges) == 1
    edge = inheritance_edges[0]
    assert set(edge.nodes) == {"DockerRunner", "LocalRunner", "RemoteRunner"}
    assert edge.pattern_type == "shared_concept"


def test_sqlite_store_hyperedges_crud(tmp_path: Path):
    """Verify saving and retrieving hyperedges from SQLite database."""
    db_file = tmp_path / "store.db"
    run_id = "test_run_123"
    with SqliteStore(db_file) as store:
        store.upsert_run(run_id, str(tmp_path))

        h1 = Hyperedge(
            id="pattern::repo",
            concept="Repository Pattern",
            nodes=["UserRepo", "OrderRepo", "ItemRepo"],
            description="Repositories for entities.",
            confidence="EXTRACTED",
            pattern_type="design_pattern",
        )
        h2 = Hyperedge(
            id="motif::service",
            concept="Service Layer",
            nodes=["UserService", "OrderService", "ItemService"],
            description="Business services.",
            confidence="INFERRED",
            pattern_type="architectural_motif",
        )

        store.upsert_hyperedges(run_id, [h1, h2])

        loaded = store.get_hyperedges(run_id)
        assert len(loaded) == 2

        by_id = {h["id"]: h for h in loaded}
        assert "pattern::repo" in by_id
        assert by_id["pattern::repo"]["concept"] == "Repository Pattern"
        assert set(by_id["pattern::repo"]["nodes"]) == {"UserRepo", "OrderRepo", "ItemRepo"}
        assert by_id["pattern::repo"]["confidence"] == "EXTRACTED"

        assert "motif::service" in by_id
        assert set(by_id["motif::service"]["nodes"]) == {"UserService", "OrderService", "ItemService"}

        # Another run should see empty
        assert store.get_hyperedges("non_existent_run") == []


def test_json_exporter_hyperedges(tmp_path: Path):
    """Verify JsonExporter writes hyperedges.json and includes them in manifest.json."""
    exporter = JsonExporter(tmp_path)
    run_id = "run_json_test"

    h = Hyperedge(
        id="pattern::factory",
        concept="Factory Pattern",
        nodes=["WidgetFactory", "GadgetFactory", "ButtonFactory"],
        description="Creates UI elements.",
        confidence="EXTRACTED",
    )
    combined = AnalysisResult(
        shard_id="s1",
        files_seen=["a.py"],
        entry_points=["main"],
        hyperedges=[h],
    )

    exporter.export(
        run_id=run_id,
        files=[],
        combined=combined,
        pages={},
        diagrams={},
    )

    manifest_file = tmp_path / "exports" / "manifest.json"
    assert manifest_file.exists()
    manifest_data = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert manifest_data.get("hyperedge_count") == 1
    assert len(manifest_data.get("hyperedges", [])) == 1
    assert manifest_data["hyperedges"][0]["concept"] == "Factory Pattern"

    hyperedges_file = tmp_path / "exports" / "hyperedges.json"
    assert hyperedges_file.exists()
    hyperedges_data = json.loads(hyperedges_file.read_text(encoding="utf-8"))
    assert len(hyperedges_data) == 1
    assert hyperedges_data[0]["id"] == "pattern::factory"


def test_format_design_patterns_section():
    """Verify Markdown generation for Design Patterns section."""
    h = Hyperedge(
        id="pattern::repo",
        concept="Repository Pattern",
        nodes=["A_Repo", "B_Repo", "C_Repo"],
        description="Data abstraction layer.",
        confidence="EXTRACTED",
        pattern_type="design_pattern",
    )
    md = format_design_patterns_section([h])
    assert "## Design Patterns & Architectural Motifs" in md
    assert "### Repository Pattern" in md
    assert "`A_Repo`, `B_Repo`, `C_Repo`" in md
    assert "Data abstraction layer." in md
