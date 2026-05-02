"""Integration tests for the rekipedia web server."""
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from rekipedia.models.contracts import LLMConfig
from rekipedia.server.app import create_app
from rekipedia.storage.sqlite_store import SqliteStore


@pytest.fixture
def wiki_env():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "myrepo"
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


def test_index_returns_200(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "rekipedia" in res.text


def test_index_has_wiki_links(client):
    res = client.get("/")
    assert "index" in res.text


def test_wiki_page_returns_200(client):
    res = client.get("/wiki/index")
    assert res.status_code == 200
    assert "Hello world" in res.text


def test_wiki_page_renders_markdown(client):
    res = client.get("/wiki/index")
    assert "<h1>" in res.text


def test_wiki_missing_page_returns_404(client):
    res = client.get("/wiki/nonexistent")
    assert res.status_code == 404


def test_ask_page_returns_200(client):
    res = client.get("/ask")
    assert res.status_code == 200
    assert "Ask" in res.text


def test_api_history_empty(client):
    res = client.get("/api/history")
    assert res.status_code == 200
    assert res.json() == []


def test_api_history_after_save(wiki_env):
    repo, output_dir = wiki_env
    app = create_app(repo, output_dir, LLMConfig())
    with TestClient(app, raise_server_exceptions=False) as c:
        db = output_dir / "store.db"
        with SqliteStore(db) as store:
            store.save_qa(str(repo), "What is this?", "A test repo.", "test-model")
        res = c.get("/api/history")
        assert res.status_code == 200
        data = res.json()
        assert len(data) == 1
        assert data[0]["question"] == "What is this?"
