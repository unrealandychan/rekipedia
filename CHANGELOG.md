# Changelog

All notable changes to this project will be documented in this file.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [0.8.0] — 2026-05-16

### Added — Issue #94: Agentic ReAct Ask

- `reki ask --agentic` / `close-wiki ask --agentic` flag — enables a ReAct
  tool-calling loop instead of single-shot RAG stuffing.
- Up to 5 LLM→tool→LLM iterations before a forced final answer.
- **Four tools exposed to the LLM:**
  - `search_code(query)` — semantic vector search over wiki chunks
  - `get_symbol(name)` — look up a function / class / variable by name
  - `get_page(slug)` — fetch a full wiki page by slug (fuzzy match)
  - `get_relationships(symbol)` — retrieve all dependency edges for a symbol
- `LLMClient.call_with_tools()` — new multi-turn tool-call method wrapping
  litellm / go-openai function-calling APIs.
- `SqliteStore.search_symbols()` — filtered symbol lookup (Python + Go).
- `SqliteStore.get_relationships()` / `GetRelationshipsBySymbol()` (Go) —
  dependency edge retrieval.
- `agentic_ask.py` + `agentic_ask.go` — orchestration layer.
- `REKIPEDIA_AGENTIC=1` env var as alternative to `--agentic` flag.
- 10 new unit tests covering all tool schemas, executor dispatch, and
  end-to-end loop behaviour.

### Changed

- `ask.go` (Go CLI) — `askFlags` extended with `agentic bool`.
- `ask.py` (Python CLI) — `--agentic` option added with rich indicator.

---

## [0.7.3] — prior

- SQLite batch commits + PRAGMA tuning for faster scans.
- ThreadPoolExecutor parallel SHA-256 hashing.
- FAISS cache (O(1) MMR lookup).
- BM25 IDF optional param backward compat fix.
- Go shard ID rune overflow fix (idx ≥ 10).
- `LLMClient.stream()` dead code cleanup.
