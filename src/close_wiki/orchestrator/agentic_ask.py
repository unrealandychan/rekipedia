"""Agentic ReAct loop for `reki ask --agentic`.

Instead of a single-shot RAG call, the LLM can issue up to *max_iter*
tool calls before delivering its final answer.  This avoids the context-
stuffing anti-pattern for complex multi-part questions.

Tools available to the LLM
---------------------------
search_code(query)        — re-run BM25/RAG retrieval mid-answer
get_symbol(name)          — look up a symbol's file / line / signature
get_page(slug)            — fetch a specific wiki page on demand
get_relationships(symbol) — list edges in the dependency graph

Fallback
--------
If the model returns a response with no tool calls on the first turn, or
if litellm raises a BadRequestError (model doesn't support tool calling),
we fall back silently to the single-shot path.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

import litellm

from close_wiki.llm.client import LLMClient
from close_wiki.models.contracts import LLMConfig
from close_wiki.orchestrator.run_ask import (
    _build_full_system,
    _load_wiki_pages,
    _load_symbol_lines,
    _rag_chunks,
    _verify_scan,
)
from close_wiki.storage.sqlite_store import SqliteStore

logger = logging.getLogger("close_wiki.orchestrator.agentic_ask")

_DEFAULT_MAX_ITER = int(os.environ.get("REKIPEDIA_ASK_MAX_ITER", "5"))

# ---------------------------------------------------------------------------
# Tool schemas (OpenAI function-calling format, passed via litellm tools=)
# ---------------------------------------------------------------------------

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_code",
            "description": (
                "Search the codebase for source chunks relevant to a query. "
                "Use this when you need more specific code evidence that may not "
                "be in the initial context."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural language or keyword search query.",
                    }
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
                "Look up a specific symbol (function, class, variable) by name. "
                "Returns its file path, line number, kind, and signature."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Exact or partial symbol name to look up.",
                    }
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
                "Fetch the full content of a specific wiki page by its slug. "
                "Use this to get more detail on a module or concept."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "slug": {
                        "type": "string",
                        "description": "Wiki page slug (filename without .md extension).",
                    }
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
                "Return the dependency graph edges (imports, calls, inherits) "
                "for a given symbol. Useful for tracing call chains."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "Symbol name to look up relationships for.",
                    }
                },
                "required": ["symbol"],
            },
        },
    },
]

# ---------------------------------------------------------------------------
# Tool executor
# ---------------------------------------------------------------------------

class _ToolExecutor:
    """Executes tool calls against the local knowledge store."""

    def __init__(
        self,
        output_dir: Path,
        llm_config: LLMConfig,
        db_path: Path,
        run_id: str,
    ) -> None:
        self._output_dir = output_dir
        self._llm_config = llm_config
        self._db_path = db_path
        self._run_id = run_id

    def execute(self, name: str, arguments: dict[str, Any]) -> str:
        try:
            if name == "search_code":
                return self._search_code(arguments["query"])
            if name == "get_symbol":
                return self._get_symbol(arguments["name"])
            if name == "get_page":
                return self._get_page(arguments["slug"])
            if name == "get_relationships":
                return self._get_relationships(arguments["symbol"])
            return f"Unknown tool: {name}"
        except Exception as exc:  # noqa: BLE001
            return f"Tool error ({name}): {exc}"

    def _search_code(self, query: str) -> str:
        chunks = _rag_chunks(query, self._output_dir, self._llm_config, top_k=5)
        if not chunks:
            return "No relevant code chunks found."
        parts: list[str] = []
        for chunk in chunks:
            file_ = chunk.get("file", "")
            score = chunk.get("score", 0.0)
            text = chunk.get("text", "")
            ext = chunk.get("ext", "").lstrip(".")
            parts.append(f"### `{file_}` (score={score:.2f})\n```{ext}\n{text}\n```")
        return "\n\n".join(parts)

    def _get_symbol(self, name: str) -> str:
        with SqliteStore(self._db_path) as store:
            symbols = store.search_symbols(self._run_id, name, limit=10)
        if not symbols:
            return f"No symbol found matching '{name}'."
        lines: list[str] = []
        for sym in symbols:
            line = f"**{sym.get('name')}** ({sym.get('kind')}) — `{sym.get('file')}`"
            if sym.get("line_start"):
                line += f" line {sym['line_start']}"
            if sym.get("signature"):
                line += f"\n  Signature: `{sym['signature']}`"
            lines.append(line)
        return "\n".join(lines)

    def _get_page(self, slug: str) -> str:
        wiki_dir = self._output_dir / "wiki"
        # Try exact match first, then prefix match
        for candidate in [f"{slug}.md", f"{slug.lower()}.md"]:
            page_path = wiki_dir / candidate
            if page_path.exists():
                return page_path.read_text(encoding="utf-8")
        # Fuzzy: find any page whose stem contains the slug
        if wiki_dir.exists():
            for md_file in wiki_dir.glob("*.md"):
                if slug.lower() in md_file.stem.lower():
                    return md_file.read_text(encoding="utf-8")
        return f"No wiki page found for slug '{slug}'."

    def _get_relationships(self, symbol: str) -> str:
        with SqliteStore(self._db_path) as store:
            edges = store.get_relationships(self._run_id, symbol)
        if not edges:
            return f"No relationships found for '{symbol}'."
        lines = [f"- **{e.get('from_')}** → **{e.get('to')}** ({e.get('kind')})" for e in edges]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# ReAct loop
# ---------------------------------------------------------------------------

def agentic_ask(
    question: str,
    repo_root: Path,
    output_dir: Path,
    llm_config: LLMConfig | None = None,
    max_iter: int = _DEFAULT_MAX_ITER,
) -> str:
    """Answer *question* via a ReAct tool-calling loop.

    The LLM may call search_code / get_symbol / get_page / get_relationships
    up to *max_iter* times before producing its final answer.

    Falls back to single-shot ``run_ask`` if:
    - The model doesn't support tool calling (litellm BadRequestError)
    - No tool calls are issued on the first turn

    Args:
        question: Free-text question from the user.
        repo_root: Absolute path to the repository.
        output_dir: ``.rekipedia/`` directory.
        llm_config: LLM settings; defaults to LLMConfig().
        max_iter: Maximum tool-call iterations (default: REKIPEDIA_ASK_MAX_ITER env, else 5).

    Returns:
        The assistant's answer as a Markdown string.
    """
    from close_wiki.orchestrator.run_ask import run_ask  # avoid circular at module level

    llm_config = llm_config or LLMConfig()
    run_id = _verify_scan(output_dir, repo_root)
    db_path = output_dir / "store.db"

    executor = _ToolExecutor(output_dir, llm_config, db_path, run_id)
    client = LLMClient(llm_config)

    # Build the same initial system prompt as single-shot (wiki + RAG context)
    system_prompt = _build_full_system(question, output_dir, llm_config)

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": question},
    ]

    try:
        for iteration in range(max_iter):
            response = client.call_with_tools(messages, tools=TOOL_SCHEMAS)

            # No tool calls → final answer
            if not response.get("tool_calls"):
                answer = response.get("content") or ""
                if not answer:
                    # Empty response — fall back
                    logger.warning("Agentic ask: empty response on iter %d, falling back", iteration)
                    return run_ask(question, repo_root, output_dir, llm_config)
                logger.debug("Agentic ask: finished in %d iteration(s)", iteration + 1)
                return answer

            # Append assistant message with tool calls
            messages.append({
                "role": "assistant",
                "content": response.get("content") or "",
                "tool_calls": response["tool_calls"],
            })

            # Execute each tool call and append tool results
            for tc in response["tool_calls"]:
                fn_name = tc["function"]["name"]
                try:
                    fn_args = json.loads(tc["function"]["arguments"])
                except json.JSONDecodeError:
                    fn_args = {}

                logger.debug("Agentic ask: tool call %s(%s)", fn_name, fn_args)
                result = executor.execute(fn_name, fn_args)

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result,
                })

        # Max iterations reached — ask for final answer without tools
        logger.warning("Agentic ask: max_iter=%d reached, requesting final answer", max_iter)
        messages.append({
            "role": "user",
            "content": "Please provide your final answer now based on all the information gathered.",
        })
        response = client.call_with_tools(messages, tools=None)
        return response.get("content") or ""

    except litellm.BadRequestError as exc:
        logger.warning("Agentic ask: model doesn't support tool calling (%s), falling back", exc)
        return run_ask(question, repo_root, output_dir, llm_config)
    except Exception as exc:
        logger.warning("Agentic ask: unexpected error (%s), falling back", exc)
        return run_ask(question, repo_root, output_dir, llm_config)
