"""`rekipedia init` command — scaffold the .rekipedia/ bundle in a repo."""
from __future__ import annotations

from pathlib import Path

import click
from rich.console import Console

console = Console()

_DEFAULT_CONFIG_YAML = """\
# Project-level config — overrides ~/.config/rekipedia/config.yml
# rekipedia configuration — .rekipedia/config.yml
# Run `reki init` to regenerate this file.
version: 1

# ── Files to ignore (gitignore-style patterns) ───────────────────────────────
ignore:
  - .git
  - node_modules
  - __pycache__
  - .rekipedia

# ── Language filter ───────────────────────────────────────────────────────────
# Controls which source files are scanned.
#
# Supported values:
#   python, typescript, javascript, go, rust, java, kotlin, ruby,
#   markdown, yaml, json, toml, sql, shell, docker, terraform, html, css, scss
#
# Set to `null` (or remove the key) to scan ALL supported languages — recommended
# for mixed-language repos (e.g. Python + Go).
#
# Examples:
#   languages: null           # scan everything (DEFAULT)
#   languages: [python]       # Python only
#   languages: [python, go]   # Python + Go
#   languages: [typescript, javascript, go]
#
languages:   # null = all languages

# ── LLM settings ─────────────────────────────────────────────────────────────
llm:
  # Model in litellm format: provider/model-name  (can override per-project)
  # Examples:
  #   ollama/llama4          (local Ollama — default)
  #   openai/gpt-4o
  #   anthropic/claude-sonnet-4
  #   openrouter/google/gemini-2.5-pro
  # model: ollama/llama4
  model: ollama/llama4
  # api_key, base_url, embed_api_key, embed_base_url — set in global config
  # (~/.config/rekipedia/config.yml) or via env vars (REKIPEDIA_API_KEY, etc.)
  temperature: 0.2

  # ── Embedding model (for semantic search / RAG) ───────────────────────────
  # Leave blank to use the same model as above (not recommended for large repos).
  # embed_model: text-embedding-3-small
  # embed_provider: openai

# ── External connectors ───────────────────────────────────────────────────────
# connectors:
#   github:
#     token: ""          # or set REKIPEDIA_GITHUB_TOKEN env var
#     repo: ""           # e.g. "owner/repo" — auto-detected from git remote if empty
#     max_issues: 500    # cap how many issues to index
#     max_prs: 200       # cap how many PRs to index
"""

_GITIGNORE_ENTRY = ".rekipedia/store.db\n"

_AGENT_CONTENT_TEMPLATE = """\
# rekipedia — AI Codebase Intelligence

This repository uses [rekipedia](https://github.com/unrealandychan/rekipedia) to maintain a \
structured wiki, symbol index, and RAG knowledge store in `.rekipedia/`.

> **You MUST use rekipedia tools before answering architecture questions, tracing flows, or \
locating code.** Do not guess — ask rekipedia first.

## Mandatory Usage Rules

**Before you answer ANY of the following, run the corresponding reki command:**

| Situation | Command to run FIRST |
|-----------|---------------------|
| "How does X work?" / "Explain the auth flow" | `reki ask "how does X work?"` |
| "Where is Y implemented?" / "Find the payment handler" | `reki ask "where is Y implemented?"` |
| "What calls this function?" / "What depends on X?" | `reki ask "what calls X?"` |
| Implementing a new feature | `reki ask "what modules are related to <feature area>?"` |
| Fixing a bug | `reki ask "how does <affected subsystem> work?"` |
| Onboarding to an unfamiliar area | `reki ask "give me an overview of <module>"` |
| After editing multiple files | `reki update .` |

**Never answer architecture or flow questions from memory alone.** Always ground your answer \
with rekipedia output — include the file:line citations it provides.

## Commands

| Command | What it does |
|---------|-------------|
| `reki ask "<question>"` | Ask anything — grounded answers with file:line citations |
| `reki scan .` | Full scan — extract symbols, generate wiki, build knowledge store |
| `reki update .` | Incremental refresh — only re-processes changed files |
| `reki serve .` | Start local web UI at http://127.0.0.1:7070 |
| `reki embed .` | Build / rebuild semantic search index (FAISS) for RAG |
| `reki export .` | Export wiki (--format md|zip|json) |
| `reki onboard .` | Generate onboarding guide for new contributors |
| `reki diff .` | Impact analysis for uncommitted git changes |
| `reki tour .` | Guided learning walkthrough ordered by dependency depth |
| `reki domain .` | Classify codebase into business domains |

## MCP Server (Recommended for Claude Code / Cursor)

`.mcp.json` in this repo auto-configures the MCP server. Available tools:

| MCP Tool | When to use |
|----------|------------|
| `ask` | Any architecture / flow question |
| `search_nodes` | Find symbols, classes, functions by name or description |
| `get_context` | Get full context for a file or symbol |
| `get_relationships` | Trace call graphs and import chains |
| `get_hub_nodes` | Find the most critical / highly-connected modules |
| `get_impact` | What breaks if I change this file? |

Start the MCP server: `reki mcp`

## Setup (first time)

```bash
reki scan .     # generates wiki + knowledge store (~30s for most repos)
```

The knowledge store lives in `.rekipedia/store.db` — portable, local, no cloud required.
Commit `.rekipedia/wiki/` to share knowledge with teammates.
"""


def _write_agent_files(repo_path: Path, force: bool = False) -> None:
    """Write agent instruction files for Claude Code, Codex/OpenAI, and GitHub Copilot."""
    files = [
        (repo_path / "CLAUDE.md", "Claude Code"),
        (repo_path / "AGENTS.md", "Codex / OpenAI Agents"),
        (repo_path / ".github" / "copilot-instructions.md", "GitHub Copilot"),
    ]
    for file_path, platform in files:
        if file_path.exists() and not force:
            console.print(
                f"[yellow]⚠[/yellow]  [bold]{file_path}[/bold] already exists — skipping."
            )
        else:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(_AGENT_CONTENT_TEMPLATE, encoding="utf-8")
            console.print(f"[green]✔[/green]  Created [bold]{file_path}[/bold] ({platform})")


def run_init(repo_path: Path, no_agent_files: bool = False) -> None:
    wiki_dir = repo_path / ".rekipedia"
    config_path = wiki_dir / "config.yml"
    gitignore_path = repo_path / ".gitignore"

    # Create .rekipedia/ if missing
    wiki_dir.mkdir(parents=True, exist_ok=True)

    # Write config.yml — idempotent (skip if already present)
    if config_path.exists():
        console.print(
            f"[yellow]⚠[/yellow]  [bold]{config_path}[/bold] already exists — skipping."
        )
    else:
        config_path.write_text(
            _DEFAULT_CONFIG_YAML,
            encoding="utf-8",
        )
        console.print(f"[green]✔[/green]  Created [bold]{config_path}[/bold]")

    # Append .gitignore entry — idempotent
    if gitignore_path.exists():
        existing = gitignore_path.read_text(encoding="utf-8")
        if ".rekipedia/store.db" in existing:
            console.print(
                "[yellow]⚠[/yellow]  .gitignore already contains .rekipedia/store.db — skipping."
            )
        else:
            with gitignore_path.open("a", encoding="utf-8") as fh:
                fh.write(_GITIGNORE_ENTRY)
            console.print("[green]✔[/green]  Added .rekipedia/store.db to .gitignore")
    else:
        gitignore_path.write_text(_GITIGNORE_ENTRY, encoding="utf-8")
        console.print("[green]✔[/green]  Created .gitignore with .rekipedia/store.db")

    if not no_agent_files:
        console.print()
        console.print("[bold]Writing agent instruction files…[/bold]")
        _write_agent_files(repo_path)

    console.print()
    console.print("[bold green]rekipedia initialised.[/bold green]")
    console.print(
        f"  Edit [cyan]{config_path}[/cyan] to choose your LLM provider/model, then run:"
    )
    console.print("  [bold]rekipedia scan .[/bold]")


@click.command("init")
@click.argument(
    "repo",
    default=".",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
)
@click.option(
    "--no-agent-files",
    is_flag=True,
    default=False,
    help="Skip writing CLAUDE.md, AGENTS.md, and .github/copilot-instructions.md.",
)
def init_cmd(repo: Path, no_agent_files: bool) -> None:
    """Initialise rekipedia in REPO (default: current directory)."""
    run_init(repo.resolve(), no_agent_files=no_agent_files)
