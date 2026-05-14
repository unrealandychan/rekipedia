# close-wiki

**[English](README.md) | [繁體中文](README.zh-TW.md) | [简体中文](README.zh-CN.md)**

> 你的 AI 技術主管——隨時待命，永遠保持最新狀態。

close-wiki 將任何程式碼庫掃描成一個可攜式的 SQLite 知識庫，讓團隊中的每位開發者都擁有一位由 LLM 驅動的技術主管，可以隨時詢問任何問題：*「身份驗證流程是如何運作的？」、「新增一個 API 端點最快的方法是什麼？」、「上週是什麼導致支付服務出現問題？」*

沒有幻覺，不靠猜測——每個答案都完全根植於你實際的程式碼庫。

### 主要功能
- **代理式 Wiki 編排**：`PlannerAgent` 根據你的程式庫動態設計 Wiki 結構
- **頁面重要性評分**：規劃器為每個頁面分配重要性評分（0–100）；導覽側邊欄按優先順序排列
- **DeepWiki 風格的章節**：頁面分組為邏輯章節（`getting-started`、`architecture`、`core-components` 等）
- **Context 切片**：每個頁面只接收所需的資料（相較固定佈局方式減少約 40–60% 的 token 用量）
- **混合 RAG 問答**：FAISS 索引的程式碼片段 + Wiki 頁面，讓 LLM 在回答問題時擁有完整的程式庫上下文
- **嵌入提供者選擇**：`--embed-provider openai|ollama|azure|...` — 支援任何與 litellm 相容的嵌入模型
- **Wiki 匯出**：打包成單一 Markdown 檔案、ZIP 壓縮檔或結構化 JSON（`close-wiki export`）
- **增量更新**：首次掃描後僅重新處理已變更的檔案
- **有根據的問答**：答案引用真實的檔案路徑與行號——不會產生幻覺

## 快速開始

### 透過 npm / npx（無需安裝）

```bash
npx close-wiki init .
npx close-wiki scan .
```

### 透過 uv / uvx（無需安裝）

```bash
uvx close-wiki init .
uvx close-wiki scan .
```

### 永久安裝

```bash
# Python
uv tool install close-wiki
# or
pip install close-wiki

# Node (adds global `close-wiki` binary that delegates to Python)
npm install -g close-wiki
```

---

## 指令

- `close-wiki init [REPO]` — 建立 `.close-wiki/` 目錄結構，包含 `config.yml`，並更新 `.gitignore`
- `close-wiki scan [REPO]` — 完整分析——提取符號、合成 Wiki 頁面、匯出 JSON
- `close-wiki update [REPO]` — 增量更新——僅重新提取已變更的檔案，其餘保留
- `close-wiki ask [QUESTION]` — 互動式問答 REPL——串流回答，按 Ctrl+C 離開
- `close-wiki serve [REPO]` — 啟動本地網頁介面以瀏覽 Wiki 頁面並提問
- `close-wiki embed [REPO]` — 建立（或重建）用於混合 RAG 問答的 FAISS 語義搜尋索引
- `close-wiki export [REPO]` — 將 Wiki 打包成單一檔案（`--format md|zip|json`）

---

## LLM 設定

執行 `close-wiki init` 後，編輯 `.close-wiki/config.yml`：

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

### 支援的提供者（透過 [litellm](https://docs.litellm.ai)）

- **Ollama（本地，免費）**：`ollama/llama4`
- **OpenAI**：`gpt-5.5`
- **Anthropic**：`claude-opus-4-6`
- **Google Gemini**：`gemini/gemini-3.0-pro`
- **任何與 OpenAI 相容的服務**：在設定中指定 `base_url`

### 執行時覆寫（環境變數）

```bash
export CLOSE_WIKI_MODEL=gpt-5.5
export CLOSE_WIKI_API_KEY=***
export CLOSE_WIKI_BASE_URL=https://my-proxy/v1
```

---

## 輸出

`close-wiki scan` 將所有內容寫入你程式庫中的 `.close-wiki/` 目錄：

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

根據程式庫複雜度動態生成 3–15 個 Wiki 頁面（由 PlannerAgent 驅動）。

Wiki 結構由 `PlannerAgent` 根據程式庫中實際存在的內容動態設計：

- **Getting Started**（例：index、installation、quick-start）：永遠生成
- **Architecture**（例：architecture-overview、data-flow、repository-structure）：模組數 ≥3 時生成
- **Core Components**（每個主要模組一頁）：模組數 ≥2 時生成
- **API Reference**（例：cli-reference、python-api、rest-api）：找到 CLI/HTTP 處理器時生成
- **Development**（例：testing、contributing、ci-cd）：找到測試檔案時生成
- **Ecosystem**（例：integrations、deployment）：外部依賴數 ≥3 時生成

### 掃描選項

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

### RAG / 語義搜尋

`close-wiki ask` 使用**混合檢索**——Wiki 頁面 + FAISS 索引的程式碼片段——以完整的程式庫上下文回答問題。

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

FAISS 索引儲存於 `.close-wiki/rag/index.faiss`，分塊的原始碼儲存於 `.close-wiki/rag/chunks.json`。

### 匯出 Wiki

```bash
# Single combined Markdown file (default)
close-wiki export . --format md --output ./wiki-export.md

# ZIP archive (one .md per page + manifest.json)
close-wiki export . --format zip --output ./wiki.zip

# Structured JSON (all pages + metadata)
close-wiki export . --format json --output ./wiki.json
```

### 增量更新

首次掃描後，`close-wiki update` 只會重新處理 SHA-256 已變更的檔案。未變更的符號與關聯關係將從上次執行結果中延續——Wiki 可在數秒內完成更新。

```bash
close-wiki update .                    # auto-detect changed files
close-wiki update . --no-docker        # skip Docker
```

若未找到先前的掃描記錄，`update` 會自動退回執行完整掃描。

### 詢問 Wiki

```bash
# Start interactive Q&A session (streams answers, Ctrl+C to quit)
close-wiki ask
close-wiki ask --repo ./my-project
close-wiki ask --model gpt-4o

# Single-shot mode (backward compat)
close-wiki ask -q "How does the auth flow work?"

# Agentic mode — ReAct loop with tool calls (multi-step reasoning)
close-wiki ask --agentic
close-wiki ask --agentic -q "Trace the full request lifecycle from HTTP handler to DB"
# Or via env var:
export REKIPEDIA_AGENTIC=1
```

回答**完全**根植於你的 Wiki 頁面和符號索引——LLM 無法捏造任何不在已掃描知識庫中的細節。回答以逐 token 串流方式輸出，等待期間顯示進度指示器。

對生成的頁面不滿意？請參閱 **[docs/customizing.md](docs/customizing.md)**——你可以釘選頁面、覆寫提示詞、變更撰寫風格，或新增掃描永遠不會觸及的自訂頁面。

### 啟動 Wiki 伺服器

```bash
close-wiki serve .                     # opens browser at http://127.0.0.1:7070
close-wiki serve . --port 8080         # custom port
close-wiki serve . --no-browser        # don't auto-open browser
```

- 在深色主題的網頁介面中瀏覽生成的 Wiki 頁面
- 使用相同的有根據問答功能提問（答案透過網頁串流輸出）
- 問答歷史記錄儲存於 SQLite

---

## 環境需求

- **Python ≥ 3.11**（或使用 `uv`，它會自行管理 Python 版本）
- **Docker** — 可選；用於隔離式提取。若 Docker 不可用，會自動退回至處理程序內執行模式（`--no-docker` 強制使用處理程序內模式）

---

## 搭配 AI 程式碼代理使用 close-wiki

close-wiki 內附一個 **Hermes agent skill**（`close-wiki-agent-skill.md`），可教導 AI 助理（Copilot、Claude Code、Codex）將 close-wiki 作為其程式庫智能層：

1. 將 `close-wiki-agent-skill.md` 複製到你的 Hermes skills 目錄
2. 任何載入該 skill 的代理，都會在深入原始碼檔案前自動執行掃描並查詢 close-wiki
3. 對於大型程式庫，可大幅減少上下文視窗的使用量

---

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

MIT — 詳見 [LICENSE](LICENSE)。
