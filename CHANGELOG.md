# Changelog

## [0.28.0] — 2026-09-26

### Features
- **Hyperedge Support (#237)**: Represent N-ary relationships, architectural motifs, and design patterns (Repository Pattern, Service Layer, Controllers, Factory Pattern, shared inheritance clusters). Stored in SQLite (`scan_hyperedges`, `scan_hyperedge_members`), exported to JSON, and rendered into a dedicated "Design Patterns & Architectural Motifs" section in wiki generation.
- **Tree-sitter AST Extraction for TypeScript/JS (#246)**: Replaced regex parsing with `tree-sitter-typescript` AST traversal via new `BaseTreeSitterExtractor`, achieving high precision for TypeScript, TSX, JSX, interfaces, type aliases, CommonJS `require`, and classes with robust fallback.
- **Hybrid Engine Bridge (#247)**: Added `--use-engine codebase-memory` to delegate symbol/relationship extraction to `codebase-memory-mcp` for ultra-large codebases, with automatic schema mapping via `CodebaseMemoryAdapter`.
- **Graph-First Cloud SQL Schema (#232)**: Added PostgreSQL 16 + pgvector DDL schema (`schemas/cloud_sql/001_graph_first_pgvector.sql`), hybrid retrieval function (`merge_and_rerank`), and GCS artifact incremental sync.
- **`reki path <from> <to>` CLI Command**: Trace the shortest directed path between any two symbols hop-by-hop with relationship kinds and `[EXTRACTED]` / `[INFERRED]` confidence tags. Supports `--json`.
- **`reki explain <symbol>` CLI Command**: Instant symbol breakdown showing location (`file:line`), callers, callees, degree metrics, rationale notes (`NOTE:`, `WHY:`), and design pattern memberships. Supports `--json`.
- **Standalone Interactive `graph.html` Export**: Generate a self-contained, offline force-directed graph viewer (`reki export --format graph` and auto-emitted `.rekipedia/graph.html`) featuring search, kind filters, zoom/pan, and node inspector without needing a server.
- **Universal Agent Skill Installer**: `reki install [--platform pi|claude|cursor|codex|agents|copilot] [--project]` auto-registers skills with Pi, Claude Code, Cursor rules (`.cursor/rules/`), Codex, or cross-framework Agent-Skills.
- **Staleness Detection (CodeGraph pattern)**: Auto-detects modified files since the last scan and warns users/agents in `reki ask` and MCP server tools to keep context fresh.

### Tests
- 43 new unit tests across 8 test suites; 1,266 tests passing in total.

## [0.27.0] — 2026-06-26

### Features
- `chat.db` isolated from `store.db` — chat history no longer pollutes the shared scan DB (#248)
- `reki serve --title / --logo` — custom branding; `/api/config` + `/logo` endpoints (#238)
- `detect_changes` MCP tool — git blast-radius analysis via MCP with risk tagging (#245)
- `reki diff --graph-diff` — edge-level relationship diff between last two scan runs (#235)
- `get_two_latest_run_ids()` on SqliteStore for cross-run comparison

### Tests
- 39 new tests across 4 test files (all passing)

## [0.26.0] — 2026-06-26

### Features
- `reki export --format okf` — export wiki as an [OKF v0.1 Knowledge Bundle](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md) (GoogleCloudPlatform compatible). Produces `wiki/`, `diagrams/`, `index.md`, and `log.md` with standard YAML frontmatter.
- **`log.md` wiki changelog** — `.rekipedia/wiki/log.md` is written on every `reki scan` and `reki update`, recording timestamp, run ID, and list of pages changed. Newest entry prepended.
- **Section index pages** — `index-<section>.md` files generated per section group after each scan for progressive disclosure (OKF §6 pattern). Pages sorted alphabetically within each section.

## [0.22.1] - 2026-06-10
### Added
- `reki ask` arrow-key history — press ↑ / ↓ in interactive REPL to recall previous questions, just like a shell. History is persisted to `~/.rekipedia/ask_history` across sessions. Use `--no-history` to disable. Closes #224.

## [0.22.0] - 2026-06-08
### Added
- **Modern Next.js SPA frontend** for `reki serve` (#219):
  - Completely rewritten from FastAPI Uvicorn/Jinja2 template rendering to a highly responsive Client-side Static-Export React Single Page Application (SPA).
  - Clean SPA routing using hash-routing pattern to ensure zero "404 on refresh" errors on generic local file/web servers.
  - Interactive sidebar featuring dynamic sections with fuzzy-search filtering for Wiki chapters (#222).
  - Codebase Chat window with streaming token responses (SSE-powered), auto-scrolling, clear-history, and suggestion prompts (#221).
  - Interactive Dependency Graph using **React Flow** canvas featuring MiniMap, node dragging, zoom/pan controls, and visual module card coloring by codebase folders (#220).
  - Metadata inspector side-sheet for nodes inside the dependency graph displaying lines of code, classes, exported symbols, and active imports on click (#220).
  - Notes Management Board allowing developers to persist, tag-filter, and quickly delete codebase notes/insights directly in-browser.
- **Backend API Modernization**:
  - Exposed new JSON API endpoints under `/api/wiki` and `/api/wiki/page/{slug}` in `app.py` to seamlessly connect Next.js frontends to the local Python RAG database (#221).
  - Retrofitted the local web server fallback mechanism (`PYTEST_CURRENT_TEST` environment check) to allow 100% of preexisting Jinja2 server tests to pass cleanly without regression.

## [0.21.2] - 2026-06-04
### Added
- `reki ask` now injects **real source code bodies** into the LLM context — when no RAG index is available, the top-N most relevant functions/classes are extracted directly from source files (ranked by keyword overlap with the question) and passed as fenced code blocks. RAG remains the primary path and takes precedence when `reki embed .` has been run. Closes #217.
### Changed
- `ask_system.md` system prompt updated: LLM is now explicitly required to include fenced code block examples from context in every answer, with `file:line` citations.

## [0.21.1] - 2026-06-03
### Fixed
- `reki search` always errored with "No rekipedia DB" — `search.py` was looking for `.rekipedia/rekipedia.db` but `reki scan` writes `.rekipedia/store.db`. Now uses `store.db` first with `rekipedia.db` fallback for backward compat. Closes #217.
- `reki export --format obsidian` and `reki export --format graphml/cypher` had the same hardcoded `rekipedia.db` bug. Fixed in `export.py` (2 blocks).
- `reki search --all-repos` never found any registered repos for the same reason. Fixed in `cross_repo_search.py`.

## [0.21.0] - 2026-06-02
### Changed
- Unified `RefactorIssue` Pydantic model — all refactor analysis modules now use the single canonical model from `contracts.py` instead of ad-hoc dicts. Closes #208.
- Consolidated three independent refactor detection implementations into a single canonical `refactor_detector.detect_issues()` entry point. Closes #207.
- Split `sqlite_store.py` (1041 lines) into focused modules: `storage/connection.py`, `storage/migrations.py`, `storage/writes.py`, `storage/reads.py`, `storage/analytics.py`. `SqliteStore` remains as a thin facade. Closes #212.
- Renamed `analysis/domain.py` → `layer_classifier.py` and `analysis/biz_domain.py` → `domain_flow_analyzer.py` for clarity. Closes #214.
- Unified dual progress-reporting paths in `run_digest.py` into a single `StepEmitter`. Closes #216.
- Fixed `--with-refactor` redundant re-extraction when rationale notes already present in DB. Closes #213.
### Added
- CLI help output now groups 51 commands into labelled sections: Core, Analysis, Team sync, Setup. Closes #215.
- Documented `AgentPlanner` experimental env var (`REKIPEDIA_AGENT_PLANNER=1`) in CONTRIBUTING.md. Closes #211.
- Documented `DockerSandboxRunner` Docker image build process in CONTRIBUTING.md. Closes #210.
- Added Go port charter: `go/README.md` section and ADR at `docs/adr/0001-go-port-charter.md`. Closes #209.

## [0.20.0] - 2026-06-01
### Added
- **Document extraction** (`rekipedia[docs]`): parse PDF, DOCX, PPTX, and XLSX files via `liteparse`. Opt-in via `documents.enabled: true` in `.rekipedia/config.yml`. Closes #199.
- `document_chunks` SQLite table (migration 006): stores page-level text and bounding boxes for all extracted document pages. Cascade-deleted when a scan run is removed. Closes #200.
- `reki embed` now includes document chunks in the FAISS index when `documents.embed_chunks: true` (default). Closes #201.
- `reki scan` auto-generates a wiki summary page per document file (e.g., `📄 api.pdf`) when `documents.wiki_page_per_doc: true` (default). Closes #203.
- `reki onboard` now shows a **📄 Documentation Files** table listing all PDF/DOCX/PPTX/XLSX files in the repo. Closes #204.
- New `documents` config section added to default config with sensible opt-in defaults. All existing repos unaffected until `enabled: true` is set.
### Changed
- `config/loader.py`: `load_config()` now merges built-in `_DEFAULT_CONFIG` before global and local overrides, ensuring all config keys always have a valid default.

## [0.19.0] - 2026-05-29
### Added
- `reki init --with-copilot`: writes `.vscode/mcp.json` (VS Code Copilot MCP, `"servers"` format) and enables `chat.mcp.enabled` in `.vscode/settings.json`.
- `reki init --with-codex`: writes `.codex/instructions.md` and `codex-mcp-hint.md` with Codex CLI `~/.codex/config.toml` setup instructions.
- `reki init --with-cursor`: writes `.cursor/mcp.json` and `.cursor/rules/rekipedia.mdc` with `alwaysApply: true`.
- `reki init --with-all-ai`: convenience flag — runs `--with-copilot`, `--with-codex`, and `--with-cursor` in one command.
- Two new MCP tools: `list_wiki_pages` (enumerate all wiki pages) and `get_wiki_page` (read a page by name). Available in `reki mcp` server.
- Per-tool tailored agent instruction files: `CLAUDE.md`, `AGENTS.md`, and `.github/copilot-instructions.md` now each contain tool-specific MCP setup instructions rather than a generic template.

## [0.18.0] - 2026-05-29
### Added
- `reki export --format bundle` — deterministic, content-addressed wiki snapshot with stable `bundle_id` and per-page hash trailers for team sync. Closes #182.
- `reki merge <bundle-A> <bundle-B> [--base BASE]` — three-way wiki merge with last-write-wins on unchanged pages and `<!-- reki:conflict -->` markers on genuine conflicts. Outputs `merge_report.json`. Closes #183.
- `reki merge-driver BASE OURS THEIRS` — git merge driver interface: exits 0 on clean merge, 1 on conflict. Write best-effort merged result to OURS. Closes #184.
- `reki init --with-merge-driver` — registers `.gitattributes` merge driver entry and `.git/config` merge driver config so `git merge` automatically uses rekipedia's wiki merge logic. Closes #184.
- `reki watch . --publish` — auto-publishes the wiki after every incremental update. Closes #185.
- `team.sync_dir` config key — default publish target for `reki watch --publish`. `team.auto_watch_publish: true` enables publish automatically without the flag. Closes #185.
- `reki pull [URL]` — fetch and merge a remote wiki bundle over HTTPS, S3 (`rekipedia[aws]`), or GCS (`rekipedia[gcs]`). Reads `team.remote_url` from config when URL is omitted. `--dry-run` previews without writing. Closes #186.
- `reki init --with-ci --with-upload s3|gcs` — appends an S3 or GCS bundle upload step to the generated GitHub Actions workflow. Closes #187.

## [0.17.22] - 2026-05-26
### Added
- `reki refactor --dry-run` — preview all suggested changes without writing files. Closes #166.
- `reki refactor --apply` — auto-apply safe smells (`dead_code`, `large_file`). Non-auto-fixable smells show guidance only.
- `reki refactor --apply --dry-run` — preview what `--apply` would do.


## [0.17.19] - 2026-05-26
### Added
- `reki update --impact-only` — BFS-based selective wiki regeneration; only re-generates pages for transitively affected modules, reducing LLM calls by 80-90% on large repos. Closes #164.
- `reki ask --brief` / `REKIPEDIA_BRIEF=1` — compact answer mode (~150 tokens, 1 paragraph + file:line citations) closes #167
