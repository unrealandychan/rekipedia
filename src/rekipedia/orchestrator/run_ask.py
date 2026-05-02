"""Grounded Q&A pipeline for `rekipedia ask`.

Flow:
    1. Locate the latest successful scan run for this repo.
    2. Load wiki pages from disk (wiki/*.md).
    3. Load symbol index from exports/symbols.json (if present).
    4. RAG retrieval — FAISS top-K source chunks (if index exists).
    5. Assemble a context string, truncated to a token budget.
    6. Call the LLM with a grounding system prompt.
    7. Return the answer text.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

from rekipedia.llm.client import LLMClient
from rekipedia.models.contracts import LLMConfig
from rekipedia.storage.sqlite_store import SqliteStore

_SYSTEM_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "ask_system.md"

# Approximate character budget for context (≈ 24 K tokens at ~4 chars/token).
# Keeps us safely within the context window of most models.
_CONTEXT_CHAR_BUDGET = 96_000

# RAG: number of code chunks to retrieve per question
_RAG_TOP_K = 8


# ---------------------------------------------------------------------------
# Context assembly (shared by run_ask + stream_ask)
# ---------------------------------------------------------------------------

def _verify_scan(output_dir: Path, repo_root: Path) -> str:
    """Return the latest successful run_id, or raise RuntimeError."""
    db_path = output_dir / "store.db"
    if not db_path.exists():
        raise RuntimeError(
            f"No knowledge store found at {db_path}.\n"
            "Run `rekipedia scan .` first."
        )
    with SqliteStore(db_path) as store:
        run_id = store.get_latest_run_id(str(repo_root))
    if run_id is None:
        raise RuntimeError(
            "No successful scan found for this repository.\n"
            "Run `rekipedia scan .` first."
        )
    return run_id


def _load_wiki_pages(output_dir: Path) -> list[str]:
    wiki_dir = output_dir / "wiki"
    pages: list[str] = []
    if wiki_dir.exists():
        for md_file in sorted(wiki_dir.glob("*.md")):
            slug = md_file.stem
            content = md_file.read_text(encoding="utf-8")
            pages.append(f"## [{slug}.md]\n\n{content}")
    return pages


def _load_symbol_lines(output_dir: Path) -> list[str]:
    symbols_path = output_dir / "exports" / "symbols.json"
    lines: list[str] = []
    if symbols_path.exists():
        try:
            symbols = json.loads(symbols_path.read_text(encoding="utf-8"))
            for sym in symbols:
                name = sym.get("name", "")
                kind = sym.get("kind", "")
                file_ = sym.get("file", "")
                sig = sym.get("signature") or ""
                line = f"[Symbol: {name}] kind={kind} file={file_}"
                if sig:
                    line += f" signature={sig}"
                lines.append(line)
        except (json.JSONDecodeError, KeyError):
            pass
    return lines


def _rag_chunks(
    question: str,
    output_dir: Path,
    llm_config: LLMConfig,
    top_k: int = _RAG_TOP_K,
) -> list[dict]:
    """Return top-k RAG chunks, or [] if index not available."""
    try:
        from rekipedia.rag.embedder import EmbedPipeline  # noqa: PLC0415

        pipe = EmbedPipeline(output_dir, llm_config)
        if not pipe.is_built():
            return []
        return pipe.search(question, top_k=top_k)
    except Exception:
        return []


def _build_full_system(
    question: str,
    output_dir: Path,
    llm_config: LLMConfig,
) -> str:
    """Assemble the system prompt + all context sources."""
    system_prompt = _SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")

    page_texts = _load_wiki_pages(output_dir)
    symbol_lines = _load_symbol_lines(output_dir)
    rag_results = _rag_chunks(question, output_dir, llm_config)

    context_parts: list[str] = ["# Knowledge Context\n"]
    used_chars = sum(len(p) for p in context_parts)

    # ── Wiki pages (highest priority — curated prose) ──────────────────
    for page in page_texts:
        if used_chars + len(page) > _CONTEXT_CHAR_BUDGET:
            context_parts.append(
                "\n*[Additional wiki pages omitted — token budget reached]*\n"
            )
            break
        context_parts.append(page)
        used_chars += len(page)

    # ── RAG: raw source code chunks ────────────────────────────────────
    if rag_results:
        rag_header = "\n## Relevant Source Code (RAG)\n"
        if used_chars + len(rag_header) < _CONTEXT_CHAR_BUDGET:
            context_parts.append(rag_header)
            used_chars += len(rag_header)
            for chunk in rag_results:
                file_ = chunk.get("file", "")
                ext = chunk.get("ext", "")
                lang = ext.lstrip(".") if ext else ""
                score = chunk.get("score", 0.0)
                text = chunk.get("text", "")
                snippet = (
                    f"\n### `{file_}` (relevance={score:.2f})\n"
                    f"```{lang}\n{text}\n```\n"
                )
                if used_chars + len(snippet) > _CONTEXT_CHAR_BUDGET:
                    break
                context_parts.append(snippet)
                used_chars += len(snippet)

    # ── Symbol index ──────────────────────────────────────────────────
    if symbol_lines:
        sym_section = "\n## Symbol Index\n\n" + "\n".join(symbol_lines)
        remaining = _CONTEXT_CHAR_BUDGET - used_chars
        if remaining > 500:
            if len(sym_section) > remaining:
                sym_section = sym_section[:remaining] + "\n*[Symbol index truncated]*"
            context_parts.append(sym_section)

    context = "\n\n".join(context_parts)
    return f"{system_prompt}\n\n{context}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_ask(
    question: str,
    repo_root: Path,
    output_dir: Path,
    llm_config: LLMConfig | None = None,
) -> str:
    """Answer *question* grounded in the knowledge store.

    Args:
        question: Free-text question from the user.
        repo_root: Absolute path to the repository.
        output_dir: `.rekipedia/` directory containing store.db + wiki/.
        llm_config: LLM settings; defaults to LLMConfig().

    Returns:
        The assistant's answer as a Markdown string.

    Raises:
        RuntimeError: If no successful scan exists for the repo.
    """
    llm_config = llm_config or LLMConfig()
    _verify_scan(output_dir, repo_root)
    full_system = _build_full_system(question, output_dir, llm_config)
    client = LLMClient(llm_config)
    return client.call(question, system=full_system)


def stream_ask(
    question: str,
    repo_root: Path,
    output_dir: Path,
    llm_config: LLMConfig | None = None,
) -> Iterator[str]:
    """Answer *question* grounded in the knowledge store, streaming tokens.

    Identical to :func:`run_ask` except the final LLM call uses streaming
    and yields text chunks instead of returning a single string.
    """
    llm_config = llm_config or LLMConfig()
    _verify_scan(output_dir, repo_root)
    full_system = _build_full_system(question, output_dir, llm_config)
    client = LLMClient(llm_config)
    return client.stream(question, system=full_system)
