# Phase 5 — `rekipedia serve` Web UI Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Add a `rekipedia serve` command that starts a local web server providing a wiki viewer, search, and grounded Q&A with full history stored in SQLite.

**Architecture:**
- FastAPI (Python) server — fits existing Python stack, zero new language deps
- Jinja2 templates + vanilla JS — no build step, ships inside the Python package
- Q&A history stored in existing `store.db` via a new `qa_history` migration
- Reuses `run_ask()` pipeline from Phase 4 for grounded answers

**Tech Stack:** FastAPI, uvicorn, Jinja2, `markdown` (Python lib), existing SqliteStore + run_ask()

---

## Task 1: Add FastAPI + uvicorn to dependencies

**Objective:** Add `fastapi` and `uvicorn[standard]` to `pyproject.toml`.

**Files:**
- Modify: `pyproject.toml`

**Steps:**

1. In `pyproject.toml` `[project]` `dependencies` list, add:
   ```
   "fastapi>=0.110",
   "uvicorn[standard]>=0.29",
   "jinja2>=3.1",
   "markdown>=3.6",
   "python-multipart>=0.0.9",
   ```

2. Run: `pip install -e ".[dev]" -q`

3. Verify: `python -c "import fastapi, uvicorn, jinja2, markdown; print('OK')"`

4. Commit:
   ```bash
   git add pyproject.toml
   git commit -m "feat(serve): add fastapi/uvicorn/jinja2/markdown deps"
   ```

---

## Task 2: Add `qa_history` migration to SqliteStore

**Objective:** Create migration SQL that adds a `qa_history` table to `store.db`.

**Files:**
- Create: `src/rekipedia/storage/migrations/003_qa_history.sql`

**Steps:**

1. Create `src/rekipedia/storage/migrations/003_qa_history.sql`:
   ```sql
   CREATE TABLE IF NOT EXISTS qa_history (
       id          INTEGER PRIMARY KEY AUTOINCREMENT,
       repo_path   TEXT    NOT NULL,
       question    TEXT    NOT NULL,
       answer      TEXT    NOT NULL,
       model       TEXT    NOT NULL DEFAULT '',
       created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
   );
   ```

2. Check existing migrations to confirm naming convention:
   ```bash
   ls src/rekipedia/storage/migrations/
   ```
   Migrations are applied in alphabetical order by filename — `003_` comes after `002_`.

3. Write failing test in `tests/test_qa_history.py`:
   ```python
   import tempfile
   from pathlib import Path
   from rekipedia.storage.sqlite_store import SqliteStore

   def test_qa_history_table_exists():
       with tempfile.TemporaryDirectory() as tmp:
           db = Path(tmp) / "store.db"
           with SqliteStore(db) as store:
               # table should exist after migrations
               rows = store._conn.execute(
                   "SELECT name FROM sqlite_master WHERE type='table' AND name='qa_history'"
               ).fetchall()
               assert rows, "qa_history table missing"
   ```

4. Run: `pytest tests/test_qa_history.py -v` — expect FAIL (table doesn't exist yet)

5. After creating the SQL file, run again — expect PASS.

6. Commit:
   ```bash
   git add src/rekipedia/storage/migrations/003_qa_history.sql tests/test_qa_history.py
   git commit -m "feat(serve): add qa_history table migration"
   ```

---

## Task 3: Add `save_qa` and `get_qa_history` methods to SqliteStore

**Objective:** Expose read/write methods for Q&A history on SqliteStore.

**Files:**
- Modify: `src/rekipedia/storage/sqlite_store.py`
- Modify: `tests/test_qa_history.py`

**Steps:**

1. Add to `SqliteStore` class (after existing methods):
   ```python
   def save_qa(self, repo_path: str, question: str, answer: str, model: str = "") -> int:
       """Persist a Q&A pair. Returns the new row id."""
       cur = self._conn.execute(
           "INSERT INTO qa_history (repo_path, question, answer, model) VALUES (?, ?, ?, ?)",
           (repo_path, question, answer, model),
       )
       return cur.lastrowid

   def get_qa_history(self, repo_path: str, limit: int = 50) -> list[dict]:
       """Return recent Q&A pairs for a repo, newest first."""
       rows = self._conn.execute(
           "SELECT id, question, answer, model, created_at FROM qa_history "
           "WHERE repo_path = ? ORDER BY id DESC LIMIT ?",
           (repo_path, limit),
       ).fetchall()
       return [
           {"id": r[0], "question": r[1], "answer": r[2], "model": r[3], "created_at": r[4]}
           for r in rows
       ]
   ```

2. Add tests to `tests/test_qa_history.py`:
   ```python
   def test_save_and_retrieve_qa():
       with tempfile.TemporaryDirectory() as tmp:
           db = Path(tmp) / "store.db"
           with SqliteStore(db) as store:
               rid = store.save_qa("/my/repo", "How does auth work?", "It uses JWT.", "gpt-4o")
               assert rid == 1
               history = store.get_qa_history("/my/repo")
               assert len(history) == 1
               assert history[0]["question"] == "How does auth work?"
               assert history[0]["model"] == "gpt-4o"

   def test_qa_history_only_returns_own_repo():
       with tempfile.TemporaryDirectory() as tmp:
           db = Path(tmp) / "store.db"
           with SqliteStore(db) as store:
               store.save_qa("/repo-a", "Q1", "A1", "")
               store.save_qa("/repo-b", "Q2", "A2", "")
               assert len(store.get_qa_history("/repo-a")) == 1
               assert len(store.get_qa_history("/repo-b")) == 1
   ```

3. Run: `pytest tests/test_qa_history.py -v` — expect 3 PASS.

4. Commit:
   ```bash
   git add src/rekipedia/storage/sqlite_store.py tests/test_qa_history.py
   git commit -m "feat(serve): add save_qa / get_qa_history to SqliteStore"
   ```

---

## Task 4: Create the FastAPI app module

**Objective:** Create `src/rekipedia/server/app.py` with all routes.

**Files:**
- Create: `src/rekipedia/server/__init__.py`
- Create: `src/rekipedia/server/app.py`

**Steps:**

1. Create `src/rekipedia/server/__init__.py` (empty).

2. Create `src/rekipedia/server/app.py`:

```python
"""FastAPI web server for rekipedia serve."""
from __future__ import annotations

import os
import json
from pathlib import Path
from typing import Annotated

import markdown as md
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from rekipedia.models.contracts import LLMConfig
from rekipedia.orchestrator.run_ask import run_ask
from rekipedia.storage.sqlite_store import SqliteStore

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_STATIC_DIR = Path(__file__).parent / "static"


def create_app(repo_root: Path, output_dir: Path, llm_config: LLMConfig) -> FastAPI:
    """Factory — returns a configured FastAPI app."""
    app = FastAPI(title="rekipedia", docs_url=None, redoc_url=None)

    templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

    if _STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    # ── helpers ──────────────────────────────────────────────────────

    def _wiki_pages() -> list[dict]:
        wiki_dir = output_dir / "wiki"
        pages = []
        if wiki_dir.exists():
            for f in sorted(wiki_dir.glob("*.md")):
                pages.append({"slug": f.stem, "title": f.stem.replace("-", " ").title()})
        return pages

    def _render_md(path: Path) -> str:
        return md.markdown(
            path.read_text(encoding="utf-8"),
            extensions=["fenced_code", "tables", "toc"],
        )

    # ── routes ───────────────────────────────────────────────────────

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        pages = _wiki_pages()
        # redirect to first page if any
        first_slug = pages[0]["slug"] if pages else None
        return templates.TemplateResponse(
            "index.html",
            {"request": request, "pages": pages, "first_slug": first_slug},
        )

    @app.get("/wiki/{slug}", response_class=HTMLResponse)
    async def wiki_page(request: Request, slug: str):
        path = output_dir / "wiki" / f"{slug}.md"
        if not path.exists():
            return HTMLResponse("<h1>Page not found</h1>", status_code=404)
        html = _render_md(path)
        pages = _wiki_pages()
        return templates.TemplateResponse(
            "wiki.html",
            {"request": request, "pages": pages, "slug": slug, "content": html,
             "title": slug.replace("-", " ").title()},
        )

    @app.get("/ask", response_class=HTMLResponse)
    async def ask_page(request: Request):
        db_path = output_dir / "store.db"
        history = []
        if db_path.exists():
            with SqliteStore(db_path) as store:
                history = store.get_qa_history(str(repo_root))
        pages = _wiki_pages()
        return templates.TemplateResponse(
            "ask.html",
            {"request": request, "pages": pages, "history": history},
        )

    @app.post("/ask", response_class=JSONResponse)
    async def ask_submit(question: Annotated[str, Form()]):
        try:
            answer = run_ask(
                question=question,
                repo_root=repo_root,
                output_dir=output_dir,
                llm_config=llm_config,
            )
        except RuntimeError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=500)

        # persist to history
        db_path = output_dir / "store.db"
        if db_path.exists():
            with SqliteStore(db_path) as store:
                store.save_qa(str(repo_root), question, answer, llm_config.model)

        return JSONResponse({"answer": answer})

    @app.get("/api/history", response_class=JSONResponse)
    async def api_history():
        db_path = output_dir / "store.db"
        if not db_path.exists():
            return JSONResponse([])
        with SqliteStore(db_path) as store:
            return JSONResponse(store.get_qa_history(str(repo_root)))

    return app
```

3. Commit:
   ```bash
   git add src/rekipedia/server/
   git commit -m "feat(serve): add FastAPI app factory with wiki + ask routes"
   ```

---

## Task 5: Create HTML templates

**Objective:** Create Jinja2 templates for the three pages.

**Files:**
- Create: `src/rekipedia/server/templates/base.html`
- Create: `src/rekipedia/server/templates/index.html`
- Create: `src/rekipedia/server/templates/wiki.html`
- Create: `src/rekipedia/server/templates/ask.html`

**Steps:**

1. Create `src/rekipedia/server/templates/base.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>rekipedia{% if title %} · {{ title }}{% endif %}</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    :root {
      --bg: #0d1117; --sidebar-bg: #161b22; --border: #30363d;
      --text: #c9d1d9; --muted: #8b949e; --accent: #58a6ff;
      --code-bg: #161b22; --radius: 6px;
    }
    body { display: flex; min-height: 100vh; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: var(--bg); color: var(--text); font-size: 15px; line-height: 1.6; }
    /* Sidebar */
    .sidebar { width: 240px; min-width: 240px; background: var(--sidebar-bg); border-right: 1px solid var(--border); padding: 1.5rem 1rem; display: flex; flex-direction: column; gap: 0.25rem; position: sticky; top: 0; height: 100vh; overflow-y: auto; }
    .sidebar h1 { font-size: 1rem; font-weight: 700; color: var(--accent); margin-bottom: 1rem; letter-spacing: .5px; }
    .sidebar a { display: block; padding: 0.35rem 0.75rem; border-radius: var(--radius); color: var(--text); text-decoration: none; font-size: 0.875rem; }
    .sidebar a:hover, .sidebar a.active { background: rgba(88,166,255,.1); color: var(--accent); }
    .sidebar hr { border: none; border-top: 1px solid var(--border); margin: 0.75rem 0; }
    .sidebar .nav-label { font-size: 0.7rem; text-transform: uppercase; letter-spacing: 1px; color: var(--muted); padding: 0 0.75rem; margin-top: 0.5rem; }
    /* Main */
    .main { flex: 1; padding: 2.5rem 3rem; max-width: 900px; }
    /* Prose */
    .prose h1, .prose h2, .prose h3 { color: #e6edf3; margin: 1.5em 0 0.5em; font-weight: 600; }
    .prose h1 { font-size: 1.8em; border-bottom: 1px solid var(--border); padding-bottom: 0.3em; }
    .prose h2 { font-size: 1.3em; }
    .prose p { margin: 0.75em 0; }
    .prose a { color: var(--accent); }
    .prose code { background: var(--code-bg); border: 1px solid var(--border); padding: 0.15em 0.4em; border-radius: 4px; font-size: 0.875em; font-family: "SFMono-Regular", Consolas, monospace; }
    .prose pre { background: var(--code-bg); border: 1px solid var(--border); border-radius: var(--radius); padding: 1em; overflow-x: auto; margin: 1em 0; }
    .prose pre code { background: none; border: none; padding: 0; }
    .prose table { border-collapse: collapse; width: 100%; margin: 1em 0; }
    .prose th, .prose td { border: 1px solid var(--border); padding: 0.5em 0.75em; text-align: left; }
    .prose th { background: var(--sidebar-bg); }
    .prose ul, .prose ol { padding-left: 1.5em; margin: 0.75em 0; }
    .prose blockquote { border-left: 3px solid var(--border); margin: 1em 0; padding-left: 1em; color: var(--muted); }
    /* Ask */
    .ask-box { display: flex; gap: 0.5rem; margin-bottom: 2rem; }
    .ask-box input { flex: 1; padding: 0.6rem 1rem; background: var(--sidebar-bg); border: 1px solid var(--border); border-radius: var(--radius); color: var(--text); font-size: 0.95rem; outline: none; }
    .ask-box input:focus { border-color: var(--accent); }
    .ask-box button { padding: 0.6rem 1.25rem; background: var(--accent); color: #0d1117; border: none; border-radius: var(--radius); font-weight: 600; cursor: pointer; font-size: 0.95rem; }
    .ask-box button:disabled { opacity: 0.5; cursor: not-allowed; }
    .qa-item { border: 1px solid var(--border); border-radius: var(--radius); padding: 1rem 1.25rem; margin-bottom: 1rem; }
    .qa-item .q { font-weight: 600; color: var(--accent); margin-bottom: 0.5rem; }
    .qa-item .meta { font-size: 0.75rem; color: var(--muted); margin-top: 0.5rem; }
    .spinner { display: none; width: 20px; height: 20px; border: 2px solid var(--border); border-top-color: var(--accent); border-radius: 50%; animation: spin 0.8s linear infinite; }
    @keyframes spin { to { transform: rotate(360deg); } }
    #live-answer { display: none; }
  </style>
</head>
<body>
<nav class="sidebar">
  <h1>📖 rekipedia</h1>
  <span class="nav-label">Wiki</span>
  {% for page in pages %}
  <a href="/wiki/{{ page.slug }}"{% if slug is defined and slug == page.slug %} class="active"{% endif %}>{{ page.title }}</a>
  {% endfor %}
  {% if not pages %}
  <span style="font-size:0.8rem;color:var(--muted);padding:0 .75rem">No pages yet — run scan first</span>
  {% endif %}
  <hr>
  <a href="/ask"{% if request.url.path == '/ask' %} class="active"{% endif %}>💬 Ask</a>
</nav>
<main class="main">
{% block content %}{% endblock %}
</main>
</body>
</html>
```

2. Create `src/rekipedia/server/templates/index.html`:

```html
{% extends "base.html" %}
{% block content %}
<div class="prose">
  <h1>rekipedia</h1>
  <p>Your AI tech lead — always available, always up to date.</p>
  {% if first_slug %}
  <p><a href="/wiki/{{ first_slug }}">→ Open wiki</a> &nbsp; <a href="/ask">→ Ask a question</a></p>
  {% else %}
  <p style="color:var(--muted)">No wiki pages found. Run <code>rekipedia scan .</code> first.</p>
  {% endif %}
</div>
{% endblock %}
```

3. Create `src/rekipedia/server/templates/wiki.html`:

```html
{% extends "base.html" %}
{% block content %}
<div class="prose">{{ content | safe }}</div>
{% endblock %}
```

4. Create `src/rekipedia/server/templates/ask.html`:

```html
{% extends "base.html" %}
{% block content %}
<h1 style="color:#e6edf3;margin-bottom:1.5rem">💬 Ask</h1>
<div class="ask-box">
  <input id="q-input" type="text" placeholder="How does authentication work?" autofocus>
  <div class="spinner" id="spinner"></div>
  <button id="ask-btn" onclick="submitQuestion()">Ask</button>
</div>

<div id="live-answer" class="qa-item">
  <div class="q" id="live-q"></div>
  <div class="prose" id="live-a"></div>
</div>

<div id="history">
{% for item in history %}
<div class="qa-item">
  <div class="q">{{ item.question }}</div>
  <div class="prose">{{ item.answer | safe }}</div>
  <div class="meta">{{ item.model }} · {{ item.created_at }}</div>
</div>
{% endfor %}
</div>

<script>
// Simple markdown → HTML (bold, italic, code, headings, line breaks)
function simpleMarkdown(text) {
  return text
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/```([\s\S]*?)```/g, '<pre><code>$1</code></pre>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/^### (.+)$/gm, '<h3>$1</h3>')
    .replace(/^## (.+)$/gm, '<h2>$1</h2>')
    .replace(/^# (.+)$/gm, '<h1>$1</h1>')
    .replace(/\n/g, '<br>');
}

async function submitQuestion() {
  const input = document.getElementById('q-input');
  const q = input.value.trim();
  if (!q) return;

  const btn = document.getElementById('ask-btn');
  const spinner = document.getElementById('spinner');
  const liveBox = document.getElementById('live-answer');
  btn.disabled = true;
  spinner.style.display = 'block';
  liveBox.style.display = 'block';
  document.getElementById('live-q').textContent = q;
  document.getElementById('live-a').innerHTML = '<em style="color:var(--muted)">Thinking…</em>';

  const form = new FormData();
  form.append('question', q);

  try {
    const res = await fetch('/ask', { method: 'POST', body: form });
    const data = await res.json();
    if (data.error) {
      document.getElementById('live-a').innerHTML = '<span style="color:#f85149">' + data.error + '</span>';
    } else {
      document.getElementById('live-a').innerHTML = simpleMarkdown(data.answer);
      // prepend to history
      const hist = document.getElementById('history');
      const div = document.createElement('div');
      div.className = 'qa-item';
      div.innerHTML = '<div class="q">' + q + '</div><div class="prose">' + simpleMarkdown(data.answer) + '</div>';
      hist.prepend(div);
      liveBox.style.display = 'none';
      input.value = '';
    }
  } catch(e) {
    document.getElementById('live-a').innerHTML = '<span style="color:#f85149">Request failed</span>';
  }

  btn.disabled = false;
  spinner.style.display = 'none';
}

document.getElementById('q-input').addEventListener('keydown', e => {
  if (e.key === 'Enter') submitQuestion();
});
</script>
{% endblock %}
```

5. Commit:
   ```bash
   git add src/rekipedia/server/templates/
   git commit -m "feat(serve): add Jinja2 HTML templates (base, index, wiki, ask)"
   ```

---

## Task 6: Add `serve` CLI command

**Objective:** Wire `rekipedia serve` into the CLI.

**Files:**
- Create: `src/rekipedia/cli/serve.py`
- Modify: `src/rekipedia/cli/__init__.py`

**Steps:**

1. Create `src/rekipedia/cli/serve.py`:

```python
"""`rekipedia serve` command — local web UI."""
from __future__ import annotations

import os
import webbrowser
from pathlib import Path

import click
import yaml

from rekipedia.models.contracts import LLMConfig


@click.command("serve")
@click.option(
    "--repo",
    default=".",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Repository root (default: current directory).",
)
@click.option("--port", default=7070, show_default=True, help="Port to listen on.")
@click.option("--host", default="127.0.0.1", show_default=True, help="Host to bind to.")
@click.option("--output-dir", default=None, type=click.Path(path_type=Path))
@click.option("--model", default=None, envvar="REKIPEDIA_MODEL")
@click.option("--open/--no-open", "open_browser", default=True, help="Auto-open browser.")
def serve_cmd(repo: Path, port: int, host: str, output_dir: Path | None, model: str | None, open_browser: bool) -> None:
    """Start the rekipedia web UI.

    \b
    Examples:
        rekipedia serve
        rekipedia serve --port 8080
        rekipedia serve --repo ./my-project --no-open
    """
    import uvicorn  # noqa: PLC0415 — lazy import keeps startup fast

    repo = repo.resolve()
    output_dir = (output_dir or repo / ".rekipedia").resolve()

    cfg_path = repo / ".rekipedia" / "config.yml"
    cfg = yaml.safe_load(cfg_path.read_text()) if cfg_path.exists() else {}
    llm_raw = cfg.get("llm", {})
    llm_config = LLMConfig(
        model=os.environ.get("REKIPEDIA_MODEL") or model or llm_raw.get("model", "ollama/llama4"),
        api_key=os.environ.get("REKIPEDIA_API_KEY") or llm_raw.get("api_key", ""),
        base_url=os.environ.get("REKIPEDIA_BASE_URL") or llm_raw.get("base_url", ""),
        temperature=llm_raw.get("temperature", 0.2),
    )

    from rekipedia.server.app import create_app  # noqa: PLC0415

    app = create_app(repo_root=repo, output_dir=output_dir, llm_config=llm_config)

    url = f"http://{host}:{port}"
    click.echo(f"  rekipedia serve → {url}")
    click.echo(f"  repo       : {repo}")
    click.echo(f"  output-dir : {output_dir}")
    click.echo(f"  model      : {llm_config.model}")

    if open_browser:
        import threading  # noqa: PLC0415
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    uvicorn.run(app, host=host, port=port, log_level="warning")
```

2. Open `src/rekipedia/cli/__init__.py`. Find the `main` click group and add:
   ```python
   from rekipedia.cli.serve import serve_cmd
   # and inside main group:
   main.add_command(serve_cmd)
   ```

3. Verify: `python -m rekipedia serve --help` shows serve options.

4. Commit:
   ```bash
   git add src/rekipedia/cli/serve.py src/rekipedia/cli/__init__.py
   git commit -m "feat(serve): add rekipedia serve CLI command"
   ```

---

## Task 7: Write integration test for the server routes

**Objective:** Test all routes return correct status codes using FastAPI's TestClient.

**Files:**
- Create: `tests/test_server.py`

**Steps:**

1. Create `tests/test_server.py`:

```python
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
        # seed a wiki page
        (wiki_dir / "index.md").write_text("# Index\n\nHello world.")
        # seed store.db with a scan run
        db = output_dir / "store.db"
        with SqliteStore(db) as store:
            store.upsert_run("run-1", str(repo))
            store.mark_run_complete("run-1")
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


def test_wiki_page_returns_200(client):
    res = client.get("/wiki/index")
    assert res.status_code == 200
    assert "Hello world" in res.text


def test_wiki_missing_page_returns_404(client):
    res = client.get("/wiki/nonexistent")
    assert res.status_code == 404


def test_ask_page_returns_200(client):
    res = client.get("/ask")
    assert res.status_code == 200


def test_api_history_empty(client):
    res = client.get("/api/history")
    assert res.status_code == 200
    assert res.json() == []
```

2. Run: `pytest tests/test_server.py -v`
   - `test_index_returns_200` — PASS
   - `test_wiki_page_returns_200` — PASS
   - `test_wiki_missing_page_returns_404` — PASS
   - `test_ask_page_returns_200` — PASS
   - `test_api_history_empty` — PASS

3. Commit:
   ```bash
   git add tests/test_server.py
   git commit -m "test(serve): add integration tests for web routes"
   ```

---

## Task 8: Push and verify

**Objective:** Run all tests, push to GitHub.

**Steps:**

1. Run full test suite: `pytest -v`
   Expected: all existing tests + new serve tests pass.

2. Check serve starts:
   ```bash
   timeout 3 python -m rekipedia serve --no-open --port 7070 || true
   ```

3. Push:
   ```bash
   git push origin main
   ```

4. Done ✅
