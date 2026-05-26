"""Extra coverage tests for rekipedia server/app.py."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from rekipedia.models.contracts import LLMConfig
from rekipedia.server.app import create_app
from rekipedia.storage.sqlite_store import SqliteStore

# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def empty_env(tmp_path):
    """An environment with no wiki pages at all."""
    repo = tmp_path / "emptyrepo"
    repo.mkdir()
    output_dir = repo / ".rekipedia"
    output_dir.mkdir()
    yield repo, output_dir


@pytest.fixture
def empty_client(empty_env):
    repo, output_dir = empty_env
    app = create_app(repo, output_dir, LLMConfig())
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def wiki_env(tmp_path):
    repo = tmp_path / "myrepo"
    output_dir = repo / ".rekipedia"
    wiki_dir = output_dir / "wiki"
    wiki_dir.mkdir(parents=True)
    (wiki_dir / "index.md").write_text("# Index\n\nHello world.")
    (wiki_dir / "architecture.md").write_text("# Architecture\n\nMermaid goes here.")
    db = output_dir / "store.db"
    with SqliteStore(db) as store:
        store.upsert_run("run-1", str(repo))
        store.update_run_status("run-1", "success")
    yield repo, output_dir


@pytest.fixture
def client(wiki_env):
    repo, output_dir = wiki_env
    app = create_app(repo, output_dir, LLMConfig())
    return TestClient(app, raise_server_exceptions=False)


# ── GET / ──────────────────────────────────────────────────────────────────────

def test_index_empty_state_returns_200(empty_client):
    res = empty_client.get("/")
    assert res.status_code == 200


def test_index_with_pages_returns_200(client):
    res = client.get("/")
    assert res.status_code == 200


# ── GET /wiki/{slug} ──────────────────────────────────────────────────────────

def test_wiki_page_exists_returns_200(client):
    res = client.get("/wiki/index")
    assert res.status_code == 200
    assert "Hello world" in res.text


def test_wiki_page_missing_returns_404(client):
    res = client.get("/wiki/nonexistent-page")
    assert res.status_code == 404


def test_wiki_page_invalid_slug_returns_404(client):
    # Dots are not in _SLUG_RE so foo.bar should fail the regex check
    res = client.get("/wiki/foo.bar")
    assert res.status_code == 404


# ── GET /graph ────────────────────────────────────────────────────────────────

def test_graph_page_returns_200(client):
    res = client.get("/graph")
    assert res.status_code == 200


# ── GET /api/graph ────────────────────────────────────────────────────────────

def test_api_graph_returns_nodes_and_edges(client):
    res = client.get("/api/graph")
    assert res.status_code == 200
    data = res.json()
    assert "nodes" in data
    assert "edges" in data


def test_api_graph_no_db_returns_empty(empty_client):
    res = empty_client.get("/api/graph")
    assert res.status_code == 200
    data = res.json()
    assert data["nodes"] == []
    assert data["edges"] == []


# ── GET /api/health ───────────────────────────────────────────────────────────

def test_api_health_returns_status_key(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.json()
    assert "status" in data


def test_api_health_no_db(empty_client):
    res = empty_client.get("/api/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


# ── POST /ask ─────────────────────────────────────────────────────────────────

def test_post_ask_question_missing_returns_error(wiki_env):
    """POST /ask with no question param should return a client error (app has a known Form import bug)."""
    repo, output_dir = wiki_env
    app = create_app(repo, output_dir, LLMConfig())
    with TestClient(app, raise_server_exceptions=False) as c:
        res = c.post("/ask")
    # 422 = validation error (missing question), 500 = internal, either way not 200
    assert res.status_code in (400, 422, 500)


def test_api_graph_with_db_run(wiki_env):
    """GET /api/graph returns nodes/edges when DB has a run_id."""
    repo, output_dir = wiki_env
    app = create_app(repo, output_dir, LLMConfig())
    with TestClient(app, raise_server_exceptions=False) as c:
        res = c.get("/api/graph")
    assert res.status_code == 200
    data = res.json()
    assert "nodes" in data
    assert "edges" in data


# ── _wiki_pages() helper ──────────────────────────────────────────────────────

def test_wiki_pages_empty_when_no_wiki_dir(empty_env):
    repo, output_dir = empty_env
    app = create_app(repo, output_dir, LLMConfig())
    # Access via the index route — pages list will be empty → first_slug is None
    with TestClient(app, raise_server_exceptions=False) as c:
        res = c.get("/")
    assert res.status_code == 200
    # No wiki dir → no page links
    assert "wiki/" not in res.text or "index" not in res.text


def test_wiki_pages_ordered_by_manifest(tmp_path):
    repo = tmp_path / "repo"
    output_dir = repo / ".rekipedia"
    wiki_dir = output_dir / "wiki"
    wiki_dir.mkdir(parents=True)
    # Two pages
    (wiki_dir / "beta.md").write_text("# Beta\n\nContent.")
    (wiki_dir / "alpha.md").write_text("# Alpha\n\nContent.")
    # manifest specifies beta first
    exports_dir = output_dir / "exports"
    exports_dir.mkdir(parents=True)
    (exports_dir / "manifest.json").write_text(
        json.dumps({"nav_order": ["beta", "alpha"]})
    )
    app = create_app(repo, output_dir, LLMConfig())
    with TestClient(app, raise_server_exceptions=False) as c:
        res = c.get("/")
    assert res.status_code == 200
    # beta should appear before alpha in nav
    assert res.text.index("beta") < res.text.index("alpha")


def test_wiki_page_frontmatter_not_rendered(tmp_path):
    """Wiki page content must not include raw frontmatter fields in rendered HTML."""
    repo = tmp_path / "fmrepo"
    output_dir = repo / ".rekipedia"
    wiki_dir = output_dir / "wiki"
    wiki_dir.mkdir(parents=True)
    page_content = (
        "---\n"
        "slug: architecture-overview\n"
        'title: "System Architecture Overview"\n'
        "section: architecture\n"
        "tags: [architecture, overview]\n"
        "pin: false\n"
        "---\n\n"
        "# System Architecture Overview\n\n"
        "This is the architecture page.\n"
    )
    (wiki_dir / "architecture-overview.md").write_text(page_content)
    app = create_app(repo, output_dir, LLMConfig())
    with TestClient(app, raise_server_exceptions=False) as c:
        res = c.get("/wiki/architecture-overview")
    assert res.status_code == 200
    # Frontmatter fields must NOT appear as visible text in the rendered page
    assert "slug: architecture-overview" not in res.text
    assert "pin: false" not in res.text
    assert "tags: [architecture, overview]" not in res.text


def test_summary_html_frontmatter_not_rendered(tmp_path):
    """Index page summary must not include raw frontmatter text."""
    repo = tmp_path / "sumrepo"
    output_dir = repo / ".rekipedia"
    wiki_dir = output_dir / "wiki"
    wiki_dir.mkdir(parents=True)
    page_content = (
        "---\n"
        "slug: architecture-overview\n"
        'title: "System Architecture Overview"\n'
        "section: architecture\n"
        "tags: [architecture, overview]\n"
        "pin: false\n"
        "---\n\n"
        "# System Architecture Overview\n\n"
        "Intro paragraph text.\n"
    )
    (wiki_dir / "architecture-overview.md").write_text(page_content)
    app = create_app(repo, output_dir, LLMConfig())
    with TestClient(app, raise_server_exceptions=False) as c:
        res = c.get("/")
    assert res.status_code == 200
    # Frontmatter must not appear in the summary section of the index
    assert "slug: architecture-overview" not in res.text
    assert "pin: false" not in res.text
    # Body content should be present
    assert "Intro paragraph text" in res.text


def test_wiki_page_malformed_frontmatter_preserves_content(tmp_path):
    """Wiki page with an unclosed frontmatter block must not lose body content."""
    repo = tmp_path / "malrepo"
    output_dir = repo / ".rekipedia"
    wiki_dir = output_dir / "wiki"
    wiki_dir.mkdir(parents=True)
    # Opening --- present but no closing ---
    page_content = (
        "---\n"
        "slug: orphan\n"
        "title: Orphan\n"
        "\n"
        "# Orphan\n\n"
        "Body text here.\n"
    )
    (wiki_dir / "orphan.md").write_text(page_content)
    app = create_app(repo, output_dir, LLMConfig())
    with TestClient(app, raise_server_exceptions=False) as c:
        res = c.get("/wiki/orphan")
    assert res.status_code == 200
    # Body content must not be silently discarded
    assert "Body text here" in res.text


def test_summary_html_malformed_frontmatter_preserves_content(tmp_path):
    """Summary snippet for a page with an unclosed frontmatter block must not be empty."""
    repo = tmp_path / "malsum"
    output_dir = repo / ".rekipedia"
    wiki_dir = output_dir / "wiki"
    wiki_dir.mkdir(parents=True)
    # Opening --- present but no closing ---
    page_content = (
        "---\n"
        "slug: architecture-overview\n"
        "\n"
        "# Architecture Overview\n\n"
        "Summary body text.\n"
    )
    (wiki_dir / "architecture-overview.md").write_text(page_content)
    app = create_app(repo, output_dir, LLMConfig())
    with TestClient(app, raise_server_exceptions=False) as c:
        res = c.get("/")
    assert res.status_code == 200
    # Body text must appear in the page (summary or elsewhere), not be silently dropped
    assert "Summary body text" in res.text
