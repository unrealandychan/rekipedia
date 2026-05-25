# rekipedia

**[English](README.md) | [繁體中文](README.zh-TW.md) | [简体中文](README.zh-CN.md)**

> Your AI tech lead — always available, always up to date.

rekipedia scans any repository into a portable SQLite knowledge store and gives every developer an LLM-powered tech lead they can ask anything.

No hallucinations — every answer is grounded in your actual codebase.

---

## Quick start

```bash
# No install required
npx rekipedia init . && npx rekipedia scan .
# or
uvx rekipedia init . && uvx rekipedia scan .
```

```bash
# Permanent install
pip install rekipedia          # core
pip install "rekipedia[rag]"   # + semantic search (FAISS)
```

---

## Quick Start — No API Key Needed

Run a full static analysis without any LLM API key:

```bash
pip install rekipedia
reki scan . --no-llm   # ~5-10s, zero API calls
reki onboard .         # architecture overview
reki tour .            # guided walkthrough by dependency depth
reki domain .          # business domain layer map
reki diff .            # impact analysis on changed files
reki export . --format md  # export full wiki to markdown
```

> **Note:** `reki ask` (AI Q&A) requires an LLM API key. See [LLM Setup](#llm-setup) below.

---

## Core commands

| Command | What it does |
|---|---|
| `reki init .` | Scaffold config |
| `reki scan .` | Full analysis → wiki + knowledge store |
| `reki update .` | Incremental refresh (changed files only) |
| `reki serve .` | Local web UI — browse, search, ask AI |
| `reki ask` | Interactive Q&A REPL (streamed) |
| `reki embed .` | Build FAISS semantic index for hybrid RAG |
| `reki export .` | Bundle wiki → `--format md\|zip\|json\|html` |
| `reki diff` | Uncommitted-change impact analysis |
| `reki domain .` | Map codebase to business layers (API/Service/Data/UI) |
| `reki tour .` | Guided learning walkthrough by dependency depth |
| `reki onboard .` | Static onboarding guide for new developers |
| `reki review` | LLM PR review grounded in wiki context |
| `reki refactor .` | Detect code smells → `REFACTOR.md` |
| `reki watch .` | Auto-index on file change (OS watcher) |
| `reki hook install` | Git post-commit auto-rebuild |
| `reki mcp` | MCP stdio server for AI coding assistants |

---

## LLM Setup

rekipedia uses [litellm](https://github.com/BerriAI/litellm) and supports any provider:

| Provider | Example |
|---|---|
| OpenAI | `OPENAI_API_KEY=sk-... reki scan .` |
| Anthropic Claude | `REKIPEDIA_MODEL=claude-3-5-sonnet-20241022 REKIPEDIA_API_KEY=sk-ant-... reki scan .` |
| Google Gemini | `REKIPEDIA_MODEL=gemini/gemini-2.0-flash REKIPEDIA_API_KEY=AIza... reki scan .` |
| OpenRouter | `REKIPEDIA_MODEL=openrouter/anthropic/claude-3.5-sonnet REKIPEDIA_API_KEY=sk-or-... reki scan .` |
| Local Ollama (default) | `REKIPEDIA_MODEL=ollama/llama4 reki scan .` |
| Azure OpenAI | `REKIPEDIA_MODEL=azure/gpt-4o REKIPEDIA_BASE_URL=https://your-resource.openai.azure.com REKIPEDIA_API_KEY=... reki scan .` |

After `reki init`, edit `.rekipedia/config.yml`:

```yaml
llm:
  model: ollama/llama4        # any litellm model string
  api_key: ""                 # or REKIPEDIA_API_KEY env var
  base_url: ""                # for local / self-hosted endpoints
  temperature: 0.2
```

Supported providers: Ollama, OpenAI, Anthropic, Gemini, any OpenAI-compatible endpoint.

Environment variables:
- `REKIPEDIA_MODEL` — litellm model string (default: `ollama/llama4`)
- `REKIPEDIA_API_KEY` — API key for the chosen provider
- `REKIPEDIA_BASE_URL` — custom base URL (for Azure, Ollama, proxies)
- `REKIPEDIA_TIMEOUT` — LLM call timeout in seconds (default: 180)

---

## Output layout

```
.rekipedia/
├── config.yml          # settings (committed)
├── store.db            # SQLite knowledge store (git-ignored)
├── wiki/               # generated Markdown pages
├── rag/                # FAISS index + chunks (git-ignored)
├── diagrams/           # Mermaid diagrams
└── exports/            # JSON exports + manifest
```

---

## Python API

```python
import rekipedia

result = rekipedia.scan("/path/to/repo")
answer = rekipedia.ask("/path/to/repo", "How does the auth flow work?")
print(answer.text)
for c in answer.citations:
    print(f"  {c.file}:{c.line}")
```

Async variants: `rekipedia.scan_async()`, `rekipedia.ask_async()`

---

## Development

```bash
make dev      # install deps
make test     # run tests
make lint     # lint
make build    # wheel + npm tarball
```

---

## License

Proprietary and Confidential — Copyright © 2026 Eddie Chan. All Rights Reserved.
