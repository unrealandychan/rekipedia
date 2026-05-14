# close-wiki

**[English](README.md) | [繁體中文](README.zh-TW.md) | [简体中文](README.zh-CN.md)**

> 您的 AI 技术负责人 —— 随时在线，始终最新。

close-wiki 可扫描任意代码仓库，将其转化为便携式 SQLite 知识库，让团队中的每位开发者都拥有一个由 LLM 驱动的技术负责人，可以随时提问：_"认证流程是怎么工作的？"、"添加一个新 API 端点最快的方式是什么？"、"上周支付服务是什么原因出了问题？"_

零幻觉，零猜测 —— 每一个答案都基于您的真实代码库。

### 核心功能
- **智能体 Wiki 编排**：`PlannerAgent` 根据您的仓库动态设计 Wiki 结构
- **页面重要性评分**：规划器为每个页面分配重要性分数（0–100），导航侧边栏按优先级排序
- **DeepWiki 风格分区**：页面按逻辑分区归组（`getting-started`、`architecture`、`core-components` 等）
- **上下文切片**：每个页面仅接收所需数据（相比固定布局方案减少约 40–60% 的 token 用量）
- **混合 RAG 问答**：FAISS 索引代码块 + Wiki 页面，为 LLM 提供完整的代码库上下文
- **嵌入提供商可选**：`--embed-provider openai|ollama|azure|...` —— 支持任意兼容 litellm 的嵌入模型
- **Wiki 导出**：打包为单一 Markdown 文件、ZIP 压缩包或结构化 JSON（`close-wiki export`）
- **增量更新**：首次扫描后仅重新处理发生变更的文件
- **有据可查的问答**：答案引用真实文件路径和行号 —— 零幻觉

## 快速开始

### 通过 npm / npx（无需安装）

```bash
npx close-wiki init .
npx close-wiki scan .
```

### 通过 uv / uvx（无需安装）

```bash
uvx close-wiki init .
uvx close-wiki scan .
```

### 永久安装

```bash
# Python
uv tool install close-wiki
# or
pip install close-wiki

# Node (adds global `close-wiki` binary that delegates to Python)
npm install -g close-wiki
```

---

## 命令列表

- `close-wiki init [REPO]` — 初始化 `.close-wiki/` 目录，生成 `config.yml` 并更新 `.gitignore`
- `close-wiki scan [REPO]` — 完整分析 —— 提取符号、合成 Wiki 页面、导出 JSON
- `close-wiki update [REPO]` — 增量刷新 —— 仅重新提取已变更的文件，其余保持不变
- `close-wiki ask [QUESTION]` — 交互式问答 REPL —— 流式输出答案，按 Ctrl+C 退出
- `close-wiki serve [REPO]` — 启动本地 Web UI，浏览 Wiki 页面并进行提问
- `close-wiki embed [REPO]` — 构建（或重建）用于混合 RAG 问答的 FAISS 语义搜索索引
- `close-wiki export [REPO]` — 将 Wiki 打包为单一文件（`--format md|zip|json`）

---

## LLM 配置

运行 `close-wiki init` 后，编辑 `.close-wiki/config.yml`：

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

### 支持的提供商（通过 [litellm](https://docs.litellm.ai)）

- **Ollama（本地，免费）** — `ollama/llama4`
- **OpenAI** — `gpt-5.5`
- **Anthropic** — `claude-opus-4-6`
- **Google Gemini** — `gemini/gemini-3.0-pro`
- **任意 OpenAI 兼容服务** — 在配置文件中设置 `base_url`

### 运行时覆盖（环境变量）

```bash
export CLOSE_WIKI_MODEL=gpt-5.5
export CLOSE_WIKI_API_KEY=***
export CLOSE_WIKI_BASE_URL=https://my-proxy/v1
```

---

## 输出结构

`close-wiki scan` 将所有内容写入仓库内的 `.close-wiki/` 目录：

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

根据仓库复杂度动态生成 3–15 个 Wiki 页面（由 PlannerAgent 驱动）。

Wiki 结构由 `PlannerAgent` 根据仓库实际内容动态设计：

- **Getting Started**（入门）— index、installation、quick-start — 始终生成
- **Architecture**（架构）— architecture-overview、data-flow、repository-structure — 模块数 ≥3 时生成
- **Core Components**（核心组件）— 每个主要模块对应一页 — 模块数 ≥2 时生成
- **API Reference**（API 参考）— cli-reference、python-api、rest-api — 发现 CLI/HTTP 处理器时生成
- **Development**（开发）— testing、contributing、ci-cd — 发现测试文件时生成
- **Ecosystem**（生态）— integrations、deployment — 外部依赖数 ≥3 时生成

### 扫描选项

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

### RAG / 语义搜索

`close-wiki ask` 使用**混合检索**策略 —— Wiki 页面 + FAISS 索引代码块 —— 结合完整代码库上下文回答问题。

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

FAISS 索引保存至 `.close-wiki/rag/index.faiss`，代码分块保存至 `.close-wiki/rag/chunks.json`。

### 导出 Wiki

```bash
# Single combined Markdown file (default)
close-wiki export . --format md --output ./wiki-export.md

# ZIP archive (one .md per page + manifest.json)
close-wiki export . --format zip --output ./wiki.zip

# Structured JSON (all pages + metadata)
close-wiki export . --format json --output ./wiki.json
```

### 增量更新

首次扫描后，`close-wiki update` 仅重新处理 SHA-256 发生变化的文件。未变更的符号和关系将从上次运行中沿用 —— Wiki 可在数秒内完成刷新。

```bash
close-wiki update .                    # auto-detect changed files
close-wiki update . --no-docker        # skip Docker
```

若未找到之前的扫描结果，`update` 将自动回退至完整扫描。

### 向 Wiki 提问

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

答案**完全**基于您的 Wiki 页面和符号索引 —— LLM 无法凭空捏造任何不在已扫描知识库中的内容。答案以逐 token 流式输出，等待时显示进度动画。

对某个生成页面不满意？请参阅 **[docs/customizing.md](docs/customizing.md)** —— 您可以固定页面、覆盖提示词、更改写作风格，或添加扫描永远不会覆盖的自定义页面。

### 启动 Wiki 服务

```bash
close-wiki serve .                     # opens browser at http://127.0.0.1:7070
close-wiki serve . --port 8080         # custom port
close-wiki serve . --no-browser        # don't auto-open browser
```

- 在深色主题 Web UI 中浏览生成的 Wiki 页面
- 使用相同的有据可查问答功能提问（答案通过 Web 流式输出）
- 问答历史记录存储于 SQLite

---

## 环境要求

- **Python ≥ 3.11**（或使用 `uv`，其自带 Python 管理能力）
- **Docker** —— 可选；用于隔离式提取。若 Docker 不可用，将自动回退至进程内运行模式（`--no-docker` 强制使用进程内模式）

---

## 与 AI 编程智能体配合使用

close-wiki 内置一个 **Hermes agent skill**（`close-wiki-agent-skill.md`），可教会 AI 助手（Copilot、Claude Code、Codex）将 close-wiki 作为其代码库智能层：

1. 将 `close-wiki-agent-skill.md` 复制到您的 Hermes skills 目录
2. 加载了该 skill 的任意智能体将在深入源文件之前自动扫描并查询 close-wiki
3. 大幅降低大型代码库的上下文窗口占用

---

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

MIT —— 详见 [LICENSE](LICENSE)。
