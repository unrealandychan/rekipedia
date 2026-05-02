"""FastAPI web server for rekipedia serve."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, AsyncIterator

import markdown as md
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from rekipedia.models.contracts import LLMConfig
from rekipedia.orchestrator.run_ask import run_ask, stream_ask
from rekipedia.storage.sqlite_store import SqliteStore

_TEMPLATES_DIR = Path(__file__).parent / "templates"


def create_app(repo_root: Path, output_dir: Path, llm_config: LLMConfig) -> FastAPI:
    """Factory — returns a configured FastAPI app."""
    app = FastAPI(title="rekipedia", docs_url=None, redoc_url=None)

    templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

    # ── helpers ──────────────────────────────────────────────────────

    def _wiki_pages() -> list[dict]:
        wiki_dir = output_dir / "wiki"
        if not wiki_dir.exists():
            return []

        # Try to load nav_order from manifest.json (written by exporter)
        manifest_path = output_dir / "exports" / "manifest.json"
        nav_order: list[str] = []
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                nav_order = manifest.get("nav_order", [])
            except Exception:
                nav_order = []

        # Collect all available slugs from disk
        available = {f.stem: f for f in wiki_dir.glob("*.md")}
        if not available:
            return []

        # Build ordered list: nav_order first, then alphabetical remainder
        ordered_slugs: list[str] = []
        for slug in nav_order:
            if slug in available:
                ordered_slugs.append(slug)
        for slug in sorted(available):
            if slug not in ordered_slugs:
                ordered_slugs.append(slug)

        pages = []
        for i, slug in enumerate(ordered_slugs, start=1):
            # Extract H1 title from the markdown file for a nicer display name
            raw = available[slug].read_text(encoding="utf-8")
            title = slug.replace("-", " ").title()
            for line in raw.splitlines():
                line = line.strip()
                if line.startswith("# "):
                    title = line[2:].strip()
                    break
            pages.append({"slug": slug, "title": f"#{i} · {title}"})
        return pages

    def _project_name() -> str:
        """Extract project name from repo root directory name."""
        return repo_root.name.replace("-", " ").replace("_", " ").title()

    def _summary_html() -> str:
        """Read architecture-overview or index page for summary snippet."""
        wiki_dir = output_dir / "wiki"
        for slug in ("architecture-overview", "repository-structure", "getting-started"):
            p = wiki_dir / f"{slug}.md"
            if p.exists():
                raw = p.read_text(encoding="utf-8")
                # Take just the intro paragraph (before first ##)
                lines, snippet = raw.splitlines(), []
                for line in lines:
                    if line.startswith("## ") and snippet:
                        break
                    if not line.startswith("# "):
                        snippet.append(line)
                text = "\n".join(snippet[:12]).strip()
                if text:
                    return md.markdown(text, extensions=["fenced_code", "tables"])
        return ""

    def _file_count() -> int:
        db_path = output_dir / "store.db"
        if not db_path.exists():
            return 0
        try:
            with SqliteStore(db_path) as store:
                run_id = store.get_latest_run_id(str(repo_root))
                if run_id:
                    files = store.get_files_for_run(run_id)
                    return len(files)
        except Exception:
            pass
        return 0


    def _render_md(path: Path) -> str:
        return md.markdown(
            path.read_text(encoding="utf-8"),
            extensions=["fenced_code", "tables", "toc"],
        )

    def _ctx(request: Request, **kwargs) -> dict:
        """Build template context — always includes request for sidebar active-link logic."""
        return {"request": request, **kwargs}

    # ── routes ───────────────────────────────────────────────────────

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        pages = _wiki_pages()
        first_slug = pages[0]["slug"] if pages else None
        return templates.TemplateResponse(
            request, "index.html",
            _ctx(request, pages=pages, first_slug=first_slug,
                 project_name=_project_name(),
                 summary_html=_summary_html(),
                 file_count=_file_count()),
        )

    @app.get("/wiki/{slug}", response_class=HTMLResponse)
    async def wiki_page(request: Request, slug: str):
        path = output_dir / "wiki" / f"{slug}.md"
        if not path.exists():
            return HTMLResponse("<h1>Page not found</h1>", status_code=404)
        html = _render_md(path)
        pages = _wiki_pages()
        return templates.TemplateResponse(
            request, "wiki.html",
            _ctx(request, pages=pages, slug=slug, content=html,
                 project_name=_project_name(),
                 title=slug.replace("-", " ").title()),
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
            request, "ask.html",
            _ctx(request, pages=pages, history=history, project_name=_project_name()),
        )

    @app.get("/ask/stream", response_class=StreamingResponse)
    async def ask_stream(question: str, request: Request):
        """SSE endpoint — streams LLM tokens as Server-Sent Events."""
        async def _event_gen() -> AsyncIterator[str]:
            try:
                import asyncio  # noqa: PLC0415
                loop = asyncio.get_event_loop()
                # stream_ask is a sync generator; run in threadpool to avoid blocking
                import concurrent.futures  # noqa: PLC0415
                executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

                gen = stream_ask(
                    question=question,
                    repo_root=repo_root,
                    output_dir=output_dir,
                    llm_config=llm_config,
                )
                full_answer: list[str] = []
                for chunk in gen:
                    if await request.is_disconnected():
                        break
                    full_answer.append(chunk)
                    # Escape newlines so SSE data lines stay single-line
                    safe = chunk.replace("\n", "\\n")
                    yield f"data: {safe}\n\n"

                yield "data: [DONE]\n\n"

                # Persist full answer to history
                answer_text = "".join(full_answer)
                db_path = output_dir / "store.db"
                if db_path.exists() and answer_text:
                    with SqliteStore(db_path) as store:
                        store.save_qa(str(repo_root), question, answer_text, llm_config.model)
            except RuntimeError as exc:
                yield f"data: [ERROR] {exc}\n\n"
            except Exception as exc:
                yield f"data: [ERROR] {exc}\n\n"

        return StreamingResponse(
            _event_gen(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
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
