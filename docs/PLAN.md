# rekipedia — Product Plan

> Living document. Update this whenever a phase completes or goals shift.

---

## Vision

rekipedia turns any repository into a self-maintaining knowledge base. Every developer gets an always-up-to-date AI tech lead they can ask anything about the codebase — grounded entirely in the real source, never hallucinated.

---

## Phases

### Phase 1 — Foundation ✅ COMPLETE

**Goal:** project skeleton, packaging, core infrastructure, 12-table SQLite schema.

| Item | Status |
|---|---|
| `rekipedia init` — scaffold `.rekipedia/config.yml`, update `.gitignore` | ✅ |
| SQLite store (`sqlite-utils`, WAL mode, migration runner) | ✅ |
| LLM client (litellm, env-var overrides) | ✅ |
| Snapshotter — SHA-256 file walker + pathspec ignore | ✅ |
| Pydantic v2 contracts (`AnalysisResult`, `Symbol`, `Relationship`, `Shard`, `FileManifest`, `LLMConfig`) | ✅ |
| JSON Schema for Docker sandbox contract | ✅ |
| Python package (`hatchling`, `pip install rekipedia`) | ✅ |
| npm shim (`npx rekipedia` → `uvx` → Python) | ✅ |
| Makefile targets: `install`, `dev`, `test`, `lint`, `build`, `release-*` | ✅ |
| 12 passing tests | ✅ |

---

### Phase 2 — Repository Analysis & Wiki Generation ✅ COMPLETE

**Goal:** `rekipedia scan` works end-to-end; produces 5 wiki pages, Mermaid diagrams, `manifest.json`, populates `knowledge.db`.

| Item | Status |
|---|---|
| Python AST extractor | ✅ |
| TypeScript/JS regex extractor | ✅ |
| Config extractor (package.json, pyproject.toml, Dockerfile, CI yml) | ✅ |
| `ShardPlanner` — token-budget-aware grouping | ✅ |
| `Dockerfile.sandbox` — `python:3.12-slim`, `--network none` | ✅ |
| `DockerSandboxRunner` + `LocalRunner` fallback | ✅ |
| `PageBuilder` — LLM-driven 5-page wiki (index, architecture, core-modules, build-and-deploy, testing-strategy) | ✅ |
| `DiagramBuilder` — Mermaid flowchart + classDiagram | ✅ |
| `MarkdownExporter` — `wiki/*.md`, `diagrams/*.md`, respects `pin: true` | ✅ |
| `JsonExporter` — `exports/symbols.json`, `exports/relationships.json`, `exports/manifest.json` | ✅ |
| `rekipedia scan` CLI (`--no-docker`, `--output-dir`, `--model`) | ✅ |
| `scan_*` tables in SQLite (TEXT pk, no conflict with Phase 1 schema) | ✅ |
| `prompt_overrides` and `exclude_pages` config keys | ✅ |
| 37 new tests (49 total) | ✅ |

**Output structure:**
```
.rekipedia/
├── store.db
├── wiki/
│   ├── index.md
│   ├── architecture.md
│   ├── core-modules.md
│   ├── build-and-deploy.md
│   └── testing-strategy.md
├── diagrams/
│   ├── module-graph.md
│   └── class-hierarchy.md
└── exports/
    ├── symbols.json
    ├── relationships.json
    └── manifest.json
```

---

### Phase 3 — Incremental Update ✅ COMPLETE

**Goal:** `rekipedia update` re-extracts only changed files and refreshes the wiki in seconds, not minutes.

| Item | Status |
|---|---|
| `SqliteStore.get_latest_run_id(repo_path)` — find last successful run | ✅ |
| `SqliteStore.get_files_for_run(run_id)` — fetch stored file hashes | ✅ |
| `SqliteStore.copy_unchanged_symbols(from_run_id, to_run_id, exclude_paths)` | ✅ |
| `SqliteStore.copy_unchanged_relationships(from_run_id, to_run_id, exclude_paths)` | ✅ |
| `run_update()` pipeline — diff-based re-extraction + carry-forward | ✅ |
| Auto-fallback to full scan when no prior run exists | ✅ |
| `rekipedia update` CLI (`--no-docker`, `--output-dir`, `--model`) | ✅ |
| `tests/test_update.py` | ✅ |

**How it works:**
1. Find the last successful scan for this repo path
2. Snapshot the repo (current file hashes)
3. Diff: identify changed / deleted files
4. If nothing changed → report "up to date" and exit early
5. Create a new run; re-extract only the changed shards
6. Carry forward symbols & relationships from unchanged files (raw SQL copy)
7. Re-synthesize all wiki pages (full context always needed)
8. Export markdown + JSON

---

### Phase 4 — Grounded Q&A ✅ COMPLETE

**Goal:** `rekipedia ask "How does auth work?"` returns a grounded, cited answer from the wiki + symbol index — zero hallucinations.

| Item | Status |
|---|---|
| `ask_system.md` — system prompt instructing LLM to cite sources | ✅ |
| `run_ask()` pipeline — context assembly + LLM call | ✅ |
| Context builder: wiki pages + symbol list + relationships summary | ✅ |
| Token-budget truncation (keeps context within model limits) | ✅ |
| `rekipedia ask QUESTION` CLI (rich output, source citations) | ✅ |
| `tests/test_ask.py` | ✅ |

**How it works:**
1. Locate the latest successful scan for the repo
2. Load all wiki pages from `wiki/*.md`
3. Load symbol index from `exports/symbols.json`
4. Assemble a context string (wiki pages first, then symbol list), truncated to fit token budget
5. Send to LLM with a strict "ground your answer in the context below" system prompt
6. Print the streamed response with source attributions

---

## Architecture Overview

```
rekipedia scan / update
        │
        ▼
 Snapshotter          ← SHA-256 file walk (pathspec ignore)
        │
        ▼
 ShardPlanner         ← group by top-dir, split on token budget
        │
        ▼
 DockerSandboxRunner  ← `--network none` container (static analysis only)
   └─ LocalRunner     ← in-process fallback / --no-docker
        │
        ▼
 SqliteStore          ← scan_* tables (TEXT pk, WAL mode)
        │
        ├── PageBuilder     ← LLM-driven Markdown pages (HOST)
        ├── DiagramBuilder  ← pure-Python Mermaid generation
        ├── MarkdownExporter
        └── JsonExporter

rekipedia ask
        │
        ▼
 SqliteStore + wiki/*.md  ← context assembly
        │
        ▼
 LLMClient (litellm)      ← grounded answer, host-side
```

---

## Design Invariants

- **LLM calls happen on the HOST** — Docker sandbox is `--network none` and performs only static analysis.
- **`scan_*` table prefix** — Phase 2+ data uses TEXT PKs; avoids conflicts with Phase 1 INTEGER PK schema.
- **`pin: true` frontmatter** — MarkdownExporter never overwrites pinned pages.
- **`LocalRunner` fallback** — If Docker is unavailable or `--no-docker` is passed, extraction runs in-process.
- **`prompt_overrides` / `exclude_pages`** — Live in `config.yml`; honoured by `PageBuilder`.
- **Incremental update carry-forward** — Unchanged file symbols/relationships are copied via raw SQL, not re-extracted.

---

## Configuration Reference

```yaml
# .rekipedia/config.yml
version: 1
ignore:
  - .git
  - node_modules
  - __pycache__
languages:
  - python
  - typescript
llm:
  model: ollama/llama4          # any litellm model string
  api_key: ""                   # or REKIPEDIA_API_KEY env var
  base_url: ""                  # for local / self-hosted endpoints
  temperature: 0.2

# Phase 3+
prompt_overrides:
  architecture: |
    Focus on the event-driven subsystems only.
  core-modules: |
    Only document public-facing classes.

exclude_pages:
  - testing-strategy            # page slugs to never generate
```

---

## Roadmap (Future)

| Phase | Feature | Notes |
|---|---|---|
| 5 | `rekipedia serve` — local web UI | Read-only wiki browser, search, ask box |
| 6 | Multi-repo federation | Cross-repo symbol references |
| 7 | CI integration | GitHub Action that runs `update` on push |
| 8 | Vector search for `ask` | Embedding index for large repos (>100K symbols) |
| 9 | Language servers | Go, Rust, Java extractors |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python ≥ 3.11 |
| Packaging | hatchling (PyPI) + npm shim |
| CLI | click ≥ 8.1 |
| UI | rich ≥ 13.0 |
| LLM | litellm ≥ 1.30 (OpenAI, Anthropic, Gemini, Ollama, …) |
| Data contracts | pydantic ≥ 2.0 |
| Storage | sqlite-utils ≥ 3.35, WAL mode |
| Sandbox | Docker (`python:3.12-slim`, `--network none`) |
| Ignore patterns | pathspec ≥ 0.12 |
| Tests | pytest |
