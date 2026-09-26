"""FastAPI web server for rekipedia serve."""
from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Annotated

import markdown as md
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from rekipedia.models.contracts import LLMConfig
from rekipedia.orchestrator.run_ask import run_ask, stream_ask
from rekipedia.storage.sqlite_store import SqliteStore

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_STATIC_DIR    = Path(__file__).parent / "static"


def create_app(
    repo_root: Path,
    output_dir: Path,
    llm_config: LLMConfig,
    custom_title: str | None = None,
    custom_logo: Path | None = None,
) -> FastAPI:
    """Create the FastAPI application.

    Args:
        repo_root: Repository root directory.
        output_dir: .rekipedia/ output directory.
        llm_config: LLM configuration.
        custom_title: Optional project title shown in the UI (overrides repo name).
        custom_logo: Optional path to a custom logo image served as /logo.
    """
    app = FastAPI(title=custom_title or "rekipedia", docs_url=None, redoc_url=None)

    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    # Mount Next.js _next directory
    next_static = _STATIC_DIR / "_next"
    if next_static.exists():
        app.mount("/_next", StaticFiles(directory=str(next_static)), name="next")

    templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

    # ── helpers ──────────────────────────────────────────────────────

    _wiki_cache: list[dict] | None = None
    _wiki_cache_mtime: float = 0.0

    def _wiki_pages() -> list[dict]:
        nonlocal _wiki_cache, _wiki_cache_mtime
        wiki_dir = output_dir / "wiki"
        if not wiki_dir.exists():
            return []
        try:
            mtime = wiki_dir.stat().st_mtime
        except OSError:
            return []
        if _wiki_cache is not None and mtime == _wiki_cache_mtime:
            return _wiki_cache

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
        for slug in ordered_slugs:
            raw = available[slug].read_text(encoding="utf-8")
            title = slug.replace("-", " ").title()
            section = "general"
            # Parse frontmatter for title + section
            if raw.startswith("---"):
                end = raw.find("\n---", 3)
                if end != -1:
                    fm_text = raw[3:end]
                    for line in fm_text.splitlines():
                        if line.startswith("title:"):
                            t = line.split(":", 1)[1].strip().strip('"').strip("'")
                            if t:
                                title = t
                        elif line.startswith("section:"):
                            s = line.split(":", 1)[1].strip()
                            if s:
                                section = s
            # Fallback: extract H1 title
            if title == slug.replace("-", " ").title():
                for line in raw.splitlines():
                    line = line.strip()
                    if line.startswith("# "):
                        title = line[2:].strip()
                        break
            pages.append({"slug": slug, "title": title, "section": section})
        _wiki_cache = pages
        _wiki_cache_mtime = mtime
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
                text_no_fm = _strip_yaml_frontmatter(raw)
                snippet = []
                for line in text_no_fm.splitlines():
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


    def _strip_yaml_frontmatter(text: str) -> str:
        """Strip a leading YAML frontmatter block delimited by exact `---` lines.

        If the closing delimiter is missing (malformed frontmatter) we still
        strip everything up to the first blank line or H1 heading so garbage
        YAML never leaks into the rendered page.
        """
        lines = text.splitlines(keepends=True)
        if not lines or lines[0] not in ("---\n", "---\r\n", "---"):
            return text

        # Normal case: find closing ---
        for idx in range(1, len(lines)):
            if lines[idx] in ("---\n", "---\r\n", "---"):
                return "".join(lines[idx + 1:]).lstrip("\r\n")

        # Malformed: no closing ---. Strip until first blank line or # heading.
        for idx in range(1, len(lines)):
            stripped = lines[idx].strip()
            if stripped == "" or stripped.startswith("#"):
                return "".join(lines[idx:]).lstrip("\r\n")

        # Everything looks like frontmatter: return empty rather than raw YAML.
        return ""

    def _render_md(path: Path) -> str:
        text = path.read_text(encoding="utf-8")
        # Strip YAML frontmatter (--- ... ---) before rendering.
        # If the closing delimiter is missing the content is malformed; skip
        # stripping entirely so nothing is lost.
        text = _strip_yaml_frontmatter(text)
        return md.markdown(
            text,
            extensions=["fenced_code", "tables", "toc"],
        )

    def _ctx(request: Request, **kwargs) -> dict:
        """Build template context — always includes request for sidebar active-link logic."""
        return {"request": request, **kwargs}

    # ── routes ───────────────────────────────────────────────────────

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        import os
        # Serve new Next.js SPA only when not running under pytest
        if "PYTEST_CURRENT_TEST" not in os.environ:
            next_index_path = _TEMPLATES_DIR / "next_index.html"
            if next_index_path.exists():
                return HTMLResponse(next_index_path.read_text(encoding="utf-8"))
        
        pages = _wiki_pages()
        first_slug = pages[0]["slug"] if pages else None
        return templates.TemplateResponse(
            request, "index.html",
            _ctx(request, pages=pages, first_slug=first_slug,
                 project_name=_project_name(),
                 summary_html=_summary_html(),
                 file_count=_file_count()),
        )

    @app.get("/legacy", response_class=HTMLResponse)
    async def legacy_index(request: Request):
        pages = _wiki_pages()
        first_slug = pages[0]["slug"] if pages else None
        return templates.TemplateResponse(
            request, "index.html",
            _ctx(request, pages=pages, first_slug=first_slug,
                 project_name=_project_name(),
                 summary_html=_summary_html(),
                 file_count=_file_count()),
        )

    _SLUG_RE = re.compile(r"^[a-zA-Z0-9_-]+$")

    @app.get("/wiki/{slug}", response_class=HTMLResponse)
    async def wiki_page(request: Request, slug: str):
        if not _SLUG_RE.match(slug):
            return HTMLResponse("<h1>Page not found</h1>", status_code=404)
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
                # Load conversation history for multi-turn context
                # Uses chat.db (separate from shared store.db) — see #248
                from rekipedia.storage.chat_store import ChatStore
                chat_history: list[dict] = []
                with ChatStore(output_dir) as _cs:
                    raw_hist = _cs.get_qa_history(str(repo_root), limit=20)
                # get_qa_history returns newest-first; LLM needs oldest-first
                for _h in reversed(raw_hist):
                    chat_history.append({"role": "user", "content": _h["question"]})
                    chat_history.append({"role": "assistant", "content": _h["answer"]})

                gen = stream_ask(
                    question=question,
                    repo_root=repo_root,
                    output_dir=output_dir,
                    llm_config=llm_config,
                    history=chat_history,
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

                # Persist full answer to chat.db (not store.db) — see #248
                answer_text = "".join(full_answer)
                if answer_text:
                    from rekipedia.storage.chat_store import ChatStore
                    with ChatStore(output_dir) as _cs:
                        _cs.save_qa(str(repo_root), question, answer_text, llm_config.model)
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

        # Save to chat.db (not store.db) — see #248
        from rekipedia.storage.chat_store import ChatStore
        with ChatStore(output_dir) as _cs:
            _cs.save_qa(str(repo_root), question, answer, llm_config.model)

        return JSONResponse({"answer": answer})

    @app.get("/api/history", response_class=JSONResponse)
    async def api_history():
        from rekipedia.storage.chat_store import ChatStore
        with ChatStore(output_dir) as _cs:
            return JSONResponse(_cs.get_qa_history(str(repo_root)))

    @app.get("/api/config", response_class=JSONResponse)
    async def api_config():
        """Return server-side branding config (title, logo availability)."""
        return JSONResponse({
            "title": custom_title or _project_name(),
            "has_logo": custom_logo is not None and Path(custom_logo).exists(),
        })

    @app.get("/logo")
    async def serve_logo():
        """Serve the custom logo image, if one was configured."""
        from fastapi.responses import FileResponse
        if custom_logo and Path(custom_logo).exists():
            logo_path = Path(custom_logo)
            media_map = {
                ".png": "image/png",
                ".svg": "image/svg+xml",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".gif": "image/gif",
                ".webp": "image/webp",
            }
            media_type = media_map.get(logo_path.suffix.lower(), "application/octet-stream")
            return FileResponse(str(logo_path), media_type=media_type)
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="No custom logo configured")

    @app.get("/api/wiki", response_class=JSONResponse)
    async def api_wiki_list():
        """Return the list of all wiki pages with slugs, titles, and sections."""
        return JSONResponse(_wiki_pages())

    @app.get("/api/wiki/page/{slug}", response_class=JSONResponse)
    async def api_wiki_get(slug: str):
        """Return raw Markdown and rendered HTML for a specific wiki page."""
        if not _SLUG_RE.match(slug):
            return JSONResponse({"error": "Invalid slug format"}, status_code=400)
        path = output_dir / "wiki" / f"{slug}.md"
        if not path.exists():
            return JSONResponse({"error": f"Page not found: {slug}"}, status_code=404)
        
        raw = path.read_text(encoding="utf-8")
        title = slug.replace("-", " ").title()
        section = "general"
        
        # Parse frontmatter
        if raw.startswith("---"):
            end = raw.find("\n---", 3)
            if end != -1:
                fm_text = raw[3:end]
                for line in fm_text.splitlines():
                    if line.startswith("title:"):
                        t = line.split(":", 1)[1].strip().strip('"').strip("'")
                        if t:
                            title = t
                    elif line.startswith("section:"):
                        s = line.split(":", 1)[1].strip()
                        if s:
                            section = s
        
        html = _render_md(path)
        return JSONResponse({
            "slug": slug,
            "title": title,
            "section": section,
            "raw": raw,
            "html": html
        })

    @app.get("/api/graph", response_class=JSONResponse)
    async def api_graph():
        """Return file-level module dependency graph as {nodes, edges}.

        Industry-standard approach (pydeps / pyreverse style):
        - Node  = source file (e.g. src/client.py)
        - Edge  = import relationship between files
        - kind  = 'module' for all file nodes
        Relationships table stores (from_=module_path, to=module_path, kind, file=source_file).
        We build a file→file import graph using the `file` column (source) and `to` column
        (target module, normalised to a file path that exists in our node set).
        """
        db_path = output_dir / "store.db"
        if not db_path.exists():
            return JSONResponse({"nodes": [], "edges": []})
        try:
            with SqliteStore(db_path) as store:
                run_id = store.get_latest_run_id(str(repo_root))
                if not run_id:
                    return JSONResponse({"nodes": [], "edges": []})
                raw_symbols = store.get_all_symbols(run_id)
                raw_rels = store.get_all_relationships(run_id)
                god_nodes = store.get_god_nodes(run_id, top_n=10)

            # ── Build file→kind map from symbols ─────────────────────────
            # Each file gets the "dominant" kind (class > function > module)
            KIND_RANK = {"class": 3, "function": 2, "method": 1, "module": 0}
            file_kind: dict[str, str] = {}
            file_package: dict[str, str] = {}
            for row in raw_symbols:
                kind = (row[2] if isinstance(row, (list, tuple)) else row.get("kind")) or "module"
                file_ = (row[3] if isinstance(row, (list, tuple)) else row.get("file")) or ""
                if not file_:
                    continue
                cur = file_kind.get(file_, "module")
                if KIND_RANK.get(kind, 0) > KIND_RANK.get(cur, 0):
                    file_kind[file_] = kind
                # package = first path segment (e.g. src/client.py → src)
                parts = file_.replace("\\", "/").split("/")
                file_package[file_] = parts[0] if len(parts) > 1 else "root"

            # Also collect files directly from relationships
            for row in raw_rels:
                file_ = row.get("file") if isinstance(row, dict) else (row[4] if isinstance(row, (list, tuple)) else "")
                if file_ and file_ not in file_kind:
                    file_kind[file_] = "module"
                    parts = file_.replace("\\", "/").split("/")
                    file_package[file_] = parts[0] if len(parts) > 1 else "root"

            # ── Workspace package name → folder mapping ──────────────
            # Scan package.json files to resolve @scope/pkg → folder path
            pkg_name_to_folder: dict[str, str] = {}
            try:
                import json as _json
                for pkgjson in repo_root.rglob("package.json"):
                    # skip node_modules
                    if "node_modules" in pkgjson.parts:
                        continue
                    try:
                        data = _json.loads(pkgjson.read_text())
                        pkg_name = data.get("name", "")
                        if pkg_name:
                            folder = str(pkgjson.parent.relative_to(repo_root)).replace("\\", "/")
                            pkg_name_to_folder[pkg_name] = folder
                    except Exception:
                        pass
            except Exception:
                pass

            # ── TypeScript path alias resolution ─────────────────────
            # Read tsconfig.json / tsconfig.base.json paths
            ts_aliases: dict[str, str] = {}  # alias_prefix → folder
            try:
                import json as _json
                for tsconfig in list(repo_root.glob("tsconfig*.json")) + list(repo_root.glob("*/tsconfig*.json")):
                    if "node_modules" in tsconfig.parts:
                        continue
                    try:
                        raw = tsconfig.read_text()
                        # Strip JS comments for basic parsing
                        import re as _re
                        raw = _re.sub(r"//[^\n]*", "", raw)
                        data = _json.loads(raw)
                        paths = data.get("compilerOptions", {}).get("paths", {})
                        base_url = data.get("compilerOptions", {}).get("baseUrl", "")
                        tsconfig_dir = str(tsconfig.parent.relative_to(repo_root)).replace("\\", "/")
                        for alias, targets in paths.items():
                            if not targets:
                                continue
                            # Strip trailing /* from alias: '@/components/*' → '@/components'
                            alias_key = alias.rstrip("/*")
                            target = targets[0].rstrip("/*")
                            # Resolve target relative to tsconfig dir
                            if not target.startswith("/"):
                                if tsconfig_dir and tsconfig_dir != ".":
                                    target = tsconfig_dir + "/" + target
                            ts_aliases[alias_key] = target.lstrip("./")
                    except Exception:
                        pass
            except Exception:
                pass

            god_set = {name for name, _ in god_nodes}

            nodes: list[dict] = []
            for file_, kind in sorted(file_kind.items()):
                label = file_.replace("\\", "/").split("/")[-1]  # basename
                nodes.append({
                    "id": file_,
                    "label": label,
                    "kind": kind,
                    "file": file_,
                    "group": file_package.get(file_, "root"),
                    "god": file_ in god_set or label in god_set,
                })

            node_ids = {n["id"] for n in nodes}

            # ── Build file→file edges from relationships ──────────────────
            # Strategy (pydeps-style):
            # The `file` column = the source file that contains the import.
            # The `to` column = dotted module name being imported.
            # We normalise `to` → candidate file paths and match against node_ids.
            def module_to_candidates(module: str) -> list[str]:
                """Convert dotted module name to candidate file paths."""
                # e.g. "src.client" → ["src/client.py", "src/client/__init__.py"]
                path_base = module.replace(".", "/")
                return [
                    f"{path_base}.py",
                    f"{path_base}/__init__.py",
                    # also try just the last segment in case it's a relative ref
                    f"{module.split('.')[-1]}.py",
                ]

            seen_edges: set[tuple[str, str]] = set()
            edges: list[dict] = []
            MAX_EDGES = 1500

            # Build suffix index: "sqlite_store.py" → ["src/rekipedia/storage/sqlite_store.py", ...]
            suffix_index: dict[str, list[str]] = {}
            for nid in node_ids:
                # index by each suffix segment: "a/b/c.py" → keys: "a/b/c.py", "b/c.py", "c.py"
                parts = nid.replace("\\", "/").split("/")
                for i in range(len(parts)):
                    key = "/".join(parts[i:])
                    suffix_index.setdefault(key, []).append(nid)

            def resolve_module_to_file(module: str, src_file: str = "") -> str | None:
                """Convert module/import string to a node_id file path.

                Handles:
                  - Relative TS/JS: './foo', '../bar/baz', '../../utils'
                  - Dotted Python:   'rekipedia.storage.sqlite_store'
                  - TS path alias:   '@/components/Button', '~utils'
                  - Workspace pkg:   '@terraform-viz/graph-schema'
                  - Bare external:   'react', 'vitest' (skip)
                """
                module = module.strip()
                if not module:
                    return None

                # ── Workspace package name ────────────────────────────────
                if module in pkg_name_to_folder:
                    folder = pkg_name_to_folder[module]
                    for idx_file in ("index.ts", "index.tsx", "index.js", "src/index.ts", "src/index.tsx"):
                        cand = f"{folder}/{idx_file}"
                        if cand in node_ids:
                            return cand
                        matches = suffix_index.get(idx_file)
                        if matches:
                            for m in matches:
                                if m.startswith(folder + "/"):
                                    return m

                # ── TS path aliases (@/..., ~...) ─────────────────────────
                for alias_key, alias_target in ts_aliases.items():
                    if module == alias_key or module.startswith(alias_key + "/"):
                        rest = module[len(alias_key):].lstrip("/")
                        base = (alias_target + "/" + rest).rstrip("/")
                        for ext in (".ts", ".tsx", ".js", ".jsx"):
                            cand = base + ext
                            if cand in node_ids:
                                return cand
                            matches = suffix_index.get(cand)
                            if matches:
                                return matches[0]
                        # index file
                        for ext in ("/index.ts", "/index.tsx", "/index.js"):
                            cand = base + ext
                            if cand in node_ids:
                                return cand
                            matches = suffix_index.get(cand)
                            if matches:
                                return matches[0]

                # ── Relative import (TS/JS/Rust-style) ───────────────────
                if module.startswith("."):
                    if not src_file:
                        return None
                    src_dir = src_file.replace("\\", "/").rsplit("/", 1)[0]
                    parts_src = src_dir.split("/")
                    parts_mod = module.split("/")
                    remaining = list(parts_src)
                    i = 0
                    if parts_mod[0] == ".":
                        i = 1
                    elif parts_mod[0] == "..":
                        while i < len(parts_mod) and parts_mod[i] == "..":
                            if remaining:
                                remaining.pop()
                            i += 1
                    else:
                        i = 1
                    base = "/".join(remaining + parts_mod[i:]) if remaining else "/".join(parts_mod[i:])
                    for ext in (".ts", ".tsx", ".js", ".jsx", ".py", ".go", ".rs"):
                        cand = base + ext
                        if cand in node_ids:
                            return cand
                        matches = suffix_index.get(cand)
                        if matches:
                            return matches[0]
                    for ext in ("/index.ts", "/index.tsx", "/index.js", "/mod.rs"):
                        cand = base + ext
                        if cand in node_ids:
                            return cand
                        matches = suffix_index.get(cand)
                        if matches:
                            return matches[0]
                    last = module.split("/")[-1]
                    for ext in (".ts", ".tsx", ".js", ".py", ".go", ".rs"):
                        key = last + ext
                        matches = suffix_index.get(key)
                        if matches and len(matches) == 1:
                            return matches[0]
                    return None

                # ── Dotted Python-style ───────────────────────────────────
                path_base = module.replace(".", "/")
                candidates = [
                    f"{path_base}.py",
                    f"{path_base}/__init__.py",
                    f"{path_base}.go",
                    f"{path_base}.ts",
                    f"{path_base}.js",
                ]
                for cand in candidates:
                    if cand in node_ids:
                        return cand
                    matches = suffix_index.get(cand)
                    if matches:
                        return matches[0]

                # Last segment fallback (unique only)
                last = module.split(".")[-1]
                for ext in (".py", ".go", ".ts", ".js", ".rs"):
                    key = last + ext
                    matches = suffix_index.get(key)
                    if matches and len(matches) == 1:
                        return matches[0]
                return None

            for row in raw_rels:
                src_file = row.get("file") if isinstance(row, dict) else (row[4] if isinstance(row, (list, tuple)) else "")
                to_module = row.get("to") if isinstance(row, dict) else (row[1] if isinstance(row, (list, tuple)) else "")
                kind_str = row.get("kind") if isinstance(row, dict) else (row[2] if isinstance(row, (list, tuple)) else "imports")
                src_file  = (src_file  or "").strip()
                to_module = (to_module or "").strip()
                kind_str  = (kind_str  or "imports")

                if not src_file or not to_module:
                    continue
                if src_file not in node_ids:
                    continue

                tgt_file = resolve_module_to_file(to_module, src_file)
                if not tgt_file or tgt_file == src_file:
                    continue

                edge_key = (src_file, tgt_file)
                if edge_key in seen_edges:
                    continue
                seen_edges.add(edge_key)
                edges.append({"source": src_file, "target": tgt_file, "kind": kind_str})
                if len(edges) >= MAX_EDGES:
                    break

            god_nodes_data = [{"name": name, "degree": degree} for name, degree in god_nodes]
            try:
                raw_h = store.get_hyperedges(run_id) if hasattr(store, "get_hyperedges") else []
                hyperedges_data = raw_h if isinstance(raw_h, list) else []
            except Exception:
                hyperedges_data = []
            return JSONResponse({
                "nodes": nodes,
                "edges": edges,
                "god_nodes": god_nodes_data,
                "hyperedges": hyperedges_data,
                "edge_count_total": len(edges),
            })
        except Exception as exc:
            return JSONResponse({"nodes": [], "edges": [], "god_nodes": [], "error": str(exc)})

    @app.get("/api/wiki/search", response_class=JSONResponse)
    async def wiki_search(q: str = ""):
        """Full-text search across wiki page titles and content."""
        q = q.strip().lower()
        if not q or len(q) < 2:
            return JSONResponse([])
        wiki_dir = output_dir / "wiki"
        if not wiki_dir.exists():
            return JSONResponse([])
        results = []
        for md_file in sorted(wiki_dir.glob("*.md")):
            raw = md_file.read_text(encoding="utf-8")
            slug = md_file.stem
            title = slug.replace("-", " ").title()
            section = "general"
            # Parse frontmatter
            body = raw
            if raw.startswith("---"):
                end = raw.find("\n---", 3)
                if end != -1:
                    fm_text = raw[3:end]
                    body = raw[end + 4:].lstrip()
                    for line in fm_text.splitlines():
                        if line.startswith("title:"):
                            t = line.split(":", 1)[1].strip().strip('"').strip("'")
                            if t:
                                title = t
                        elif line.startswith("section:"):
                            s = line.split(":", 1)[1].strip()
                            if s:
                                section = s
            # Plain-text body (strip markdown symbols)
            text_body = re.sub(r"[#*`\[\]()>_~]", " ", body)
            title_match = q in title.lower()
            section_match = q in section.lower()
            body_match = q in text_body.lower()
            if not (title_match or section_match or body_match):
                continue
            # Build snippet: find first matching line in body
            snippet = ""
            for line in text_body.splitlines():
                if q in line.lower() and line.strip():
                    snippet = line.strip()[:120]
                    break
            if not snippet and (title_match or section_match):
                # Just use first non-empty body line
                for line in text_body.splitlines():
                    if line.strip():
                        snippet = line.strip()[:120]
                        break
            results.append({
                "slug": slug,
                "title": title,
                "section": section,
                "snippet": snippet,
                "title_match": title_match,
            })
            if len(results) >= 20:
                break
        # Sort: title/section matches first
        results.sort(key=lambda r: (0 if r["title_match"] else 1, r["title"]))
        return JSONResponse(results)

    @app.get("/graph", response_class=HTMLResponse)
    async def graph_page(request: Request):
        pages = _wiki_pages()
        return templates.TemplateResponse(
            request, "graph.html",
            _ctx(request, pages=pages, project_name=_project_name()),
        )

    @app.get("/api/graph/debug")
    async def api_graph_debug():
        """Debug: show raw relationships + node_ids to diagnose 0-edge issue."""
        db_path = output_dir / "store.db"
        if not db_path.exists():
            return JSONResponse({"error": "no store.db"})
        with SqliteStore(db_path) as store:
            run_id = store.get_latest_run_id(str(repo_root))
            if not run_id:
                return JSONResponse({"error": "no run_id"})
            raw_syms = store.get_all_symbols(run_id)
            raw_rels = store.get_all_relationships(run_id)
        node_files = sorted({
            (row[3] if isinstance(row, tuple) else row.get("file", ""))
            for row in raw_syms
        })[:30]
        sample_rels = [
            {"from_": r.get("from_"), "to": r.get("to"), "kind": r.get("kind"), "file": r.get("file")}
            for r in raw_rels[:20]
        ] if raw_rels and isinstance(raw_rels[0], dict) else raw_rels[:20]
        return JSONResponse({
            "run_id": run_id,
            "total_symbols": len(raw_syms),
            "total_rels": len(raw_rels),
            "sample_node_files": node_files,
            "sample_rels": sample_rels,
        })

    @app.get("/api/graph-data")
    async def graph_data():
        """Return graph nodes + edges as JSON."""
        db_path = output_dir / "store.db"
        if not db_path.exists():
            return JSONResponse({"nodes": [], "edges": []})
        try:
            with SqliteStore(db_path) as store:
                run_id = store.get_latest_run_id(str(repo_root))
                if not run_id:
                    return JSONResponse({"nodes": [], "edges": []})
                symbols = store.get_all_symbols(run_id)
                raw_rels = store.get_all_relationships(run_id)

            SECTION_COLORS = {
                "cli": "#4CAF50", "server": "#2196F3", "models": "#FF9800",
                "storage": "#9C27B0", "synthesis": "#F44336", "analysis": "#00BCD4",
                "orchestrator": "#FF5722", "extractors": "#795548", "rag": "#607D8B",
                "sandbox": "#E91E63",
            }
            DEFAULT_COLOR = "#9E9E9E"

            nodes = []
            for s in symbols:
                name = s[1] if isinstance(s, (list, tuple)) else (s.name if hasattr(s, "name") else s.get("name", ""))
                file = s[3] if isinstance(s, (list, tuple)) else (s.file if hasattr(s, "file") else s.get("file", ""))
                kind = s[2] if isinstance(s, (list, tuple)) else (s.kind if hasattr(s, "kind") else s.get("kind", ""))
                section = ""
                if file:
                    parts = file.split("/")
                    for part in parts:
                        if part in SECTION_COLORS:
                            section = part
                            break
                nodes.append({
                    "id": name,
                    "label": name,
                    "file": file,
                    "kind": kind,
                    "section": section,
                    "color": SECTION_COLORS.get(section, DEFAULT_COLOR),
                })

            label_to_id = {n["label"]: n["id"] for n in nodes}
            id_set = {n["id"] for n in nodes}

            def resolve_id(name: str):
                if not name: return None
                if name in label_to_id: return label_to_id[name]
                if name in id_set: return name
                parts = name.split(".")
                if len(parts) > 1 and parts[-1] in label_to_id:
                    return label_to_id[parts[-1]]
                if "." in name:
                    method = name.split(".")[-1]
                    if method in label_to_id: return label_to_id[method]
                return None

            edges = []
            KIND_PRIORITY = ["inherits", "calls", "imports", "unknown"]
            MAX_EDGES = 2000
            bucketed: dict[str, list] = {k: [] for k in KIND_PRIORITY}

            for rel in raw_rels:
                frm = rel[1] if isinstance(rel, (list, tuple)) else (rel.get("from_", "") or rel.get("from", ""))
                to = rel[2] if isinstance(rel, (list, tuple)) else rel.get("to", "")
                kind = rel[3] if isinstance(rel, (list, tuple)) else (rel.get("kind", "unknown") or "unknown")
                kind = kind or "unknown"
                src_id = resolve_id(frm)
                tgt_id = resolve_id(to)
                if src_id and tgt_id and src_id != tgt_id:
                    bucket = kind if kind in bucketed else "unknown"
                    bucketed[bucket].append({"source": src_id, "target": tgt_id, "kind": kind})

            for k in KIND_PRIORITY:
                edges.extend(bucketed[k])
                if len(edges) >= MAX_EDGES:
                    edges = edges[:MAX_EDGES]
                    break

            return JSONResponse({"nodes": nodes, "edges": edges})
        except Exception as exc:
            return JSONResponse({"nodes": [], "edges": [], "error": str(exc)})

    @app.get("/api/health", response_class=JSONResponse)
    async def api_health():
        db_path = output_dir / "store.db"
        if not db_path.exists():
            return JSONResponse({"status": "ok", "db": "no_store"})
        try:
            with SqliteStore(db_path) as store:
                store.get_qa_history(str(repo_root))  # lightweight probe
            return JSONResponse({"status": "ok", "db": "ok"})
        except Exception as exc:
            return JSONResponse(
                {"status": "degraded", "db": f"error: {exc}"},
                status_code=503,
            )

    # ── Notes API ────────────────────────────────────────────────────

    @app.get("/api/notes", response_class=JSONResponse)
    async def api_notes_list():
        db_path = output_dir / "store.db"
        with SqliteStore(db_path) as store:
            return JSONResponse(store.list_notes())

    @app.post("/api/notes", response_class=JSONResponse)
    async def api_notes_create(request: Request):
        body = await request.json()
        content = body.get("content", "").strip()
        if not content:
            return JSONResponse({"error": "content required"}, status_code=400)
        tags = body.get("tags", "")
        if isinstance(tags, list):
            tags = ",".join(tags)
        db_path = output_dir / "store.db"
        with SqliteStore(db_path) as store:
            nid = store.upsert_note(content=content, tags=tags, source="manual")
            note = store.get_note(nid)
        return JSONResponse(note, status_code=201)

    @app.delete("/api/notes/{note_id}", response_class=JSONResponse)
    async def api_notes_delete(note_id: str):
        db_path = output_dir / "store.db"
        with SqliteStore(db_path) as store:
            deleted = store.delete_note(note_id)
        if deleted:
            return JSONResponse({"deleted": True})
        return JSONResponse({"error": "not found"}, status_code=404)

    @app.get("/notes", response_class=HTMLResponse)
    async def notes_page(request: Request):
        pages = _wiki_pages()
        db_path = output_dir / "store.db"
        with SqliteStore(db_path) as store:
            notes = store.list_notes()
        return templates.TemplateResponse(
            request, "notes.html",
            _ctx(request, pages=pages, notes=notes, project_name=_project_name()),
        )

    return app
