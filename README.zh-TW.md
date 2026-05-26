# rekipedia

**[English](README.md) | [繁體中文](README.zh-TW.md) | [简体中文](README.zh-CN.md)**

> 你的 AI 技術主管 — 隨時待命，永遠保持最新。

rekipedia 可以將任何程式碼庫 scan 成可攜式的 SQLite 知識庫，讓每位開發者都擁有一位由 LLM 驅動的技術主管，可以隨時提問。

零幻覺 — 每個回答都以你實際的程式碼庫為依據。

---

## 快速開始

```bash
# 無需安裝
npx rekipedia init . && npx rekipedia scan .
# 或
uvx rekipedia init . && uvx rekipedia scan .
```

```bash
# 永久安裝
pip install rekipedia          # core
pip install "rekipedia[rag]"   # + semantic search (FAISS)
```

---

## 快速開始 — 無需 API 金鑰

不需要任何 LLM API 金鑰，即可執行完整的靜態分析：

```bash
pip install rekipedia
reki scan . --no-llm   # ~5-10s, zero API calls
reki onboard .         # architecture overview
reki tour .            # guided walkthrough by dependency depth
reki domain .          # business domain layer map
reki diff .            # impact analysis on changed files
reki export . --format md  # export full wiki to markdown
```

> **注意：** `reki ask`（AI 問答）需要 LLM API 金鑰。請參閱下方的 [LLM 設定](#llm-設定)。

---

## 核心指令

| 指令 | 功能說明 |
|---|---|
| `reki init .` | 建立初始設定檔 |
| `reki scan .` | 完整分析 → wiki + 知識庫 |
| `reki update .` | 增量更新（僅處理變更的檔案） |
| `reki update . --impact-only` | 影響感知模式 — 僅重新產生受影響模組的 wiki 頁面 |
| `reki serve .` | 本地端 Web UI — 瀏覽、搜尋、詢問 AI |
| `reki ask` | 互動式問答 REPL（串流輸出） |
| `reki embed .` | 建立 FAISS 語意索引以支援 hybrid RAG |
| `reki export .` | 打包 wiki → `--format md|zip|json|html` |
| `reki diff` | 未提交變更的影響分析 |
| `reki domain .` | 將程式碼庫對應至業務層（API/Service/Data/UI） |
| `reki tour .` | 依相依深度的引導式學習流程 |
| `reki onboard .` | 給新開發者的靜態引導指南 |
| `reki review` | 以 wiki 為基礎的 LLM PR 審查 |
| `reki refactor .` | 偵測程式碼壞味道 → `REFACTOR.md` |
| `reki refactor . --dry-run` | 預覽重構建議，不實際寫入檔案 |
| `reki refactor . --apply` | 自動套用安全修正（死碼標記、拆分建議） |
| `reki refactor . --apply --dry-run` | 預覽 `--apply` 將會執行的內容 |
| `reki watch .` | 檔案變更時自動建立索引（OS watcher） |
| `reki hook install` | Git post-commit 自動重建 |
| `reki mcp` | 供 AI 程式碼助理使用的 MCP stdio 伺服器 |

---

### `reki ask` — 簡潔模式

```bash
# Brief mode — ~150 tokens, summary + citations only
reki ask "what does Scanner.scan() do?" --brief

# Or via env var (useful for piping)
REKIPEDIA_BRIEF=1 reki ask "entry point?" | grep 'src/'
```

---

## LLM 設定

rekipedia 使用 [litellm](https://github.com/BerriAI/litellm)，支援任何供應商：

| 供應商 | 範例 |
|---|---|
| OpenAI | `OPENAI_API_KEY=*** reki scan .` |
| Anthropic Claude | `REKIPEDIA_MODEL=claude-3-5-sonnet-20241022 REKIPEDIA_API_KEY=*** reki scan .` |
| Google Gemini | `REKIPEDIA_MODEL=gemini/gemini-2.0-flash REKIPEDIA_API_KEY=*** reki scan .` |
| OpenRouter | `REKIPEDIA_MODEL=openrouter/anthropic/claude-3.5-sonnet REKIPEDIA_API_KEY=*** reki scan .` |
| 本地 Ollama（預設） | `REKIPEDIA_MODEL=ollama/llama4 reki scan .` |
| Azure OpenAI | `REKIPEDIA_MODEL=azure/gpt-4o REKIPEDIA_BASE_URL=https://your-resource.openai.azure.com REKIPEDIA_API_KEY=*** reki scan .` |

執行 `reki init` 後，編輯 `.rekipedia/config.yml`：

```yaml
llm:
  model: ollama/llama4
  api_key: ""
  base_url: ""
  temperature: 0.2
```

環境變數：
- `REKIPEDIA_MODEL` — litellm model string（預設：`ollama/llama4`）
- `REKIPEDIA_API_KEY` — 所選供應商的 API 金鑰
- `REKIPEDIA_BASE_URL` — 自訂 base URL
- `REKIPEDIA_TIMEOUT` — LLM 呼叫逾時秒數（預設：180）

---

## 輸出結構

```
.rekipedia/
├── config.yml
├── store.db
├── wiki/
├── rag/
├── diagrams/
└── exports/
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

---

## 開發

```bash
make dev
make test
make lint
make build
```

---

## 授權條款

MIT License — Copyright © 2026 Eddie Chan
