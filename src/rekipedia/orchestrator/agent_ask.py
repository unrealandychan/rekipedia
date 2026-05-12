"""Agentic ReAct ask loop for `rekipedia ask`.

The LLM issues tool calls to retrieve information on demand instead of
receiving a single massive context dump. This avoids the 96K context
anti-pattern and lets the model fetch exactly what it needs.

Tools:
    search_code(query, top_k=5)  — RAG semantic search over source chunks
    get_symbol(name)             — look up symbol location + signature
    get_page(slug)               — fetch full wiki page content
    get_relationships(target)    — dependency graph for a symbol/file
    finish(answer)               — provide final answer (terminates loop)

Environment:
    REKIPEDIA_AGENT_ASK=1        — enable agentic mode (default: 0 / off)
    REKIPEDIA_ASK_MAX_ITER=5     — max tool call iterations (default: 5)
"""
from __future__ import annotations

import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import litellm

from rekipedia.llm.client import LLMClient
from rekipedia.models.contracts import LLMConfig
from rekipedia.orchestrator.run_ask import (
    _load_symbol_lines,
    _load_wiki_pages,
    _rag_chunks,
    _verify_scan,
    _build_full_system,
    _SYSTEM_PROMPT_PATH,
    _RAG_TOP_K,
)
from rekipedia.storage.sqlite_store import SqliteStore

logger = logging.getLogger("rekipedia.agent_ask")

_MAX_ITER = int(os.environ.get("REKIPEDIA_ASK_MAX_ITER", "5"))

# ---------------------------------------------------------------------------
# Tool definitions (litellm-compatible JSON schema)
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_code",
            "description": (
                "Search for relevant source code using semantic/keyword search. "
                "Use when you need to find specific implementation details, function bodies, or code patterns."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "top_k": {"type": "integer", "description": "Number of results to return", "default": 5},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_symbol",
            "description": (
                "Look up a specific symbol (function, class, method, type) by name. "
                "Returns file, line number, kind, and signature."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Symbol name to look up"},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_page",
            "description": (
                "Fetch the full content of a wiki documentation page. "
                "Use when you need broad conceptual explanation of a component or feature."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "slug": {"type": "string", "description": "Wiki page slug (filename without .md)"},
                },
                "required": ["slug"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_relationships",
            "description": (
                "Get all known relationships (imports, calls, inherits, uses) for a symbol name or file path."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "Symbol name or file path to look up"},
                },
                "required": ["target"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finish",
            "description": (
                "Provide the final answer to the user's question. "
                "Call this ONLY when you have enough information. The answer should be complete Markdown."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "answer": {"type": "string", "description": "Final answer in Markdown"},
                },
                "required": ["answer"],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# Tool handler
# ---------------------------------------------------------------------------

class _ToolHandler:
    def __init__(self, output_dir: Path, llm_config: LLMConfig) -> None:
        self._output_dir = output_dir
        self._llm_config = llm_config
        self._symbol_cache: list[dict] | None = None
        self._page_cache: dict[str, str] = {}

    def _get_symbols(self) -> list[dict]:
        if self._symbol_cache is None:
            symbols_path = self._output_dir / "exports" / "symbols.json"
            if symbols_path.exists():
                try:
                    self._symbol_cache = json.loads(symbols_path.read_text(encoding="utf-8"))
                except Exception:
                    self._symbol_cache = []
            else:
                self._symbol_cache = []
        return self._symbol_cache

    def search_code(self, query: str, top_k: int = 5) -> str:
        results = _rag_chunks(query, self._output_dir, self._llm_config, top_k=top_k)
        if not results:
            return "No code chunks found for this query."
        parts = []
        for chunk in results:
            file_ = chunk.get("file", "")
            ext = chunk.get("ext", "").lstrip(".")
            score = chunk.get("score", 0.0)
            text = chunk.get("text", "")
            parts.append(f"### `{file_}` (score={score:.2f})\n```{ext}\n{text}\n```")
        return "\n\n".join(parts)

    def get_symbol(self, name: str) -> str:
        symbols = self._get_symbols()
        matches = [s for s in symbols if s.get("name", "").lower() == name.lower()]
        if not matches:
            # fuzzy: contains
            matches = [s for s in symbols if name.lower() in s.get("name", "").lower()][:5]
        if not matches:
            return f"No symbol found matching '{name}'."
        parts = []
        for s in matches[:5]:
            line = f"**{s.get('name')}** ({s.get('kind', '?')}) — `{s.get('file', '?')}`"
            if s.get("signature"):
                line += f"\n```\n{s['signature']}\n```"
            parts.append(line)
        return "\n\n".join(parts)

    def get_page(self, slug: str) -> str:
        if slug in self._page_cache:
            return self._page_cache[slug]
        wiki_dir = self._output_dir / "wiki"
        path = wiki_dir / f"{slug}.md"
        if not path.exists():
            # fuzzy match
            candidates = list(wiki_dir.glob("*.md")) if wiki_dir.exists() else []
            for c in candidates:
                if slug.lower() in c.stem.lower():
                    path = c
                    break
            else:
                available = ", ".join(c.stem for c in candidates[:10])
                return f"Page '{slug}' not found. Available: {available}"
        content = path.read_text(encoding="utf-8")
        self._page_cache[slug] = content
        return content

    def get_relationships(self, target: str) -> str:
        db_path = self._output_dir / "store.db"
        if not db_path.exists():
            return "No relationship data available."
        try:
            with SqliteStore(db_path) as store:
                # Try to find any successful run — iterate over possible repo paths
                run_id = store.get_latest_run_id(str(self._output_dir.parent))
                if run_id is None:
                    # Try grandparent as well
                    run_id = store.get_latest_run_id(str(self._output_dir.parent.parent))
                if run_id is None:
                    return "No scan run found."
                all_rels = store.get_all_relationships(run_id)
            matches = [
                r for r in all_rels
                if target.lower() in str(r.get("source", "")).lower()
                or target.lower() in str(r.get("target", "")).lower()
            ][:20]
            if not matches:
                return f"No relationships found for '{target}'."
            lines = []
            for r in matches:
                lines.append(f"- {r.get('source', '?')} --[{r.get('kind', '?')}]--> {r.get('target', '?')}")
            return "\n".join(lines)
        except Exception as exc:
            return f"Error fetching relationships: {exc}"

    def dispatch(self, tool_name: str, args: dict) -> str:
        if tool_name == "search_code":
            return self.search_code(args.get("query", ""), args.get("top_k", 5))
        elif tool_name == "get_symbol":
            return self.get_symbol(args.get("name", ""))
        elif tool_name == "get_page":
            return self.get_page(args.get("slug", ""))
        elif tool_name == "get_relationships":
            return self.get_relationships(args.get("target", ""))
        else:
            return f"Unknown tool: {tool_name}"


# ---------------------------------------------------------------------------
# AgentAsk class
# ---------------------------------------------------------------------------

class AgentAsk:
    """ReAct agentic loop for answering codebase questions.

    Falls back to single-shot mode if the model doesn't support tool calling.
    """

    def __init__(self, output_dir: Path, llm_config: LLMConfig) -> None:
        self._output_dir = output_dir
        self._llm_config = llm_config
        self._handler = _ToolHandler(output_dir, llm_config)
        self._client = LLMClient(llm_config)

    def _build_initial_system(self, question: str) -> str:
        system_prompt = _SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
        # List available pages as hint
        wiki_dir = self._output_dir / "wiki"
        page_list = ""
        if wiki_dir.exists():
            slugs = sorted(p.stem for p in wiki_dir.glob("*.md"))
            page_list = f"\n\nAvailable wiki pages: {', '.join(slugs)}"
        return system_prompt + page_list

    def run(
        self,
        question: str,
        history: list[dict] | None = None,
        max_iter: int = _MAX_ITER,
    ) -> str:
        """Run agentic ReAct loop. Returns final answer string."""
        system = self._build_initial_system(question)
        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": question})

        llm_config = self._llm_config
        model = os.environ.get("REKIPEDIA_MODEL") or llm_config.model
        api_key = os.environ.get("REKIPEDIA_API_KEY") or llm_config.api_key or None
        base_url = os.environ.get("REKIPEDIA_BASE_URL") or llm_config.base_url or None

        kwargs: dict = {
            "model": model,
            "temperature": llm_config.temperature,
            "timeout": 180,
            "tools": TOOLS,
            "tool_choice": "auto",
        }
        if api_key:
            kwargs["api_key"] = api_key
        if base_url:
            kwargs["base_url"] = base_url

        for _iteration in range(max_iter):
            kwargs["messages"] = messages
            try:
                response = litellm.completion(**kwargs)
            except Exception as exc:
                logger.warning("AgentAsk LLM call failed (%s) — falling back to single-shot", exc)
                full_system = _build_full_system(question, self._output_dir, llm_config)
                return self._client.call(question, system=full_system, history=history)

            msg = response.choices[0].message
            tool_calls = getattr(msg, "tool_calls", None) or []

            if not tool_calls:
                # Model gave a direct response (no tool call) — treat as final answer
                return msg.content or ""

            # Append assistant message with tool calls
            if hasattr(msg, "model_dump"):
                messages.append(msg.model_dump(exclude_none=True))
            else:
                messages.append({
                    "role": "assistant",
                    "content": msg.content,
                    "tool_calls": [tc.model_dump() for tc in tool_calls],
                })

            # Dispatch tool calls in parallel — calls within one turn are independent
            finish_answer: str | None = None
            tool_results: list[tuple[str, str]] = []  # (tool_call_id, result)

            def _dispatch_one(tc) -> tuple[str, str, bool, str]:
                """Returns (tc_id, result, is_finish, answer)."""
                fn_name = tc.function.name
                try:
                    fn_args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    fn_args = {}
                if fn_name == "finish":
                    return tc.id, "", True, fn_args.get("answer", "")
                result = self._handler.dispatch(fn_name, fn_args)
                logger.debug("Tool %s(%s) → %d chars", fn_name, fn_args, len(result))
                return tc.id, result, False, ""

            with ThreadPoolExecutor(max_workers=min(len(tool_calls), 4)) as pool:
                futures = {pool.submit(_dispatch_one, tc): tc for tc in tool_calls}
                for fut in as_completed(futures):
                    tc_id, result, is_finish, answer = fut.result()
                    if is_finish:
                        finish_answer = answer
                    else:
                        tool_results.append((tc_id, result))

            if finish_answer is not None:
                return finish_answer

            # Append tool results in original tool_call order for deterministic context
            id_to_result = dict(tool_results)
            for tc in tool_calls:
                if tc.id in id_to_result:
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": id_to_result[tc.id],
                    })

        # Max iterations reached — ask for final answer without tools
        messages.append({
            "role": "user",
            "content": "You have reached the maximum number of tool calls. Please provide your final answer now based on what you've gathered.",
        })
        kwargs_final = {k: v for k, v in kwargs.items() if k not in ("tools", "tool_choice")}
        kwargs_final["messages"] = messages
        try:
            final_response = litellm.completion(**kwargs_final)
            return final_response.choices[0].message.content or ""
        except Exception:
            return "Unable to generate answer after maximum tool iterations."


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def agent_run_ask(
    question: str,
    repo_root: Path,
    output_dir: Path,
    llm_config: LLMConfig | None = None,
    history: list[dict] | None = None,
) -> str:
    """Agentic version of run_ask."""
    llm_config = llm_config or LLMConfig()
    _verify_scan(output_dir, repo_root)
    agent = AgentAsk(output_dir, llm_config)
    return agent.run(question, history=history)
