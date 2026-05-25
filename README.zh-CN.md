# rekipedia

**[English](README.md) | [繁體中文](README.zh-TW.md) | [简体中文](README.zh-CN.md)**

> 您的 AI 技术负责人——随时在线，始终最新。

rekipedia 可扫描任意代码仓库，将其转化为便携的 SQLite 知识库，让团队中的每位开发者都拥有一个由 LLM 驱动的技术负责人，可以随时询问：_"认证流程是如何运作的？"、"添加一个新 API 端点最快的方式是什么？"、"上周是什么导致了支付服务故障？"_

零幻觉，零猜测——每个答案都基于您的真实代码库。

### 核心功能
- **关系置信度评分**：每个提取的关系均标记为 EXTRACTED/INFERRED/AMBIGUOUS，并附带置信度分数
- **设计意图提取**：`# NOTE:`、`# HACK:`、`# WHY:` 注释被提取为知识节点
- **God 节点**：度数最高的符号会在 index.md 中呈现，并在图形界面中高亮显示
- **交互式依赖关系图**：`rekipedia serve` 现已包含 `/graph` 路由，提供基于 D3.js 的力导向可视化
- **Git 钩子**：`rekipedia hook install` 可在每次提交时触发自动重建
- **智能 wiki 编排**：`PlannerAgent` 根据您的仓库动态设计 wiki 结构
- **页面重要性评分**：规划器为每个页面分配重要性分数（0–100），导航侧边栏按优先级排序
- **DeepWiki 风格分节**：页面按逻辑分节分组（`getting-started`、`architecture`、`core-components` 等）
- **Wiki 侧边栏分类**：`reki serve` 侧边栏按 `section` 字段分组，支持折叠标题
- **实时搜索**：在侧边栏搜索框中输入内容，可即时按标题或分类筛选 wiki 页面
- **重构分析**：`reki refactor` 检测代码异味（上帝类、循环依赖、死代码、高耦合），并提供 LLM 增强建议——输出 `REFACTOR.md` + `refactor_report.json`
- **上下文切片**：每个页面仅接收其所需的数据（相比固定布局方式减少约 40–60% 的 token 用量）
- **混合 RAG 问答**：FAISS 索引的代码块 + wiki 页面为 LLM 提供完整的代码库上下文以回答问题
- **嵌入模型提供商选择**：`--embed-provider openai|ollama|azure|...`——支持任何兼容 litellm 的嵌入模型
- **Wiki 导出**：打包为单个 Markdown 文件、ZIP 压缩包或结构化 JSON（`rekipedia export`）
- **增量更新**：首次扫描后仅重新处理已变更的文件
- **有据可查的问答**：答案引用真实的文件路径和行号——零幻觉
- **代码库树形索引**——每次扫描在 SQLite 中构建层级目录/文件树，支持结构化导航和未来基于推理的检索。

## 快速开始

### 通过 npm / npx（无需安装）

```bash
npx rekipedia init .
npx rekipedia scan .
```

### 通过 uv / uvx（无需安装）

```bash
uvx rekipedia init .
uvx rekipedia scan .
```

### 永久安装

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

## 快速开始——无需 API 密钥

无需任何 LLM API 密钥即可执行完整静态分析：

```bash
pip install rekipedia
reki scan . --no-llm   # ~5-10 秒，零 API 调用
reki onboard .         # 架构总览
reki tour .            # 依赖深度导览
reki domain .          # 业务领域层次图
reki diff .            # 变更影响分析
reki export . --format md  # 导出完整 wiki 为 Markdown
```

> **注意：** `reki ask`（AI 问答）需要 LLM API 密钥。请参阅下方 [LLM 配置](#llm-配置)。

---

## Python API

在 Jupyter Notebook、CI 流水线或任意 Python 应用中以编程方式使用 rekipedia：

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

**返回类型：**

| Type | Key fields |
|---|---|
| `ScanResult` | `page_count`, `symbol_count`, `token_count`, `wiki_pages`, `db_path`, `wiki_dir` |
| `AskResult` | `text`, `citations: list[Citation]`, `model_used` |
| `Citation` | `file`, `line`, `snippet` |

---

## 命令

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

## LLM 配置

rekipedia 使用 [litellm](https://github.com/BerriAI/litellm)，支持任何提供商：

| 提供商 | 示例 |
|---|---|
| OpenAI | `OPENAI_API_KEY=sk-... reki scan .` |
| Anthropic Claude | `REKIPEDIA_MODEL=claude-3-5-sonnet-20241022 REKIPEDIA_API_KEY=sk-ant-... reki scan .` |
| Google Gemini | `REKIPEDIA_MODEL=gemini/gemini-2.0-flash REKIPEDIA_API_KEY=AIza... reki scan .` |
| OpenRouter | `REKIPEDIA_MODEL=openrouter/anthropic/claude-3.5-sonnet REKIPEDIA_API_KEY=sk-or-... reki scan .` |
| 本地 Ollama（默认） | `REKIPEDIA_MODEL=ollama/llama4 reki scan .` |
| Azure OpenAI | `REKIPEDIA_MODEL=azure/gpt-4o REKIPEDIA_BASE_URL=https://your-resource.openai.azure.com REKIPEDIA_API_KEY=... reki scan .` |

环境变量：
- `REKIPEDIA_MODEL` — litellm 模型字符串（默认：`ollama/llama4`）
- `REKIPEDIA_API_KEY` — 所选提供商的 API 密钥
- `REKIPEDIA_BASE_URL` — 自定义基础 URL（用于 Azure、Ollama、代理）
- `REKIPEDIA_TIMEOUT` — LLM 调用超时秒数（默认：180）

运行 `rekipedia init` 后，编辑 `.rekipedia/config.yml`：

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

### 支持的提供商（通过 [litellm](https://docs.litellm.ai)）

| Provider | Example model string |
|---|---|
| Ollama (local, free) | `ollama/llama4` |
| OpenAI | `gpt-5.5` |
| Anthropic | `claude-opus-4-6` |
| Google Gemini | `gemini/gemini-3.0-pro` |
| Any OpenAI-compatible | set `base_url` in config |

### 运行时覆盖（环境变量）

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

## 输出

`rekipedia scan` 将所有内容写入仓库内的 `.rekipedia/` 目录：

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

根据仓库复杂度动态生成 3–15 个 wiki 页面（由 PlannerAgent 驱动）。

wiki 结构由 `PlannerAgent` 根据仓库实际内容动态设计：

| Section | Example pages | When generated |
|---|---|---|
| Getting Started | index, installation, quick-start | Always |
| Architecture | architecture-overview, data-flow, repository-structure | ≥3 modules |
| Core Components | One page per major module | ≥2 modules |
| API Reference | cli-reference, python-api, rest-api | CLI/HTTP handlers found |
| Development | testing, contributing, ci-cd | Test files found |
| Ecosystem | integrations, deployment | ≥3 external deps |

### 扫描选项

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

### RAG / 语义搜索

`rekipedia ask` 使用**混合检索**——wiki 页面 + FAISS 索引的代码块——在完整代码库上下文中回答问题。

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

FAISS 索引保存至 `.rekipedia/rag/index.faiss`，分块后的源代码保存至 `.rekipedia/rag/chunks.json`。

### 导出 wiki

```bash
# Single combined Markdown file (default)
rekipedia export . --format md --output ./wiki-export.md

# ZIP archive (one .md per page + manifest.json)
rekipedia export . --format zip --output ./wiki.zip

# Structured JSON (all pages + metadata)
rekipedia export . --format json --output ./wiki.json
```

### 增量更新

首次扫描后，`rekipedia update` 仅重新处理 SHA-256 已发生变化的文件。未变更的符号和关系将从上次运行中延续——wiki 可在数秒内完成刷新。

```bash
rekipedia update .                    # auto-detect changed files
rekipedia update . --no-docker        # skip Docker
```

若未找到之前的扫描记录，`update` 会自动回退至全量扫描。

### 询问 wiki

```bash
# Start interactive Q&A session (streams answers, Ctrl+C to quit)
rekipedia ask
rekipedia ask --repo ./my-project
rekipedia ask --model gpt-4o

# Single-shot mode (backward compat)
rekipedia ask -q "How does the auth flow work?"
```

答案**完全**基于您的 wiki 页面和符号索引——LLM 无法虚构扫描知识库中不存在的内容。答案以逐 token 流式方式输出，等待时显示进度指示器。

对某个生成页面不满意？请参阅 **[docs/customizing.md](docs/customizing.md)**——您可以固定页面、覆盖提示词、更改写作风格，或添加扫描永不触碰的自定义页面。

### 启动 wiki 服务

```bash
rekipedia serve .                     # opens browser at http://127.0.0.1:7070
rekipedia serve . --port 8080         # custom port
rekipedia serve . --no-browser        # don't auto-open browser
```

- 在深色主题的 Web 界面中浏览生成的 wiki 页面
- 使用相同的有据可查问答功能提问（答案通过 Web 流式返回）
- 问答历史记录存储于 SQLite

---

## 前置要求

- **Python ≥ 3.11**（或使用 `uv`，它自行管理 Python 环境）
- **Docker**——可选；用于隔离提取。若 Docker 不可用，将自动回退至进程内运行模式（`--no-docker` 强制使用进程内模式）

---

## 与 AI 编程智能体配合使用

rekipedia 附带一个 **Hermes agent skill**（`rekipedia-agent-skill.md`），可教会 AI 助手（Copilot、Claude Code、Codex）将 rekipedia 作为其代码库智能层：

1. 将 `rekipedia-agent-skill.md` 复制到您的 Hermes skills 目录
2. 任何已加载该 skill 的智能体都将在深入源文件之前自动扫描并查询 rekipedia
3. 显著降低大型代码库的上下文窗口用量

---

## 智能体模式

rekipedia 支持实验性智能体模式，其中 LLM 调用使用工具调用（ReAct）而非单次大上下文输入。

### 智能体问答

设置 `REKIPEDIA_AGENT_ASK=1` 以启用：

```bash
REKIPEDIA_AGENT_ASK=1 reki ask "How does authentication work?"
```

LLM 按需发出工具调用以检索信息：
- `search_code(query)` — 对源代码进行语义搜索
- `get_symbol(name)` — 查找符号位置和签名
- `get_page(slug)` — 按需获取 wiki 页面
- `get_relationships(target)` — 获取符号/文件的依赖关系图
- `finish(answer)` — 提供最终答案

最大迭代次数可通过 `REKIPEDIA_ASK_MAX_ITER` 配置（默认值：5）。

### 智能体规划器

设置 `REKIPEDIA_AGENT_PLANNER=1` 以启用工具调用式 wiki 结构规划：

```bash
REKIPEDIA_AGENT_PLANNER=1 reki scan .
```

规划器通过工具调用逐步构建 wiki 结构，而非生成单个大型 JSON 响应。

## 开发

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

### 发布

```bash
PYPI_TOKEN=*** NPM_TOKEN=*** make release

# Full release: build + tag + push + PyPI + npm
make release-all PYPI_TOKEN=*** NPM_TOKEN=***
# With version bump
make release-all PYPI_TOKEN=*** NPM_TOKEN=*** VERSION=0.5.0
```

---

## 许可证

专有且保密——版权所有 © 2026 Eddie Chan。保留所有权利。

未经授权，严禁复制、分发或修改本软件。
详情请参阅 [LICENSE](LICENSE)。
