---
name: rekipedia
description: Use rekipedia to instantly understand any codebase. Scan a repo to generate a structured wiki, then query it with natural language instead of reading hundreds of source files. Use this for onboarding, code review, architecture analysis, and feature planning.
triggers:
  - user asks to understand/explore/analyse a codebase
  - before implementing a feature in an unfamiliar repo
  - user says "read the codebase" or "understand this project"
  - before writing a PR, code review, or architecture doc
---

# rekipedia — Codebase Intelligence for AI Agents

Use `rekipedia` to understand any codebase instantly. Instead of reading hundreds of files, scan once to generate a structured wiki, then ask questions in natural language.

## When to use this skill

- You need to understand an unfamiliar repo before implementing a feature
- User asks you to "read the codebase", "understand the project", or "explore the code"
- You're doing a code review and need architectural context
- You want to answer "how does X work?" without grepping through files
- Planning a refactor or new feature across multiple modules

## Installation

```bash
# Recommended (pipx / uv tool — isolated)
uv tool install git+https://github.com/unrealandychan/rekipedia

# Or pip
pip install rekipedia

# Verify
rekipedia --version
```

## Core workflow

### Step 1 — Scan the repo (one-time, ~1–3 min)

```bash
# Basic scan (uses OPENAI_API_KEY or ANTHROPIC_API_KEY from env)
rekipedia scan /path/to/repo

# With a specific model
rekipedia scan /path/to/repo --model gpt-4o
rekipedia scan /path/to/repo --model claude-3-5-sonnet-20241022

# Verbose mode (see progress, debug LLM calls)
rekipedia scan /path/to/repo --verbose

# Skip Docker sandbox (recommended for most environments)
rekipedia scan /path/to/repo --no-docker
```

Output: generates `.rekipedia/` directory inside the repo with:
- `wiki/` — markdown pages (index, architecture, modules, CLI reference, etc.)
- `db.json` — symbol index + Q&A cache
- `analysis/` — raw static analysis shards

### Step 2 — Ask questions in natural language

```bash
# Single question
rekipedia ask /path/to/repo "How does the authentication flow work?"
rekipedia ask /path/to/repo "What does the PageBuilder class do?"
rekipedia ask /path/to/repo "How do I add a new CLI command?"

# Interactive REPL (recommended for exploration)
rekipedia ask /path/to/repo
# Then type questions interactively, Ctrl+C to exit
```

### Step 3 — Serve the wiki (optional, for browser viewing)

```bash
rekipedia serve /path/to/repo
# Opens at http://127.0.0.1:7070
```

### Step 4 — Update wiki after code changes

```bash
rekipedia update /path/to/repo
```

## Reading wiki pages directly

The generated wiki is plain Markdown — read pages directly for deep context:

```bash
# List all wiki pages
ls /path/to/repo/.rekipedia/wiki/

# Read specific pages
cat /path/to/repo/.rekipedia/wiki/index.md          # Project overview
cat /path/to/repo/.rekipedia/wiki/architecture.md   # System architecture
cat /path/to/repo/.rekipedia/wiki/core-modules.md   # Module documentation
cat /path/to/repo/.rekipedia/wiki/cli-and-api.md    # CLI + API reference
```

## Agent workflow pattern

When asked to work on an unfamiliar codebase:

```
1. Check if .rekipedia/wiki/ already exists in the repo
   → If yes: read index.md + architecture.md for context, then ask specific questions
   → If no: run rekipedia scan /path/to/repo --no-docker

2. Read index.md first (always)
   → Understand: what does this project do? main entry points? repo structure?

3. Read architecture.md or architecture-overview.md
   → Understand: component relationships, data flow, key abstractions

4. For specific tasks, ask targeted questions:
   rekipedia ask /path/to/repo "Where is [feature] implemented?"
   rekipedia ask /path/to/repo "What's the interface for [class]?"

5. Use symbol citations in wiki pages to jump to exact source lines:
   [ClassName](src/module.py#L42) → read that file at that line
```

## Environment variables

| Variable | Purpose |
|---|---|
| `OPENAI_API_KEY` | Use OpenAI models (default: gpt-4o) |
| `ANTHROPIC_API_KEY` | Use Anthropic models (Claude) |
| `REKIPEDIA_MODEL` | Override default model |
| `REKIPEDIA_BASE_URL` | Custom OpenAI-compatible endpoint |
| `REKIPEDIA_PLANNER_TIMEOUT` | Timeout for PlannerAgent LLM call in seconds (default: 600) |
| `REKIPEDIA_TIMEOUT` | Timeout for page generation LLM calls in seconds (default: 180) |

## Common options

| Flag | Description |
|---|---|
| `--model MODEL` | LLM model to use (default: gpt-4o) |
| `--no-docker` | Skip Docker sandbox for static analysis |
| `--verbose` | Show debug output, LLM calls, full tracebacks |
| `--exclude SLUG` | Skip specific wiki pages |
| `--only SLUG` | Only generate specific pages |
| `--output DIR` | Custom output directory (default: .rekipedia/) |

## Pitfalls

- **M1/ARM Mac**: install with `uv tool install` (not pip) to get correct architecture wheels
- **Large repos**: first scan can take 3–5 min; subsequent `update` is faster
- **Private repos**: no data leaves your machine — LLM calls use your own API keys
- **Model errors**: if scan fails, try `--verbose` to see the exact LLM error
- **Stale wiki**: run `rekipedia update` after significant code changes

## Source

GitHub: https://github.com/unrealandychan/rekipedia
