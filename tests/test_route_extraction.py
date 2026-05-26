"""Tests for framework-aware route extraction (#137).

Covers:
- route_patterns helpers (extract_routes_from_line, normalise_method, _clean_path)
- Python extractor: Flask, FastAPI, Django, Starlette
- TypeScript extractor: Express, Koa, NestJS, Next.js file-path inference
- Go extractor: Gin, Echo, Chi, net/http
- Rust extractor: Axum, Actix-web macros, Rocket
- SymbolKind "route" accepted by contracts
"""
from __future__ import annotations

import textwrap
from pathlib import Path

from rekipedia.extractors.route_patterns import (
    GO_ROUTE_PATTERNS,
    PYTHON_ROUTE_PATTERNS,
    RUST_ROUTE_PATTERNS,
    TYPESCRIPT_ROUTE_PATTERNS,
    _clean_path,
    extract_routes_from_line,
    normalise_method,
)
from rekipedia.models.contracts import Symbol

# ── helpers ──────────────────────────────────────────────────────────────────

def _sym_names_of_kind(symbols, kind="route"):
    return [s.name if hasattr(s, "name") else s["name"] for s in symbols
            if (s.kind if hasattr(s, "kind") else s.get("kind")) == kind]


def _extract_py(source: str, filename: str = "app.py"):
    import tempfile

    from rekipedia.extractors.python_extractor import PythonExtractor
    ext = PythonExtractor()
    with tempfile.TemporaryDirectory() as tmp:
        fpath = Path(tmp) / filename
        fpath.write_text(source)
        return ext.extract(fpath, Path(tmp))


def _extract_ts(source: str, filename: str = "server.ts"):
    import tempfile

    from rekipedia.extractors.typescript_extractor import TypeScriptExtractor
    ext = TypeScriptExtractor()
    with tempfile.TemporaryDirectory() as tmp:
        fpath = Path(tmp) / filename
        fpath.write_text(source)
        return ext.extract(fpath, Path(tmp))


def _extract_go(source: str, filename: str = "main.go"):
    import tempfile

    from rekipedia.extractors.go_extractor import GoExtractor
    ext = GoExtractor()
    with tempfile.TemporaryDirectory() as tmp:
        fpath = Path(tmp) / filename
        fpath.write_text(source)
        return ext.extract(fpath, Path(tmp))


def _extract_rust(source: str, filename: str = "main.rs"):
    import tempfile

    from rekipedia.extractors.rust_extractor import RustExtractor
    ext = RustExtractor()
    with tempfile.TemporaryDirectory() as tmp:
        fpath = Path(tmp) / filename
        fpath.write_text(source)
        return ext.extract(fpath, Path(tmp))


# ── unit: helpers ─────────────────────────────────────────────────────────────

class TestNormaliseMethod:
    def test_get_uppercase(self):
        assert normalise_method("get") == "GET"

    def test_post_uppercase(self):
        assert normalise_method("POST") == "POST"

    def test_any_becomes_wildcard(self):
        assert normalise_method("any") == "*"

    def test_all_becomes_wildcard(self):
        assert normalise_method("all") == "*"

    def test_use_becomes_wildcard(self):
        assert normalise_method("use") == "*"

    def test_unknown_uppercased(self):
        assert normalise_method("CUSTOM") == "CUSTOM"


class TestCleanPath:
    def test_adds_leading_slash(self):
        assert _clean_path("users") == "/users"

    def test_strips_django_caret(self):
        assert _clean_path("^users/") == "/users/"

    def test_strips_django_dollar(self):
        assert _clean_path("^users/$") == "/users/"

    def test_none_returns_root(self):
        assert _clean_path(None) == "/"

    def test_empty_returns_root(self):
        assert _clean_path("") == "/"


class TestExtractRoutesFromLine:
    def test_flask_route_decorator(self):
        line = "@app.route('/users', methods=['GET', 'POST'])"
        results = extract_routes_from_line(line, PYTHON_ROUTE_PATTERNS)
        names = [r[0] for r in results]
        assert any("/users" in n for n in names)

    def test_flask_shorthand_get(self):
        line = "@app.get('/health')"
        results = extract_routes_from_line(line, PYTHON_ROUTE_PATTERNS)
        assert any("GET /health" in r[0] for r in results)

    def test_fastapi_post(self):
        line = "@router.post('/users/{user_id}')"
        results = extract_routes_from_line(line, PYTHON_ROUTE_PATTERNS)
        assert any("POST /users/{user_id}" in r[0] for r in results)

    def test_express_get(self):
        line = "router.get('/api/v1/users', getUsers);"
        results = extract_routes_from_line(line, TYPESCRIPT_ROUTE_PATTERNS)
        assert any("GET /api/v1/users" in r[0] for r in results)

    def test_gin_get(self):
        line = 'r.GET("/ping", pingHandler)'
        results = extract_routes_from_line(line, GO_ROUTE_PATTERNS)
        assert any("GET /ping" in r[0] for r in results)

    def test_axum_route(self):
        line = '.route("/users", get(list_users))'
        results = extract_routes_from_line(line, RUST_ROUTE_PATTERNS)
        assert any("/users" in r[0] for r in results)


# ── Python extractor ──────────────────────────────────────────────────────────

class TestPythonRouteExtraction:
    def test_flask_route_decorator(self):
        src = textwrap.dedent("""
            from flask import Flask
            app = Flask(__name__)

            @app.route('/users', methods=['GET'])
            def list_users():
                pass
        """)
        result = _extract_py(src)
        routes = _sym_names_of_kind(result.symbols)
        assert any("/users" in r for r in routes)

    def test_flask_shorthand(self):
        src = textwrap.dedent("""
            @bp.post('/users')
            def create_user():
                pass
        """)
        result = _extract_py(src)
        routes = _sym_names_of_kind(result.symbols)
        assert any("POST /users" in r for r in routes)

    def test_fastapi_decorator(self):
        src = textwrap.dedent("""
            from fastapi import FastAPI
            app = FastAPI()

            @app.get('/items/{item_id}')
            async def read_item(item_id: int):
                pass

            @app.post('/items')
            async def create_item():
                pass
        """)
        result = _extract_py(src)
        routes = _sym_names_of_kind(result.symbols)
        assert any("/items/{item_id}" in r for r in routes), routes
        assert any("POST /items" in r for r in routes), routes

    def test_django_path(self):
        src = textwrap.dedent("""
            from django.urls import path
            urlpatterns = [
                path('users/', views.UserListView.as_view()),
                path('users/<int:pk>/', views.UserDetailView.as_view()),
            ]
        """)
        result = _extract_py(src)
        routes = _sym_names_of_kind(result.symbols)
        assert any("users/" in r for r in routes), routes

    def test_route_symbols_have_correct_kind(self):
        src = "@app.get('/ping')\ndef ping(): pass\n"
        result = _extract_py(src)
        route_syms = [s for s in result.symbols if (s.kind if hasattr(s, "kind") else s.get("kind")) == "route"]
        assert len(route_syms) >= 1
        for sym in route_syms:
            assert (sym.kind if hasattr(sym, "kind") else sym.get("kind")) == "route"

    def test_no_duplicate_routes(self):
        src = textwrap.dedent("""
            @app.get('/users')
            def list_users(): pass
            @app.get('/users')
            def also_list_users(): pass
        """)
        result = _extract_py(src)
        routes = _sym_names_of_kind(result.symbols)
        assert routes.count("GET /users") == 1


# ── TypeScript extractor ──────────────────────────────────────────────────────

class TestTypescriptRouteExtraction:
    def test_express_get(self):
        src = textwrap.dedent("""
            const router = express.Router();
            router.get('/users', listUsers);
            router.post('/users', createUser);
        """)
        result = _extract_ts(src, "routes.ts")
        routes = _sym_names_of_kind(result.symbols)
        assert any("GET /users" in r for r in routes), routes
        assert any("POST /users" in r for r in routes), routes

    def test_nestjs_decorator(self):
        src = textwrap.dedent("""
            @Controller('cats')
            export class CatsController {
                @Get('/list')
                findAll() {}

                @Post()
                create() {}
            }
        """)
        result = _extract_ts(src, "cats.controller.ts")
        routes = _sym_names_of_kind(result.symbols)
        assert any("/list" in r for r in routes), routes

    def test_nextjs_api_route_inferred(self):
        src = "export default function handler(req, res) { res.json({ok: true}); }\n"
        import tempfile

        from rekipedia.extractors.typescript_extractor import TypeScriptExtractor
        ext = TypeScriptExtractor()
        with tempfile.TemporaryDirectory() as tmp:
            # create nested directory structure
            api_dir = Path(tmp) / "pages" / "api" / "users"
            api_dir.mkdir(parents=True)
            fpath = api_dir / "[id].ts"
            fpath.write_text(src)
            result = ext.extract(fpath, Path(tmp))
        routes = _sym_names_of_kind(result.symbols)
        assert any("{id}" in r or "users" in r for r in routes), routes


# ── Go extractor ──────────────────────────────────────────────────────────────

class TestGoRouteExtraction:
    def test_gin_routes(self):
        src = textwrap.dedent("""
            package main

            import "github.com/gin-gonic/gin"

            func main() {
                r := gin.Default()
                r.GET("/ping", pingHandler)
                r.POST("/users", createUser)
                r.Run()
            }
        """)
        result = _extract_go(src)
        routes = _sym_names_of_kind(result.symbols)
        assert any("GET /ping" in r for r in routes), routes
        assert any("POST /users" in r for r in routes), routes

    def test_net_http_handlefunc(self):
        src = textwrap.dedent("""
            package main

            import "net/http"

            func main() {
                http.HandleFunc("/health", healthCheck)
                http.ListenAndServe(":8080", nil)
            }
        """)
        result = _extract_go(src)
        routes = _sym_names_of_kind(result.symbols)
        assert any("/health" in r for r in routes), routes


# ── Rust extractor ────────────────────────────────────────────────────────────

class TestRustRouteExtraction:
    def test_actix_macros(self):
        src = textwrap.dedent("""
            use actix_web::{get, post, web, App};

            #[get("/users")]
            async fn list_users() -> impl Responder { "ok" }

            #[post("/users")]
            async fn create_user() -> impl Responder { "ok" }
        """)
        result = _extract_rust(src)
        routes = _sym_names_of_kind(result.symbols)
        assert any("/users" in r for r in routes), routes

    def test_axum_route(self):
        src = textwrap.dedent("""
            use axum::{routing::get, Router};

            let app = Router::new()
                .route("/health", get(health_check))
                .route("/users", post(create_user));
        """)
        result = _extract_rust(src)
        routes = _sym_names_of_kind(result.symbols)
        assert any("/health" in r for r in routes), routes


# ── contracts: SymbolKind includes "route" ────────────────────────────────────

class TestSymbolKindRoute:
    def test_route_kind_valid(self):
        sym = Symbol(name="GET /ping", kind="route", file="app.py", line_start=1)
        assert sym.kind == "route"

    def test_route_kind_in_literal(self):
        import typing

        from rekipedia.models.contracts import SymbolKind
        args = typing.get_args(SymbolKind)
        assert "route" in args
