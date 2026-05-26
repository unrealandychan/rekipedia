"""reki mcp — MCP stdio server exposing rekipedia graph as AI tools."""
from __future__ import annotations

import json
import sys
from pathlib import Path

TOOLS = [
    {"name": "ask",
     "description": "Answer a natural-language question about this codebase, grounded in the scanned wiki pages, symbol index, and source code embeddings. Use this before reading any source file.",
     "inputSchema": {"type": "object",
       "properties": {
         "question": {"type": "string", "description": "The question to answer about the codebase"},
         "repo":     {"type": "string", "description": "Absolute path to repo root (default: cwd)"}
       },
       "required": ["question"]}},
    {"name": "get_context", "description": "Get symbols and relationships for a file (partial filename match supported)",
     "inputSchema": {"type": "object", "properties": {"file": {"type": "string"}}, "required": ["file"]}},
    {"name": "search_nodes", "description": "Search symbol names (fast indexed lookup)",
     "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
    {"name": "get_relationships", "description": "Get callers and callees for a symbol",
     "inputSchema": {"type": "object", "properties": {"symbol": {"type": "string"}}, "required": ["symbol"]}},
    {"name": "get_knowledge_gaps", "description": "List untested high-call-count symbols",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "get_hub_nodes", "description": "List architectural chokepoints",
     "inputSchema": {"type": "object", "properties": {"top_n": {"type": "integer", "default": 10}}}},
    {"name": "get_impact", "description": "Blast-radius for a changed file",
     "inputSchema": {"type": "object", "properties": {"file": {"type": "string"}, "depth": {"type": "integer", "default": 2}}, "required": ["file"]}},
    {"name": "get_transitive_impact", "description": "BFS transitive impact from a symbol name",
     "inputSchema": {"type": "object", "properties": {
         "target_symbol": {"type": "string"},
         "depth": {"type": "integer", "default": 5},
         "direction": {"type": "string", "default": "callers"},
     }, "required": ["target_symbol"]}},
]


class _StoreCache:
    """
    Lazy-loading, auto-refreshing store cache.

    Symbols and relationships are loaded on first access and reloaded
    automatically whenever the DB file's mtime changes (i.e. after reki scan).
    This means the MCP server never needs to be restarted after a rescan.
    """

    def __init__(self, output_dir: str):
        self._rekipedia_dir = Path(output_dir) / ".rekipedia"
        self.db_path = self._resolve_db_path()
        self._store = None
        self._symbols: list = []
        self._rels: list = []
        self._mtime: float = 0.0
        # Pre-built indices for O(1) / O(log n) lookups
        self._name_index: dict[str, list] = {}   # lower(name) → [symbols]
        self._file_index: dict[str, list] = {}   # lower(file) → [symbols]
        self._callers_index: dict[str, list] = {}  # symbol → [callers]
        self._callees_index: dict[str, list] = {}  # symbol → [callees]

    def _resolve_db_path(self) -> Path:
        store = self._rekipedia_dir / "store.db"
        if store.exists():
            return store
        alt = self._rekipedia_dir / "rekipedia.db"
        if alt.exists():
            return alt
        return store  # default to store.db (will not exist yet if unscanned)

    # ── public accessors ──────────────────────────────────────────────────────

    @property
    def available(self) -> bool:
        return self.db_path.exists()

    @property
    def symbols(self) -> list:
        self._refresh()
        return self._symbols

    @property
    def rels(self) -> list:
        self._refresh()
        return self._rels

    def search_by_name(self, query: str) -> list:
        self._refresh()
        q = query.lower()
        results = []
        for key, syms in self._name_index.items():
            if q in key:
                results.extend(syms)
        return results[:50]

    def symbols_for_file(self, file_arg: str) -> list:
        """Match by suffix so partial paths work (e.g. 'foo.py' matches '/abs/src/foo.py')."""
        self._refresh()
        fa = file_arg.lower().replace("\\", "/")
        results = []
        for key, syms in self._file_index.items():
            if key.endswith(fa) or fa in key:
                results.extend(syms)
        return results

    def callers_callees(self, symbol: str) -> tuple[list, list]:
        self._refresh()
        return (
            self._callers_index.get(symbol, [])[:30],
            self._callees_index.get(symbol, [])[:30],
        )

    # ── internals ─────────────────────────────────────────────────────────────

    def _refresh(self):
        self.db_path = self._resolve_db_path()
        if not self.db_path.exists():
            return
        try:
            current_mtime = self.db_path.stat().st_mtime
        except OSError:
            return
        if current_mtime <= self._mtime:
            return  # DB unchanged — use cached data
        self._load(current_mtime)

    def _load(self, mtime: float):
        try:
            from rekipedia.storage.sqlite_store import SqliteStore
            store = SqliteStore(self.db_path)
            run_id = store.latest_run_id()
            if not run_id:
                return
            symbols = store.get_all_symbols(run_id)
            rels = store.get_all_relationships(run_id)
            self._store = store
            self._symbols = symbols
            self._rels = rels
            self._mtime = mtime
            self._rebuild_indices(symbols, rels)
        except Exception:
            pass  # silently keep stale data if reload fails

    def _rebuild_indices(self, symbols, rels):
        name_idx: dict[str, list] = {}
        file_idx: dict[str, list] = {}
        for s in symbols:
            name = (s.name if hasattr(s, "name") else s.get("name", "")).lower()
            file = (s.file if hasattr(s, "file") else s.get("file", "")).lower().replace("\\", "/")
            name_idx.setdefault(name, []).append(s)
            if file:
                file_idx.setdefault(file, []).append(s)
        self._name_index = name_idx
        self._file_index = file_idx

        callers: dict[str, list] = {}
        callees: dict[str, list] = {}
        for r in rels:
            if isinstance(r, dict):
                frm = r.get("from_", "") or r.get("from", "")
                to  = r.get("to", "")
                kind = r.get("kind", "")
            else:
                frm  = r.from_ or ""
                to   = r.to or ""
                kind = r.kind or ""
            if kind == "calls":
                callers.setdefault(to, []).append(frm)
                callees.setdefault(frm, []).append(to)
        self._callers_index = callers
        self._callees_index = callees


def _sym_to_dict(s) -> dict:
    return {
        "name": s.name if hasattr(s, "name") else s.get("name", ""),
        "file": s.file if hasattr(s, "file") else s.get("file", ""),
        "kind": s.kind if hasattr(s, "kind") else s.get("kind", ""),
    }


def _handle_tool(name: str, args: dict, cache: _StoreCache) -> str:
    try:
        if not cache.available:
            return json.dumps({"error": "No rekipedia DB found. Run reki scan first."})

        if name == "get_context":
            file_arg = args.get("file", "")
            syms = cache.symbols_for_file(file_arg)
            sym_names = [_sym_to_dict(s)["name"] for s in syms]
            sym_name_set = set(sym_names)
            file_rels = []
            for r in cache.rels:
                if isinstance(r, dict):
                    frm  = r.get("from_", "") or r.get("from", "")
                    to   = r.get("to", "")
                    kind = r.get("kind", "")
                else:
                    frm  = r.from_ or ""
                    to   = r.to or ""
                    kind = r.kind or ""
                if frm in sym_name_set:
                    file_rels.append({"from": frm, "to": to, "kind": kind})
            return json.dumps({"symbols": sym_names[:50], "relationships": file_rels[:100]})

        elif name == "search_nodes":
            matches = [_sym_to_dict(s) for s in cache.search_by_name(args.get("query", ""))]
            return json.dumps({"matches": matches})

        elif name == "get_relationships":
            symbol = args.get("symbol", "")
            callers, callees = cache.callers_callees(symbol)
            return json.dumps({"symbol": symbol, "callers": callers, "callees": callees})

        elif name == "get_knowledge_gaps":
            from rekipedia.analysis.graph_analysis import _build_knowledge_gaps
            class _R:
                pass
            r = _R()
            r.symbols = cache.symbols
            r.relationships = cache.rels
            gaps = _build_knowledge_gaps(r)
            return json.dumps({"knowledge_gaps": gaps})

        elif name == "get_hub_nodes":
            from rekipedia.analysis.graph_analysis import _build_hub_nodes
            hubs = _build_hub_nodes(cache.rels, cache.symbols, top_n=args.get("top_n", 10))
            return json.dumps({"hub_nodes": hubs})

        elif name == "get_impact":
            from rekipedia.analysis.impact import compute_impact
            result = compute_impact(args.get("file", ""), cache.rels, cache.symbols, depth=args.get("depth", 2))
            return json.dumps(result)

        elif name == "get_transitive_impact":
            from rekipedia.analysis.impact import compute_transitive_impact
            result = compute_transitive_impact(
                args.get("target_symbol", ""),
                cache.rels,
                cache.symbols,
                depth=args.get("depth", 5),
                direction=args.get("direction", "callers"),
            )
            return json.dumps(result)

        elif name == "ask":
            question = args.get("question", "")
            repo_path = Path(args.get("repo") or Path.cwd())
            out_dir = repo_path / ".rekipedia"
            if not out_dir.exists():
                return json.dumps({"error": "No .rekipedia dir found. Run reki scan first."})
            from rekipedia.models.contracts import LLMConfig
            from rekipedia.orchestrator.run_ask import run_ask
            answer = run_ask(question, repo_path, out_dir, llm_config=LLMConfig())
            return json.dumps({"answer": answer})

        return json.dumps({"error": f"Unknown tool: {name}"})

    except Exception as exc:
        return json.dumps({"error": str(exc)})


def write_mcp_json(repo_root: Path):
    """Write / update .mcp.json at the repo root after a scan.

    Idempotent — safe to call on every scan.
    Skips silently if the file already exists with the correct content.
    """
    mcp_json_path = repo_root / ".mcp.json"
    config = {
        "mcpServers": {
            "rekipedia": {
                "command": "reki",
                "args": ["mcp"],
                "description": "rekipedia codebase knowledge — ask questions, search symbols, get impact analysis",
            }
        }
    }
    content = json.dumps(config, indent=2) + "\n"
    try:
        if mcp_json_path.exists() and mcp_json_path.read_text() == content:
            return  # already up to date
        mcp_json_path.write_text(content)
    except OSError:
        pass  # non-fatal — MCP server still works without the file


def _write(obj: dict):
    print(json.dumps(obj), flush=True)


def run_mcp_server(output_dir: str = "."):
    """Run MCP JSON-RPC 2.0 stdio server."""
    cache = _StoreCache(output_dir)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue

        req_id  = req.get("id")
        method  = req.get("method", "")
        params  = req.get("params", {})

        if method == "initialize":
            _write({"jsonrpc": "2.0", "id": req_id, "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "rekipedia", "version": "1.0.0"},
            }})
        elif method == "tools/list":
            _write({"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}})
        elif method == "tools/call":
            result_text = _handle_tool(params.get("name", ""), params.get("arguments", {}), cache)
            _write({"jsonrpc": "2.0", "id": req_id, "result": {
                "content": [{"type": "text", "text": result_text}]
            }})
        elif method == "notifications/initialized":
            continue  # notifications require no response
        else:
            _write({"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": "Method not found"}})
