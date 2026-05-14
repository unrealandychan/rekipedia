# close-wiki

> Your AI tech lead — always available, always up to date.

close-wiki scans any repository into a portable SQLite knowledge store and gives every developer on the team an LLM-powered tech lead they can ask anything: _"How does the auth flow work?", "What's the fastest way to add a new API endpoint?", "What broke the payment service last week?"_

No hallucinations, no guessing — every answer is grounded in your actual codebase.

### Key features
- **Agentic wiki orchestration**: `PlannerAgent` designs the wiki structure dynamically based on your repo
- **Page importance scoring**: planner assigns each page an importance score (0–100); nav sidebar sorts by priority
- **DeepWiki-style sections**: pages grouped into logical sections (`getting-started`, `architecture`, `core-components`, etc.)
- **Context slicing**: each page only receives the data it needs (~40–60% token reduction vs fixed-layout approach)
- **Hybrid RAG Q&A**: FAISS-indexed code chunks + wiki pages give the LLM full codebase context when answering questions
- **Embed provider choice**: `--embed-provider openai|ollama|azure|...` — any litellm-compatible embedding model
- **Wiki export**: bundle to a single Markdown file, ZIP archive, or structured JSON (`close-wiki export`)
- **Incremental updates**: only re-processes changed files after the first scan
- **Grounded Q&A**: answers cite real file paths and line numbers — no hallucinations

## Quick start

### via npm / npx (no install required)

```bash
npx close-wiki init .
npx close-wiki scan .
```

### via uv / uvx (no install required)

```bash
uvx close-wiki init .
uvx close-wiki scan .
```

### Permanent install

```bash
# Python
uv tool install close-wiki
# or
pip install close-wiki

# Node (adds global `close-wiki` binary that delegates to Python)
npm install -g close-wiki
```

---

## Commands

| Command | Description |
|---|---|
| `close-wiki init [REPO]` | Scaffold `.close-wiki/` with `config.yml` and update `.gitignore` |
| `close-wiki scan [REPO]` | Full analysis — extracts symbols, synthesises wiki pages, exports JSON |
| `close-wiki update [REPO]` | Incremental refresh — re-extracts only changed files, keeps the rest |
| `close-wiki ask [QUESTION]` | Interactive Q&A REPL — streaming answers, Ctrl+C to quit |
| `close-wiki serve [REPO]` | Start a local web UI to browse wiki pages and ask questions |
| `close-wiki embed [REPO]` | Build (or rebuild) the FAISS semantic search index for hybrid RAG Q&A |
| `close-wiki export [REPO]` | Bundle the wiki to a single file (`--format md\|zip\|json`) |

---

## LLM configuration

After running `close-wiki init`, edit `.close-wiki/config.yml`:

```yaml
version: 1
ignore:
  - .git
  - node_modules
  - __pycache__
  - .close-wiki
languages:
  - python
  - typescript
llm:
  model: ollama/llama4        # any litellm model string
  api_key: ""                 # or set CLOSE_WIKI_API_KEY env var
  base_url: ""                # for local / self-hosted endpoints
  temperature: 0.2
```

### Supported providers (via [litellm](https://docs.litellm.ai))

| Provider | Example model string |
|---|---|
| Ollama (local, free) | `ollama/llama4` |
| OpenAI | `gpt-5.5` |
| Anthropic | `claude-opus-4-6` |
| Google Gemini | `gemini/gemini-3.0-pro` |
| Any OpenAI-compatible | set `base_url` in config |

### Runtime overrides (env vars)

```bash
export CLOSE_WIKI_MODEL=gpt-5.5
export CLOSE_WIKI_API_KEY=sk-...
export CLOSE_WIKI_BASE_URL=https://my-proxy/v1
```

---

## Output

`close-wiki scan` writes everything to `.close-wiki/` inside your repo:

```
.close-wiki/
├── config.yml              # your settings (committed)
├── store.db                # SQLite knowledge store (git-ignored)
├── scan_meta.json          # last scan metadata (model, timestamp, file count)
├── wiki/                   # generated Markdown pages (3–15 pages, dynamically planned)
│   ├── index.md
│   ├── architecture-overview.md
│   ├── repository-structure.md
│   └── ... (pages vary by repo)
├── rag/                    # RAG index (git-ignored)
│   ├── index.faiss         # FAISS flat L2 index
│   └── chunks.json         # source code chunks + metadata
├── diagrams/               # Mermaid diagram files
│   ├── module-graph.md
│   └── class-hierarchy.md
└── exports/                # JSON exports
    ├── symbols.json
    ├── relationships.json
    └── manifest.json       # run summary + metadata + page importance scores
```

Dynamically generates 3–15 wiki pages based on repo complexity (powered by PlannerAgent).

The wiki structure is designed dynamically by `PlannerAgent` based on what's actually present in your repo:

| Section | Example pages | When generated |
|---|---|---|
| Getting Started | index, installation, quick-start | Always |
| Architecture | architecture-overview, data-flow, repository-structure | ≥3 modules |
| Core Components | One page per major module | ≥2 modules |
| API Reference | cli-reference, python-api, rest-api | CLI/HTTP handlers found |
| Development | testing, contributing, ci-cd | Test files found |
| Ecosystem | integrations, deployment | ≥3 external deps |

### Scan options

```bash
# Use a specific LLM model
close-wiki scan . --model gpt-5.5

# Skip Docker (run extractors in-process)
close-wiki scan . --no-docker

# Write output to a custom directory
close-wiki scan . --output-dir /tmp/wiki-output

# Enable debug logging (litellm, HTTP, full tracebacks)
close-wiki scan . --verbose

# Auto-embed for RAG after scan
close-wiki scan . --embed-model text-embedding-3-small --embed-provider openai
```

### RAG / semantic search

`close-wiki ask` uses **hybrid retrieval** — wiki pages + FAISS-indexed code chunks — to answer questions with full codebase context.

```bash
# Build or rebuild the FAISS index
close-wiki embed .

# Custom embedding model (any litellm-compatible model)
close-wiki embed . --model text-embedding-3-small --provider openai
close-wiki embed . --model nomic-embed-text --provider ollama

# Or set via env vars
export CLOSE_WIKI_EMBED_MODEL=nomic-embed-text
export CLOSE_WIKI_EMBED_PROVIDER=ollama
close-wiki scan .   # auto-embeds after scan if env vars are set
```

The FAISS index is saved to `.close-wiki/rag/index.faiss` and chunked source code to `.close-wiki/rag/chunks.json`.

### Export the wiki

```bash
# Single combined Markdown file (default)
close-wiki export . --format md --output ./wiki-export.md

# ZIP archive (one .md per page + manifest.json)
close-wiki export . --format zip --output ./wiki.zip

# Structured JSON (all pages + metadata)
close-wiki export . --format json --output ./wiki.json
```

### Incremental update

After the first scan, `close-wiki update` only re-processes files whose SHA-256 has changed. Unchanged symbols and relationships are carried forward from the previous run — the wiki is refreshed in seconds.

```bash
close-wiki update .                    # auto-detect changed files
close-wiki update . --no-docker        # skip Docker
```

If no previous scan is found, `update` automatically falls back to a full scan.

### Ask the wiki

```bash
# Start interactive Q&A session (streams answers, Ctrl+C to quit)
close-wiki ask
close-wiki ask --repo ./my-project
close-wiki ask --model gpt-4o

# Single-shot mode (backward compat)
close-wiki ask -q "How does the auth flow work?"
```

Answers are grounded **entirely** in your wiki pages and symbol index — the LLM cannot hallucinate details that aren't in the scanned knowledge store. Answers are streamed token-by-token with a spinner while waiting.

#### 🤖 Agentic mode (ReAct tool-calling loop) — v0.8.0+

```bash
# Agentic: LLM can call tools (search_code, get_symbol, get_page, get_relationships)
# before returning a final answer — much better for multi-hop questions.
close-wiki ask --agentic -q "Which functions does the auth middleware call?"
reki ask --agentic                     # Python CLI
REKIPEDIA_AGENTIC=1 close-wiki ask -q "Trace the data flow from API request to DB write"
```

In agentic mode the LLM runs up to **5 ReAct iterations** — each iteration may call one or more tools to gather context before synthesising the final answer. This is significantly more accurate for questions that require traversing multiple files or following dependency chains.

Not happy with a generated page? See **[docs/customizing.md](docs/customizing.md)** — you can pin pages, override prompts, change the writing style, or add your own pages that scans will never touch.

### Serve the wiki

```bash
close-wiki serve .                     # opens browser at http://127.0.0.1:7070
close-wiki serve . --port 8080         # custom port
close-wiki serve . --no-browser        # don't auto-open browser
```

- Browse generated wiki pages in a dark-themed web UI
- Ask questions with the same grounded Q&A (answers streamed via the web)
- Q&A history stored in SQLite

---

## Prerequisites

- **Python ≥ 3.11** (or `uv` which manages its own Python)
- **Docker** — optional; used for isolated extraction. Falls back to in-process runner automatically if Docker is not available (`--no-docker` forces in-process mode)

---

## Using close-wiki with AI coding agents

close-wiki ships a **Hermes agent skill** (`close-wiki-agent-skill.md`) that teaches AI assistants (Copilot, Claude Code, Codex) to use close-wiki as their codebase intelligence layer:

1. Copy `close-wiki-agent-skill.md` into your Hermes skills directory
2. Any agent with the skill loaded will automatically scan + query close-wiki before diving into source files
3. Dramatically reduces context window usage for large codebases

---

## Development

```bash
# Install all deps
make dev

# Run tests
make test

# Lint
make lint

# Build wheel + npm tarball
make build
```

### Release

```bash
PYPI_TOKEN=*** NPM_TOKEN=*** make release

# Full release: build + tag + push + PyPI + npm
make release-all PYPI_TOKEN=*** NPM_TOKEN=***
# With version bump
make release-all PYPI_TOKEN=*** NPM_TOKEN=*** VERSION=0.5.0
```

---

## License

MIT — see [LICENSE](LICENSE).
