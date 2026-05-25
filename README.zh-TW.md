# rekipedia

**[English](README.md) | [繁體中文](README.zh-TW.md) | [简体中文](README.zh-CN.md)**

> 您的 AI 技術領導——隨時待命，永遠最新。

rekipedia 能掃描任何程式碼庫，將其轉化為可攜式的 SQLite 知識庫，並為團隊中每位開發者提供一位由 LLM 驅動的技術領導，讓他們隨時提問：_「驗證流程是如何運作的？」、「新增 API 端點最快的方法是什麼？」、「上週付款服務是什麼出了問題？」_

不會產生幻覺，不靠猜測——每個答案都紮根於您實際的程式碼庫。

### 主要功能
- **關係可信度評分**：每個提取的關係都標記為 EXTRACTED/INFERRED/AMBIGUOUS，並附有可信度分數
- **設計原理提取**：`# NOTE:`、`# HACK:`、`# WHY:` 注釋會被提取為知識節點
- **核心節點（God nodes）**：連結度最高的符號會顯示於 index.md 並在圖表介面中高亮標示
- **互動式依賴關係圖**：`rekipedia serve` 現在包含一個使用 D3.js 力導向視覺化的 `/graph` 路由
- **Git hooks**：`rekipedia hook install` 會在每次提交時觸發自動重建
- **代理式 wiki 協作**：`PlannerAgent` 根據您的程式碼庫動態設計 wiki 結構
- **頁面重要性評分**：規劃器為每個頁面分配重要性分數（0–100）；導航側邊欄依優先級排序
- **DeepWiki 式章節**：頁面分組至邏輯章節（`getting-started`、`architecture`、`core-components` 等）
- **Wiki 側邊欄分類**：`reki serve` 側邊欄依 `section` 欄位將頁面分組，並支援可折疊標頭
- **即時搜尋**：在側邊欄搜尋框中輸入，即可立即按標題或分類篩選 wiki 頁面
- **重構分析**：`reki refactor` 偵測程式碼異味（神類、循環依賴、死碼、高耦合），並提供 LLM 增強的建議——輸出 `REFACTOR.md` + `refactor_report.json`
- **上下文切片**：每個頁面只接收其所需的資料（相較固定佈局方式減少約 40–60% 的 token 用量）
- **混合式 RAG 問答**：FAISS 索引的程式碼片段 + wiki 頁面，讓 LLM 在回答問題時擁有完整的程式碼庫上下文
- **嵌入提供者選擇**：`--embed-provider openai|ollama|azure|...`——支援任何 litellm 相容的嵌入模型
- **Wiki 匯出**：打包為單一 Markdown 檔案、ZIP 壓縮包或結構化 JSON（`rekipedia export`）
- **增量更新**：初次掃描後僅重新處理已變更的檔案
- **有依據的問答**：答案引用真實的檔案路徑和行號——不產生幻覺
- **程式碼庫樹狀索引**——每次掃描都會在 SQLite 中建立階層式目錄/檔案樹，支援結構化導航與未來基於推理的檢索。

## 快速開始

### 透過 npm / npx（無需安裝）

```bash
npx rekipedia init .
npx rekipedia scan .
```

### 透過 uv / uvx（無需安裝）

```bash
uvx rekipedia init .
uvx rekipedia scan .
```

### 永久安裝

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

## 快速開始——無需 API 金鑰

無需任何 LLM API 金鑰即可執行完整靜態分析：

```bash
pip install rekipedia
reki scan . --no-llm   # ~5-10 秒，零 API 呼叫
reki onboard .         # 架構總覽
reki tour .            # 依賴深度導覽
reki domain .          # 業務領域層次圖
reki diff .            # 變更影響分析
reki export . --format md  # 匯出完整 wiki 為 Markdown
```

> **注意：** `reki ask`（AI 問答）需要 LLM API 金鑰。請參閱下方 [LLM 設定](#llm-設定)。

---

## Python API

在 Jupyter 筆記本、CI 流水線或任何 Python 應用程式中以程式化方式使用 rekipedia：

```python
import rekipedia

# Scan a local repo
result = rekipedia.scan("/path/to/repo")
print(result.page_count)   # number of wiki pages generated
print(result.symbol_count) # number of code symbols extracted
print(result.token_count)  # estimated token count of the wiki

# Ask a question — grounded answer with file:line citations
answer = rekipedia.ask("/path/to/repo", "How does the auth flow work?")
print(answer.text)
for citation in answer.citations:
    print(f"  {citation.file}:{citation.line}")

# Async variants (Jupyter-friendly)
result = await rekipedia.scan_async("/path/to/repo")
answer = await rekipedia.ask_async("/path/to/repo", "What is the entry point?")
```

**回傳型別：**

| Type | Key fields |
|---|---|
| `ScanResult` | `page_count`, `symbol_count`, `token_count`, `wiki_pages`, `db_path`, `wiki_dir` |
| `AskResult` | `text`, `citations: list[Citation]`, `model_used` |
| `Citation` | `file`, `line`, `snippet` |

---

## 指令

| Command | Description |
|---|---|
| `rekipedia init [REPO]` | Scaffold `.rekipedia/` with `config.yml` and update `.gitignore` |
| `rekipedia scan [REPO]` | Full analysis — extracts symbols, synthesises wiki pages, exports JSON |
| `rekipedia update [REPO]` | Incremental refresh — re-extracts only changed files, keeps the rest |
| `rekipedia ask [QUESTION]` | Interactive Q&A REPL — streaming answers, Ctrl+C to quit |
| `rekipedia serve [REPO]` | Start a local web UI to browse wiki pages and ask questions |
| `rekipedia embed [REPO]` | Build (or rebuild) the FAISS semantic search index for hybrid RAG Q&A |
| `rekipedia export [REPO]` | Bundle the wiki to a single file (`--format md\|zip\|json`) |
| `rekipedia hook install/uninstall/status` | Manage git post-commit hook for auto wiki rebuild |
| `rekipedia diff [A] [B]` | Compare two graph snapshots (defaults to last two) |
| `rekipedia impact <file>` | Show blast-radius — all affected files, symbols, tests for a changed file |
| `rekipedia search <query>` | Search symbols (`--all-repos` for cross-repo parallel search) |
| `rekipedia export --format graphml\|cypher\|obsidian` | Export graph to GraphML / Neo4j Cypher / Obsidian wikilinks |
| `rekipedia mcp` | Start JSON-RPC 2.0 MCP stdio server (6 tools for AI coding assistants) |
| `rekipedia watch add\|start\|list\|remove` | Watch repos and auto-index on file change |
| `rekipedia refactor [REPO]` | Detect code smells + generate `REFACTOR.md` and `refactor_report.json` (use `--no-llm` for static only) |
| `rekipedia note add\|list\|remove\|edit\|import` | Manage persistent tech lead notes — injected into `reki ask` context automatically |

---

## LLM 設定

rekipedia 使用 [litellm](https://github.com/BerriAI/litellm)，支援任何提供者：

| 提供者 | 範例 |
|---|---|
| OpenAI | `OPENAI_API_KEY=sk-... reki scan .` |
| Anthropic Claude | `REKIPEDIA_MODEL=claude-3-5-sonnet-20241022 REKIPEDIA_API_KEY=sk-ant-... reki scan .` |
| Google Gemini | `REKIPEDIA_MODEL=gemini/gemini-2.0-flash REKIPEDIA_API_KEY=AIza... reki scan .` |
| OpenRouter | `REKIPEDIA_MODEL=openrouter/anthropic/claude-3.5-sonnet REKIPEDIA_API_KEY=sk-or-... reki scan .` |
| 本地 Ollama（預設） | `REKIPEDIA_MODEL=ollama/llama4 reki scan .` |
| Azure OpenAI | `REKIPEDIA_MODEL=azure/gpt-4o REKIPEDIA_BASE_URL=https://your-resource.openai.azure.com REKIPEDIA_API_KEY=... reki scan .` |

環境變數：
- `REKIPEDIA_MODEL` — litellm 模型字串（預設：`ollama/llama4`）
- `REKIPEDIA_API_KEY` — 所選提供者的 API 金鑰
- `REKIPEDIA_BASE_URL` — 自訂基礎 URL（用於 Azure、Ollama、代理）
- `REKIPEDIA_TIMEOUT` — LLM 呼叫逾時秒數（預設：180）

執行 `rekipedia init` 後，編輯 `.rekipedia/config.yml`：

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

### 支援的提供者（透過 [litellm](https://docs.litellm.ai)）

| Provider | Example model string |
|---|---|
| Ollama (local, free) | `ollama/llama4` |
| OpenAI | `gpt-5.5` |
| Anthropic | `claude-opus-4-6` |
| Google Gemini | `gemini/gemini-3.0-pro` |
| Any OpenAI-compatible | set `base_url` in config |

### 執行時覆寫（環境變數）

```bash
export REKIPEDIA_MODEL=gpt-5.5
export REKIPEDIA_API_KEY=***
export REKIPEDIA_BASE_URL=https://my-proxy/v1
export REKIPEDIA_SHARD_TOKEN_BUDGET=***
```

| Variable | Description |
|---|---|
| `REKIPEDIA_MODEL` | LLM model name to use |
| `REKIPEDIA_API_KEY` | API key for the LLM provider |
| `REKIPEDIA_BASE_URL` | Base URL for OpenAI-compatible endpoints |
| `REKIPEDIA_SHARD_TOKEN_BUDGET` | Max tokens per shard group (default: 40000) |
| `REKIPEDIA_AGENT_ASK` | Set to `1` to enable agentic ReAct ask loop (default: `0` — single-shot) |
| `REKIPEDIA_ASK_MAX_ITER` | Max tool-call iterations for agentic ask (default: `5`) |
| `REKIPEDIA_AGENT_PLANNER` | Set to `1` to enable tool-calling wiki planner (default: `0`) |

---

## 輸出

`rekipedia scan` 會將所有內容寫入您程式碼庫內的 `.rekipedia/`：

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

根據程式碼庫複雜度動態生成 3–15 個 wiki 頁面（由 PlannerAgent 驅動）。

Wiki 結構由 `PlannerAgent` 根據您程式碼庫的實際內容動態設計：

| Section | Example pages | When generated |
|---|---|---|
| Getting Started | index, installation, quick-start | Always |
| Architecture | architecture-overview, data-flow, repository-structure | ≥3 modules |
| Core Components | One page per major module | ≥2 modules |
| API Reference | cli-reference, python-api, rest-api | CLI/HTTP handlers found |
| Development | testing, contributing, ci-cd | Test files found |
| Ecosystem | integrations, deployment | ≥3 external deps |

### 掃描選項

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

### RAG / 語義搜尋

`rekipedia ask` 使用**混合式檢索**——wiki 頁面 + FAISS 索引的程式碼片段——以完整的程式碼庫上下文回答問題。

```bash
# Build or rebuild the FAISS index
rekipedia embed .

# Custom embedding model + provider
rekipedia embed . --model text-embedding-3-small --provider openai
rekipedia embed . --model nomic-embed-text --provider ollama

# If your embed provider uses a DIFFERENT API key from your main LLM:
rekipedia embed . --model text-embedding-3-small --provider openai
# set embed_api_key in config.yml, or:
export REKIPEDIA_EMBED_API_KEY=***

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
export REKIPEDIA_EMBED_API_KEY=***
export REKIPEDIA_EMBED_BASE_URL=https://my-proxy.example.com/v1
```

FAISS 索引儲存於 `.rekipedia/rag/index.faiss`，分塊的原始碼儲存於 `.rekipedia/rag/chunks.json`。

### 匯出 wiki

```bash
# Single combined Markdown file (default)
rekipedia export . --format md --output ./wiki-export.md

# ZIP archive (one .md per page + manifest.json)
rekipedia export . --format zip --output ./wiki.zip

# Structured JSON (all pages + metadata)
rekipedia export . --format json --output ./wiki.json
```

### 增量更新

初次掃描後，`rekipedia update` 只會重新處理 SHA-256 已變更的檔案。未變更的符號和關係會從上次執行中延續——wiki 可在幾秒內完成更新。

```bash
rekipedia update .                    # auto-detect changed files
rekipedia update . --no-docker        # skip Docker
```

若找不到先前的掃描記錄，`update` 會自動回退至完整掃描。

### 向 wiki 提問

```bash
# Start interactive Q&A session (streams answers, Ctrl+C to quit)
rekipedia ask
rekipedia ask --repo ./my-project
rekipedia ask --model gpt-4o

# Single-shot mode (backward compat)
rekipedia ask -q "How does the auth flow work?"
```

答案**完全**以您的 wiki 頁面和符號索引為依據——LLM 無法捏造不存在於已掃描知識庫中的細節。答案以逐 token 串流方式輸出，等待時會顯示進度指示器。

對某個生成頁面不滿意？請參閱 **[docs/customizing.md](docs/customizing.md)**——您可以釘選頁面、覆寫提示詞、更改寫作風格，或新增掃描時永遠不會觸及的自訂頁面。

### 啟動 wiki 伺服器

```bash
rekipedia serve .                     # opens browser at http://127.0.0.1:7070
rekipedia serve . --port 8080         # custom port
rekipedia serve . --no-browser        # don't auto-open browser
```

- 在深色主題的網頁介面中瀏覽生成的 wiki 頁面
- 使用相同的有依據問答功能提問（答案透過網頁串流）
- 問答歷史記錄儲存於 SQLite

---

## 環境需求

- **Python ≥ 3.11**（或使用 `uv`，它自行管理 Python 版本）
- **Docker**——可選；用於隔離式提取。若 Docker 不可用，會自動回退至行程內執行模式（`--no-docker` 強制使用行程內模式）

---

## 搭配 AI 程式碼代理使用 rekipedia

rekipedia 附帶一個 **Hermes agent skill**（`rekipedia-agent-skill.md`），可教導 AI 助理（Copilot、Claude Code、Codex）將 rekipedia 作為其程式碼庫智慧層：

1. 將 `rekipedia-agent-skill.md` 複製到您的 Hermes skills 目錄
2. 任何已載入該技能的代理，都會在深入原始碼檔案前自動掃描並查詢 rekipedia
3. 大幅減少大型程式碼庫的上下文視窗用量

---

## 代理模式

rekipedia 支援實驗性的代理模式，其中 LLM 呼叫使用工具調用（ReAct）而非單次大型上下文傾倒。

### 代理式提問

設定 `REKIPEDIA_AGENT_ASK=1` 以啟用：

```bash
REKIPEDIA_AGENT_ASK=1 reki ask "How does authentication work?"
```

LLM 會發出工具調用以按需取得資訊：
- `search_code(query)` — 對原始碼進行語義搜尋
- `get_symbol(name)` — 查詢符號的位置和簽名
- `get_page(slug)` — 按需取得 wiki 頁面
- `get_relationships(target)` — 取得符號/檔案的依賴關係圖
- `finish(answer)` — 提供最終答案

最大迭代次數可透過 `REKIPEDIA_ASK_MAX_ITER` 設定（預設值：5）。

### 代理式規劃器

設定 `REKIPEDIA_AGENT_PLANNER=1` 以啟用工具調用式 wiki 結構規劃：

```bash
REKIPEDIA_AGENT_PLANNER=1 reki scan .
```

規劃器使用工具調用增量建構 wiki 結構，而非生成單一大型 JSON 回應。

## 開發

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

### 發佈

```bash
PYPI_TOKEN=*** NPM_TOKEN=*** make release

# Full release: build + tag + push + PyPI + npm
make release-all PYPI_TOKEN=*** NPM_TOKEN=***
# With version bump
make release-all PYPI_TOKEN=*** NPM_TOKEN=*** VERSION=0.5.0
```

---

## 授權條款

專有且機密——版權所有 © 2026 Eddie Chan。保留所有權利。

嚴禁未經授權複製、散布或修改本軟體。
詳情請參閱 [LICENSE](LICENSE)。
