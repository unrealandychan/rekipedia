# rekipedia

**[English](README.md) | [繁體中文](README.zh-TW.md) | [简体中文](README.zh-CN.md)**

> 你的 AI 技术负责人 —— 随时在线，始终最新。

rekipedia 可扫描任意代码库，生成便携式 SQLite 知识库，为每位开发者提供一个由 LLM 驱动的技术负责人，随问随答。

零幻觉 —— 每个回答都基于你的真实代码库。

---

## 快速开始

```bash
# 无需安装
npx rekipedia init . && npx rekipedia scan .
# 或
uvx rekipedia init . && uvx rekipedia scan .
```

```bash
# 永久安装
pip install rekipedia          # 核心
pip install "rekipedia[rag]"   # + 语义搜索 (FAISS)
```

---

## 快速开始 —— 无需 API Key

无需任何 LLM API Key，即可运行完整静态分析：

```bash
pip install rekipedia
reki scan . --no-llm   # ~5-10s，零 API 调用
reki onboard .         # 架构概览
reki tour .            # 按依赖深度引导游览
reki domain .          # 业务域分层图
reki diff .            # 已变更文件的影响分析
reki export . --format md  # 将完整 wiki 导出为 Markdown
```

> **注意：** `reki ask`（AI 问答）需要 LLM API Key。请参阅下方 [LLM 配置](#llm-配置)。

---

## 核心命令

| 命令 | 功能说明 |
|---|---|
| `reki init .` | 初始化配置 |
| `reki scan .` | 完整分析 → wiki + 知识库 |
| `reki update .` | 增量刷新（仅处理变更文件） |
| `reki update . --impact-only` | 影响感知模式 —— 仅重新生成受影响模块的 wiki 页面 |
| `reki serve .` | 本地 Web UI —— 浏览、搜索、问 AI |
| `reki ask` | 交互式问答 REPL（流式输出） |
| `reki embed .` | 构建 FAISS 语义索引（混合 RAG） |
| `reki export .` | 打包 wiki → `--format md|zip|json|html` |
| `reki diff` | 未提交变更的影响分析 |
| `reki domain .` | 将代码库映射到业务层（API/Service/Data/UI） |
| `reki tour .` | 按依赖深度引导学习游览 |
| `reki onboard .` | 面向新开发者的静态入职指南 |
| `reki review` | 基于 wiki 上下文的 LLM PR 审查 |
| `reki refactor .` | 检测代码异味 → `REFACTOR.md` |
| `reki refactor . --dry-run` | 预览重构建议，不写入文件 |
| `reki refactor . --apply` | 自动应用安全修复（死代码标记、拆分建议） |
| `reki refactor . --apply --dry-run` | 预览 `--apply` 将执行的操作 |
| `reki watch .` | 文件变更时自动重建索引（OS 监听器） |
| `reki hook install` | Git post-commit 自动重建 |
| `reki mcp` | 面向 AI 编程助手的 MCP stdio 服务器 |

---

### `reki ask` —— 简洁模式

```bash
# 简洁模式 —— ~150 tokens，仅输出摘要 + 引用
reki ask "what does Scanner.scan() do?" --brief

# 或通过环境变量（便于管道传输）
REKIPEDIA_BRIEF=1 reki ask "entry point?" | grep 'src/'
```

---

## LLM 配置

rekipedia 使用 [litellm](https://github.com/BerriAI/litellm)，支持任意 LLM 提供商：

| 提供商 | 示例 |
|---|---|
| OpenAI | `OPENAI_API_KEY=*** reki scan .` |
| Anthropic Claude | `REKIPEDIA_MODEL=claude-3-5-sonnet-20241022 REKIPEDIA_API_KEY=*** reki scan .` |
| Google Gemini | `REKIPEDIA_MODEL=gemini/gemini-2.0-flash REKIPEDIA_API_KEY=*** reki scan .` |
| OpenRouter | `REKIPEDIA_MODEL=openrouter/anthropic/claude-3.5-sonnet REKIPEDIA_API_KEY=*** reki scan .` |
| 本地 Ollama（默认） | `REKIPEDIA_MODEL=ollama/llama4 reki scan .` |
| Azure OpenAI | `REKIPEDIA_MODEL=azure/gpt-4o REKIPEDIA_BASE_URL=https://your-resource.openai.azure.com REKIPEDIA_API_KEY=*** reki scan .` |

执行 `reki init` 后，编辑 `.rekipedia/config.yml`：

```yaml
llm:
  model: ollama/llama4
  api_key: ""
  base_url: ""
  temperature: 0.2
```

环境变量：
- `REKIPEDIA_MODEL` —— litellm 模型字符串（默认：`ollama/llama4`）
- `REKIPEDIA_API_KEY` —— 所选提供商的 API Key
- `REKIPEDIA_BASE_URL` —— 自定义 Base URL
- `REKIPEDIA_TIMEOUT` —— LLM 调用超时时间，单位秒（默认：180）

---

## 输出目录结构

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

## 开发

```bash
make dev
make test
make lint
make build
```

---

## 许可证

MIT 许可证 — Copyright © 2026 Eddie Chan
