<div align="center">

<img src="https://capsule-render.vercel.app/api?type=waving&color=gradient&customColorList=6,11,20&height=170&section=header&text=rekipedia&fontSize=52&fontColor=ffffff&fontAlignY=38&desc=Turn+any+repo+into+an+AI-ready+knowledge+base&descAlignY=58&descSize=14" alt="Header"/>

[![PyPI](https://img.shields.io/badge/PyPI-rekipedia-3776AB?style=for-the-badge&logo=pypi&logoColor=white&labelColor=0d1117)](https://pypi.org/project/rekipedia/)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white&labelColor=0d1117)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-amber?style=for-the-badge&logo=open-source-initiative&logoColor=white&labelColor=0d1117)](LICENSE)
[![MCP](https://img.shields.io/badge/MCP-Compatible-8b5cf6?style=for-the-badge&logo=protocols.io&logoColor=white&labelColor=0d1117)](https://modelcontextprotocol.io)

</div>

---

# rekipedia

> **One scan. A living wiki. AI agents that actually know your code.**
>
> Parse any codebase into a structured SQLite knowledge store, auto-generate wiki pages, and expose everything via CLI and an MCP stdio server — with file:line citations and zero hallucinations.

[![PyPI version](https://img.shields.io/pypi/v/rekipedia.svg)](https://pypi.org/project/rekipedia/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![MIT License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

---

## Why rekipedia?

| Problem | rekipedia |
|---|---|
| "Where does the auth logic live?" | `reki ask "how does auth work?"` → `src/auth.py:42` |
| "What does this class or symbol do?" | `reki explain AuthService` → callers, callees, degrees, design pattern |
| "How does module A reach module B?" | `reki path App UserRepo` → shortest directed path hop-by-hop |
| Onboarding new devs takes days | `reki onboard .` generates a guided walkthrough in seconds |
| AI agents hallucinate about your codebase | `reki mcp` gives agents a grounded knowledge base with citations |
| Stale graph after file edits | Auto-staleness detection alerts agents when working tree changed |
| Refactor anxiety — will this break everything? | `reki hotspots` surfaces hub and bridge nodes before you touch anything |
| Interactive dependency exploration | `reki export . --format graph` → self-contained `graph.html` (zero server) |
| Wiki goes stale immediately | `reki watch .` auto-reindexes on every file save |

---

## ⚡ Quickstart

### Install

```bash
pip install rekipedia
# or: npx rekipedia
```

### Scan & Ask (with LLM)

```bash
export REKIPEDIA_MODEL=gemini/gemini-2.5-flash
export GOOGLE_API_KEY=...
reki scan .
reki ask "how does authentication work?"
```

### Scan without LLM (zero config, no API key)

```bash
reki scan . --no-llm
reki ask "what is the entry point?" --no-llm
```

---

## 🏗️ Architecture & Data Storage

```
.rekipedia/
│
├── store.db              # 🗃️ Structured SQLite graph
│   └── symbols, relationships, file manifests, scan history
│
├── rag/
│   └── faiss.index       # 🔍 Dense embedding vectors (FAISS / Qdrant / Chroma)
│
├── wiki/
│   └── *.md              # 📄 Auto-generated wiki pages per module
│
├── diagrams/
│   └── *.md              # 🏛️ Architecture diagrams & hotspot reports
│
└── config.yml            # ⚙️ Backend, LLM, and team-sync settings
```

### Storage at a Glance

| Layer | Format | Purpose | Size (typical 50k–200k LOC repo) |
|---|---|---|---|
| **SQLite** | `store.db` | Structured graph — symbols, callers, exact lookup | ~10–80 MB |
| **Vector** | `.rekipedia/rag/` | Dense embeddings for semantic / fuzzy search | ~50–500 MB |
| **Wiki** | `wiki/*.md` | Human-readable pages, git-publishable | ~1–5 MB |

> **Gitignore note:** `store.db` and `rag/` are gitignored — they contain machine-specific absolute paths. Each developer runs `reki scan .` locally. Share human-readable output via `reki publish .`.

---

## 🚀 Core Features

### 🗂 `reki scan` — Instant knowledge store

Parses your repo into a SQLite knowledge store with symbols, relationships, and auto-generated wiki pages.

```bash
reki scan .            # full scan with LLM summaries
reki scan . --no-llm   # zero config, no API key required
reki scan . --community-sharding   # group related files by import-graph community before summarising
```

### 💬 `reki ask` — Q&A grounded in your code

Answers with **file:line citations and real code examples**. No hallucinations — every answer is backed by indexed source, with actual function bodies quoted inline.

```bash
reki ask "what is the entry point?"
reki ask "which modules handle payments?" --brief
```

**Example output:**
```
Answer: The entry point is src/main.py:12 — App.run() bootstraps the server.

```python
# src/main.py:12
def run(self):
    server = HTTPServer(self.config)
    server.start()
```

Sources: src/main.py:12, src/server.py:34
```

**How it works:** rekipedia extracts actual source bodies of the most relevant functions/classes and passes them directly to the LLM — so answers include real, runnable code, not just paraphrases. When a FAISS index exists (`reki embed .`), RAG chunks are used for even higher precision.

### 🤖 `reki mcp` — MCP server for AI agents

Plug rekipedia directly into Claude Code, Cursor, GitHub Copilot, or any MCP-aware agent.

```bash
reki mcp
```

**Available MCP tools:**

| Tool | Purpose |
|---|---|
| `ask` | Natural-language Q&A grounded in the scanned wiki |
| `search_nodes` | Fast symbol/file lookup by name |
| `get_context` | Symbols and relationships for a file |
| `get_relationships` | Callers and callees for a symbol |
| `get_hub_nodes` | Architectural chokepoints |
| `get_god_nodes` | Top N symbols by combined in+out degree — find architectural bottlenecks instantly |
| `shortest_path` | BFS shortest directed call-path between any two symbols (e.g. "how does A reach B?") |
| `get_community` | Which import-graph community a symbol belongs to, plus all community members |
| `get_impact` | Blast-radius for a changed file |
| `get_knowledge_gaps` | Untested high-call-count symbols |
| `list_wiki_pages` / `get_wiki_page` | Wiki browsing |

### 🔥 `reki hotspots` — Architectural hotspot detection

Finds hub nodes (files many depend on) and bridge nodes (files connecting clusters).

```bash
reki hotspots
```

```
Hub nodes:    src/core/engine.py (42 dependents)
Bridge nodes: src/adapters/db.py (connects 3 clusters)
```

### 🔄 `reki update` — Incremental updates

Only regenerates wiki pages affected by your changes.

```bash
reki update . --impact-only
```

### 🌐 `reki serve` — Local web UI

Launch a browsable wiki at `http://127.0.0.1:7070`.

```bash
reki serve .
```

### 📤 `reki publish` — Team sharing

Copy generated wiki into a git-tracked directory for team browsing.

```bash
reki publish . [--output-dir PATH]
```

---

## 🛠️ Commands Cheat Sheet

| Command | Description |
|---|---|
| `reki scan .` | Full scan — index symbols, generate wiki |
| `reki scan . --no-llm` | Scan without LLM, zero config |
| `reki scan . --use-engine codebase-memory` | Hybrid mode: delegate AST indexing for multi-million LOC codebases |
| `reki ask "question"` | Ask anything about the codebase |
| `reki ask "question" --brief` | Short answer mode |
| `reki explain <symbol>` | Inspect symbol location, callers, callees, degrees, design patterns |
| `reki path <from> <to>` | Trace shortest directed path between two symbols with evidence tags |
| `reki install` | Install agent skill for Pi, Claude Code, Cursor, Codex, Agent-Skills |
| `reki update . --impact-only` | Incremental update, affected pages only |
| `reki serve .` | Local web UI at `http://127.0.0.1:7070` |
| `reki embed .` | Build FAISS semantic index |
| `reki publish . [--output-dir PATH]` | Publish wiki to a git-tracked directory |
| `reki export . --format graph` | Export standalone interactive `graph.html` (offline viewer) |
| `reki export . --format bundle` | Export a content-addressed wiki bundle |
| `reki merge <bundle-A> <bundle-B> [--base BASE]` | Three-way conflict-free wiki merge |
| `reki pull [URL]` | Fetch and merge a remote wiki bundle |
| `reki watch . --publish` | Auto-index + auto-publish on every file save |
| `reki export . --format md\|zip\|json\|graph\|html` | Export the wiki |
| `reki diff` | Show impact of uncommitted changes |
| `reki hotspots` | Hub & bridge node detection |
| `reki refactor . --dry-run` | Preview refactor suggestions |
| `reki refactor . --apply` | Apply refactor suggestions |
| `reki mcp` | Start MCP stdio server |
| `reki review` | LLM-powered PR review |
| `reki hook install` | Install git post-commit hook |
| `reki init --with-all-ai` | Configure MCP for Copilot + Codex + Cursor |
| `reki init --with-ci` | Scaffold GitHub Actions workflow for auto-wiki |

---

## 🤖 AI CLI Tool Integration

```bash
reki init --with-all-ai    # configure Copilot + Codex + Cursor in one step

# or pick individually:
reki init --with-copilot   # VS Code — writes .vscode/mcp.json
reki init --with-codex     # Codex CLI — writes .codex/instructions.md
reki init --with-cursor    # Cursor — writes .cursor/mcp.json + rules
```

Once configured, each tool automatically gets access to the [MCP tools listed above](#-reki-mcp--mcp-server-for-ai-agents).

---

## ⚙️ LLM Setup

rekipedia works **entirely without an LLM** (`--no-llm`). To enable richer summaries and Q&A:

```bash
export REKIPEDIA_MODEL=gemini/gemini-2.5-pro
export GOOGLE_API_KEY=...
```

Or use any OpenAI-compatible endpoint:

```bash
export REKIPEDIA_MODEL=openai/gpt-4o
export REKIPEDIA_API_KEY=sk-...

# Local / offline
export REKIPEDIA_API_KEY=ollama
export REKIPEDIA_MODEL=ollama/llama3
```

---

## ❓ FAQ

**Q: Why is `store.db` gitignored? How do teammates use rekipedia?**

`store.db` contains machine-specific absolute paths — committing it would cause path mismatches and noisy binary diffs. Each developer runs `reki scan .` locally. To share human-readable output, use `reki publish .`, which copies generated wiki pages to `docs/wiki/` so they can be committed and browsed on GitHub or your docs site.

---

**Q: What is `store.db` for vs the FAISS index? Why do I need both?**

| | `store.db` | FAISS / Qdrant / Chroma |
|---|---|---|
| **Format** | Structured SQLite graph | Dense embedding vectors |
| **Purpose** | Precise filters — "find all callers of function X" | Fuzzy semantic search — "find code that handles authentication" |
| **Used by** | `search_nodes`, `get_relationships`, `hotspots` | `reki ask` RAG pipeline |

`reki ask` uses both: BM25 keyword search over SQLite **plus** vector similarity search, then merges and re-ranks results.

---

**Q: Can I use Postgres or MySQL instead of SQLite?**

Not currently. SQLite is intentional — zero-config, portable, no running server. `reki export .` produces `symbols.json` and `relationships.json` for loading into any database. Postgres/MySQL support is not on the roadmap, but the JSON exports make integration straightforward.

---

**Q: Does rekipedia support Qdrant or Chroma instead of FAISS?**

Yes. FAISS is the default, but Qdrant and Chroma are supported as optional backends — useful for shared, persistent vector stores across a team. Install extras:

```bash
pip install rekipedia[qdrant]    # or rekipedia[chroma]
```

Then configure the backend in `.rekipedia/config.yml`.

---

**Q: Do I need an OpenAI API key?**

No. `reki scan . --no-llm` performs static analysis only — fully offline and air-gap safe. When LLM features are enabled, only retrieved chunks (not your full source) are sent as context. Use [Ollama](https://ollama.com) for fully local inference — no internet required.

---

**Q: How do I keep the wiki up to date automatically?**

Run `reki init --with-ci` to scaffold a GitHub Actions workflow that runs `reki scan` + `reki publish` on every push to `main`. The workflow commits changes to `docs/wiki/` back to the repo automatically. Set `REKIPEDIA_API_KEY` as a repository secret for LLM-enriched pages; omit it and the workflow falls back to `--no-llm` at zero cost.

---

**Q: How does team sync work for distributed teams?**

rekipedia uses a multi-layer, conflict-free collaboration system:

1. **Bundle** — `reki export --format bundle` creates a deterministic, content-addressed snapshot.
2. **Merge** — `reki merge bundle-A bundle-B --base bundle-base` performs a three-way merge with automatic resolution for non-conflicting changes.
3. **Git merge driver** — `reki init --with-merge-driver` registers a custom driver so `git merge` and `git pull` use rekipedia's logic — no `<<<<<<` conflicts in generated wiki files.
4. **Live sync** — `reki watch . --publish` publishes the wiki after every incremental update.
5. **Remote pull** — `reki pull <url>` fetches a bundle from HTTPS, S3, or GCS and merges it locally.

---

**Q: How does `reki ask` work under the hood?**

A hybrid retrieval pipeline:

1. **BM25 keyword search** against the SQLite store for exact and near-exact matches.
2. **Vector similarity search** against FAISS/Qdrant/Chroma for semantic matches.
3. **Merge & re-rank** the two result sets by relevance score.
4. **LLM synthesis** — top chunks passed to your configured LLM with file:line citations.

With `--no-llm`, retrieval results are returned directly without synthesis.

---

**Q: How large does `store.db` / the FAISS index get on a large repo?**

For a typical mid-size repo (50k–200k LOC):

| Storage | Typical Size |
|---|---|
| `store.db` | 10–80 MB |
| FAISS index | 50–500 MB |

On very large monorepos (1M+ LOC), the FAISS index can exceed 1 GB; switching to a server-backed Qdrant instance is recommended.

---

**Q: Can rekipedia scan private or fully offline repos?**

Yes, fully. `reki scan` is pure static analysis — it never sends your source code anywhere. With `--no-llm`, the entire pipeline is offline and air-gap safe. There are no telemetry calls, no license checks against a remote server, and no internet requirement beyond your chosen LLM endpoint.

---

## 🔮 Coming Soon

- **Hosted wiki** — share your knowledge base with a link, no self-hosting required
- **VS Code extension** — inline `reki ask` from your editor

---

## 🤝 Contributing

```bash
git clone https://github.com/unrealandychan/rekipedia.git
pip install -e ".[dev]"
```

Open an issue or PR — the bar is low and the maintainer is responsive.

---

**Current version:** `0.23.0` · [PyPI](https://pypi.org/project/rekipedia/) · [MIT License](LICENSE)
