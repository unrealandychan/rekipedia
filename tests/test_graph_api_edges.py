"""Tests for the multi-strategy edge ID resolution in the graph API."""
from __future__ import annotations

import tempfile

# ---------------------------------------------------------------------------
# Helpers — replicate the resolve_id logic from app.py so we can unit test it
# ---------------------------------------------------------------------------

def build_resolve_id(nodes: list[dict]):
    """Build a resolve_id function from a list of node dicts (id, label)."""
    label_to_id: dict[str, str] = {}
    id_set: set[str] = set()
    for n in nodes:
        label_to_id[n["label"]] = n["id"]
        id_set.add(n["id"])

    def resolve_id(name: str) -> str | None:
        if not name:
            return None
        if name in label_to_id:
            return label_to_id[name]
        if name in id_set:
            return name
        parts = name.split(".")
        if len(parts) > 1 and parts[-1] in label_to_id:
            return label_to_id[parts[-1]]
        if "." in name:
            method = name.split(".")[-1]
            if method in label_to_id:
                return label_to_id[method]
        return None

    return resolve_id


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------

SAMPLE_NODES = [
    {"id": "src/rekipedia/cli/scan.py::scan", "label": "scan"},
    {"id": "src/rekipedia/cli/scan.py::run_scan", "label": "run_scan"},
    {"id": "src/rekipedia/storage.py::PageBuilder", "label": "PageBuilder"},
    {"id": "src/rekipedia/storage.py::build", "label": "build"},
]


def test_resolve_id_exact_label_match():
    resolve_id = build_resolve_id(SAMPLE_NODES)
    result = resolve_id("scan")
    assert result == "src/rekipedia/cli/scan.py::scan"


def test_resolve_id_dotted_module_fallback():
    """rekipedia.cli.scan → last segment 'scan' resolves to correct node."""
    resolve_id = build_resolve_id(SAMPLE_NODES)
    result = resolve_id("rekipedia.cli.scan")
    assert result == "src/rekipedia/cli/scan.py::scan"


def test_resolve_id_class_method_format():
    """PageBuilder.build → method 'build' resolves to correct node."""
    resolve_id = build_resolve_id(SAMPLE_NODES)
    result = resolve_id("PageBuilder.build")
    assert result == "src/rekipedia/storage.py::build"


def test_edge_dropped_when_unresolvable():
    """Edges where from_ or to_ can't be resolved must not appear in output."""
    nodes = [{"id": "a.py::foo", "label": "foo"}]
    resolve_id = build_resolve_id(nodes)
    raw_rels = [
        {"from_": "completely_unknown", "to": "also_unknown", "kind": "calls"},
    ]
    edges = []
    for row in raw_rels:
        src = resolve_id(row["from_"])
        tgt = resolve_id(row["to"])
        if src and tgt and src != tgt:
            edges.append({"source": src, "target": tgt, "kind": row["kind"]})
    assert edges == []


def test_self_loop_dropped():
    """Edge where src_id == tgt_id must be dropped."""
    nodes = [{"id": "a.py::foo", "label": "foo"}]
    resolve_id = build_resolve_id(nodes)
    raw_rels = [{"from_": "foo", "to": "foo", "kind": "calls"}]
    edges = []
    for row in raw_rels:
        src = resolve_id(row["from_"])
        tgt = resolve_id(row["to"])
        if src and tgt and src != tgt:
            edges.append({"source": src, "target": tgt, "kind": row["kind"]})
    assert edges == []


def test_graph_api_returns_edges():
    """End-to-end: file-level graph — beta.py imports alpha.py → edge appears."""
    from pathlib import Path

    from fastapi.testclient import TestClient

    from rekipedia.models.contracts import LLMConfig
    from rekipedia.server.app import create_app
    from rekipedia.storage.sqlite_store import SqliteStore

    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir) / "repo"
        output_dir = repo / ".rekipedia"
        output_dir.mkdir(parents=True)
        db = output_dir / "store.db"

        with SqliteStore(db) as store:
            store.upsert_run("run-e2e", str(repo))
            store.update_run_status("run-e2e", "success")
            store.upsert_symbols("run-e2e", [
                {"name": "Alpha", "kind": "class", "file": "alpha.py", "line_start": 1, "line_end": 5, "signature": "", "docstring": ""},
                {"name": "Beta", "kind": "class", "file": "beta.py", "line_start": 1, "line_end": 5, "signature": "", "docstring": ""},
            ])
            # File-level: beta.py imports the "alpha" module (maps to alpha.py)
            store.upsert_relationships("run-e2e", [
                {"from_": "beta", "to": "alpha", "kind": "imports", "file": "beta.py"},
            ])

        app = create_app(repo, output_dir, LLMConfig())
        with TestClient(app, raise_server_exceptions=False) as c:
            res = c.get("/api/graph")
        assert res.status_code == 200
        data = res.json()
        assert len(data.get("nodes", [])) >= 2
        assert len(data.get("edges", [])) > 0, f"Expected edges > 0, got {data}"

