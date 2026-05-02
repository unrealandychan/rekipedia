# rekipedia

> Your AI tech lead — always available, always up to date.

rekipedia scans any repository into a portable SQLite knowledge store and gives every developer on the team an LLM-powered tech lead they can ask anything: _"How does the auth flow work?", "What's the fastest way to add a new API endpoint?", "What broke the payment service last week?"_

No hallucinations, no guessing — every answer is grounded in your actual codebase.

### Key features
- **Agentic wiki orchestration**: `PlannerAgent` designs the wiki structure dynamically based on your repo
- **Page importance scoring**: planner assigns each page an importance score (0–100); nav sidebar sorts by priority
- **DeepWiki-style sections**: pages grouped into logical sections (`getting-started`, `architecture`, `core-components`, etc.)
- **Context slicing**: each page only receives the data it needs (~40–60% token reduction vs fixed-layout approach)
- **Hybrid RAG Q&A**: FAISS-indexed code chunks + wiki pages give the LLM full codebase context when answering questions
- **Embed provider choice**: `--embed-provider openai|ollama|azure|...` — any litellm-compatible embedding model
- **Wiki export**: bundle to a single Markdown file, ZIP archive, or structured JSON (`rekipedia export`)
- **Incremental updates**: only re-processes changed files after the first scan
- **Grounded Q&A**: answers cite real file paths and line numbers — no hallucinations

## Quick start

### via npm / npx (no install required)

```bash
npx rekipedia init .
npx rekipedia scan .
```

### via uv / uvx (no install required)

```bash
uvx rekipedia init .
uvx rekipedia scan .
```

### Permanent install

```bash
# Core (scan + serve + ask)
pip install rekipedia
# or
uv tool install rekipedia

# With RAG support (semantic embed + search — needs faiss-cpu + numpy ~100MB)
pip install "rekipedia[rag]"

# Homebrew (Go single binary — no Python needed)
brew tap unrealandychan/tap
brew install rekipedia
```

---

## Commands

| Command | Description |
|---|---|
| `rekipedia init [REPO]` | Scaffold `.rekipedia/` with `config.yml` and update `.gitignore` |
| `rekipedia scan [REPO]` | Full analysis — extracts symbols, synthesises wiki pages, exports JSON |
| `rekipedia update [REPO]` | Incremental refresh — re-extracts only changed files, keeps the rest |
| `rekipedia ask [QUESTION]` | Interactive Q&A REPL — streaming answers, Ctrl+C to quit |
| `rekipedia serve [REPO]` | Start a local web UI to browse wiki pages and ask questions |
| `rekipedia embed [REPO]` | Build (or rebuild) the FAISS semantic search index for hybrid RAG Q&A |
| `rekipedia export [REPO]` | Bundle the wiki to a single file (`--format md\|zip\|json`) |

---

## LLM configuration

After running `rekipedia init`, edit `.rekipedia/config.yml`:

```yaml
version: 1
ignore:
  - .git
  - node_modules
  - __pycache__
  - .rekipedia
languages:
  - python
  - typescript
llm:
  model: ollama/llama4        # any litellm model string
  api_key: ""                 # or set REKIPEDIA_API_KEY env var
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
export REKIPEDIA_MODEL=gpt-5.5
export REKIPEDIA_API_KEY=sk-...
export REKIPEDIA_BASE_URL=https://my-proxy/v1
```

---

## Output

`rekipedia scan` writes everything to `.rekipedia/` inside your repo:

```
.rekipedia/
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
rekipedia scan . --model gpt-5.5

# Skip Docker (run extractors in-process)
rekipedia scan . --no-docker

# Write output to a custom directory
rekipedia scan . --output-dir /tmp/wiki-output

# Enable debug logging (litellm, HTTP, full tracebacks)
rekipedia scan . --verbose

# Auto-embed for RAG after scan
rekipedia scan . --embed-model text-embedding-3-small --embed-provider openai
```

### RAG / semantic search

`rekipedia ask` uses **hybrid retrieval** — wiki pages + FAISS-indexed code chunks — to answer questions with full codebase context.

```bash
# Build or rebuild the FAISS index
rekipedia embed .

# Custom embedding model + provider
rekipedia embed . --model text-embedding-3-small --provider openai
rekipedia embed . --model nomic-embed-text --provider ollama

# If your embed provider uses a DIFFERENT API key from your main LLM:
rekipedia embed . --model text-embedding-3-small --provider openai
# set embed_api_key in config.yml, or:
export REKIPEDIA_EMBED_API_KEY=sk-your-openai-key

# Or configure everything in .rekipedia/config.yml:
# llm:
#   model: ollama/llama4          # main LLM (local)
#   embed_model: text-embedding-3-small
#   embed_provider: openai
#   embed_api_key: sk-xxx         # separate key for embed provider
#   embed_base_url: ""            # optional: custom endpoint

# Env var overrides (all optional):
export REKIPEDIA_EMBED_MODEL=nomic-embed-text
export REKIPEDIA_EMBED_PROVIDER=ollama
export REKIPEDIA_EMBED_API_KEY=sk-xxx
export REKIPEDIA_EMBED_BASE_URL=https://my-proxy.example.com/v1
```

The FAISS index is saved to `.rekipedia/rag/index.faiss` and chunked source code to `.rekipedia/rag/chunks.json`.

### Export the wiki

```bash
# Single combined Markdown file (default)
rekipedia export . --format md --output ./wiki-export.md

# ZIP archive (one .md per page + manifest.json)
rekipedia export . --format zip --output ./wiki.zip

# Structured JSON (all pages + metadata)
rekipedia export . --format json --output ./wiki.json
```

### Incremental update

After the first scan, `rekipedia update` only re-processes files whose SHA-256 has changed. Unchanged symbols and relationships are carried forward from the previous run — the wiki is refreshed in seconds.

```bash
rekipedia update .                    # auto-detect changed files
rekipedia update . --no-docker        # skip Docker
```

If no previous scan is found, `update` automatically falls back to a full scan.

### Ask the wiki

```bash
# Start interactive Q&A session (streams answers, Ctrl+C to quit)
rekipedia ask
rekipedia ask --repo ./my-project
rekipedia ask --model gpt-4o

# Single-shot mode (backward compat)
rekipedia ask -q "How does the auth flow work?"
```

Answers are grounded **entirely** in your wiki pages and symbol index — the LLM cannot hallucinate details that aren't in the scanned knowledge store. Answers are streamed token-by-token with a spinner while waiting.

Not happy with a generated page? See **[docs/customizing.md](docs/customizing.md)** — you can pin pages, override prompts, change the writing style, or add your own pages that scans will never touch.

### Serve the wiki

```bash
rekipedia serve .                     # opens browser at http://127.0.0.1:7070
rekipedia serve . --port 8080         # custom port
rekipedia serve . --no-browser        # don't auto-open browser
```

- Browse generated wiki pages in a dark-themed web UI
- Ask questions with the same grounded Q&A (answers streamed via the web)
- Q&A history stored in SQLite

---

## Prerequisites

- **Python ≥ 3.11** (or `uv` which manages its own Python)
- **Docker** — optional; used for isolated extraction. Falls back to in-process runner automatically if Docker is not available (`--no-docker` forces in-process mode)

---

## Using rekipedia with AI coding agents

rekipedia ships a **Hermes agent skill** (`rekipedia-agent-skill.md`) that teaches AI assistants (Copilot, Claude Code, Codex) to use rekipedia as their codebase intelligence layer:

1. Copy `rekipedia-agent-skill.md` into your Hermes skills directory
2. Any agent with the skill loaded will automatically scan + query rekipedia before diving into source files
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
