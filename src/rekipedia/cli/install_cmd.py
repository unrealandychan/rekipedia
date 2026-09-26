"""Multi-platform Agent Skill installer for rekipedia (Pi, Claude Code, Cursor, Codex, Agent-Skills)."""
from __future__ import annotations

import os
from pathlib import Path

import click
from rich.console import Console

console = Console()

SKILL_TEMPLATE = """---
name: rekipedia
description: AI Codebase Intelligence & Graph Navigation. Ask questions about architecture, trace dependencies, inspect symbols, and navigate unfamiliar repos with zero hallucinations.
triggers:
  - user asks about codebase architecture, design patterns, or entry points
  - before refactoring or touching unfamiliar files
  - user asks "how does X connect to Y" or "explain symbol X"
  - before code reviews or large feature planning
---

# rekipedia — Codebase Intelligence for Coding Agents

Use `rekipedia` CLI and MCP tools to understand codebases instantly. Instead of reading dozens of source files manually, query the structured knowledge store and graph.

## When to use rekipedia

1. **Architecture & Overview**:
   ```bash
   reki ask "What is the architectural pattern and main flow?"
   reki ask "What are the entry points?"
   ```

2. **Inspect a Symbol**:
   ```bash
   reki explain "<SymbolName>"
   ```
   Outputs exact file:line definition, caller/callee degrees, confidence tags (`[EXTRACTED]`/`[INFERRED]`), and design pattern memberships.

3. **Trace Paths & Connections**:
   ```bash
   reki path "<SourceSymbol>" "<TargetSymbol>"
   ```
   Traces the shortest directed path hop-by-hop with relationship kinds.

4. **Blast Radius & Refactoring Impact**:
   ```bash
   reki impact <file_path>
   reki hotspots
   ```

5. **Update Index After Edits**:
   ```bash
   reki update .
   ```

## Agent Rules
- Consult `reki ask` or `reki explain` before grepping raw files.
- If unindexed files exist, run `reki update .` to keep graph fresh.
"""

CURSOR_MDC_TEMPLATE = """---
description: rekipedia Codebase Intelligence and Dependency Navigation
globs: *
---

# rekipedia Agent Rules

When working in this codebase:
- Query rekipedia before raw file grepping: `reki ask "<question>"`
- Inspect unfamiliar symbols: `reki explain <Symbol>`
- Trace connections between components: `reki path <A> <B>`
- After modifying files, keep knowledge graph synchronized: `reki update .`
"""


def detect_environment() -> str:
    """Detect the current AI assistant environment."""
    if os.environ.get("PI_SESSION_ID") or os.environ.get("PI_MODEL") or Path.home().joinpath(".pi").exists():
        return "pi"
    if os.environ.get("CLAUDE_CODE") or Path.home().joinpath(".claude").exists():
        return "claude"
    if Path(".cursor").exists() or Path.home().joinpath(".cursor").exists():
        return "cursor"
    if os.environ.get("CODEX_ENV") or Path.home().joinpath(".codex").exists():
        return "codex"
    return "agents"


def install_skill_files(
    platform: str,
    project: bool = False,
    repo_root: Path | None = None,
) -> list[Path]:
    """Install rekipedia skill files for the specified platform.

    Returns a list of written paths.
    """
    repo = repo_root or Path.cwd()
    home = Path.home()
    written: list[Path] = []

    if platform == "pi":
        target_dir = repo / ".pi" / "agent" / "skills" / "rekipedia" if project else home / ".pi" / "agent" / "skills" / "rekipedia"
        target_dir.mkdir(parents=True, exist_ok=True)
        skill_file = target_dir / "SKILL.md"
        skill_file.write_text(SKILL_TEMPLATE, encoding="utf-8")
        written.append(skill_file)

    elif platform == "claude":
        target_dir = repo / ".claude" / "skills" / "rekipedia" if project else home / ".claude" / "skills" / "rekipedia"
        target_dir.mkdir(parents=True, exist_ok=True)
        skill_file = target_dir / "SKILL.md"
        skill_file.write_text(SKILL_TEMPLATE, encoding="utf-8")
        written.append(skill_file)

    elif platform == "cursor":
        target_dir = repo / ".cursor" / "rules" if project else home / ".cursor" / "rules"
        target_dir.mkdir(parents=True, exist_ok=True)
        rule_file = target_dir / "rekipedia.mdc"
        rule_file.write_text(CURSOR_MDC_TEMPLATE, encoding="utf-8")
        written.append(rule_file)

    elif platform == "codex":
        target_dir = repo / ".codex" / "skills" / "rekipedia" if project else home / ".codex" / "skills" / "rekipedia"
        target_dir.mkdir(parents=True, exist_ok=True)
        skill_file = target_dir / "SKILL.md"
        skill_file.write_text(SKILL_TEMPLATE, encoding="utf-8")
        written.append(skill_file)

    elif platform in ("agents", "skills"):
        target_dir = repo / ".agents" / "skills" / "rekipedia" if project else home / ".agents" / "skills" / "rekipedia"
        target_dir.mkdir(parents=True, exist_ok=True)
        skill_file = target_dir / "SKILL.md"
        skill_file.write_text(SKILL_TEMPLATE, encoding="utf-8")
        written.append(skill_file)

    elif platform == "copilot":
        target_dir = repo / ".github"
        target_dir.mkdir(parents=True, exist_ok=True)
        instructions_file = target_dir / "copilot-instructions.md"
        existing = instructions_file.read_text(encoding="utf-8") if instructions_file.exists() else ""
        if "rekipedia" not in existing:
            new_content = (existing + "\n\n" + SKILL_TEMPLATE).strip()
            instructions_file.write_text(new_content, encoding="utf-8")
        written.append(instructions_file)

    else:
        raise ValueError(f"Unknown platform: {platform}. Supported: pi, claude, cursor, codex, agents, copilot.")

    return written


@click.command("install")
@click.option(
    "--platform", "-p",
    type=click.Choice(["auto", "pi", "claude", "cursor", "codex", "agents", "skills", "copilot"], case_sensitive=False),
    default="auto",
    show_default=True,
    help="Target agent platform to install the skill for.",
)
@click.option(
    "--project",
    is_flag=True,
    default=False,
    help="Install locally in current repository instead of user global profile.",
)
def install_cmd(platform: str, project: bool) -> None:
    """Register rekipedia skill with your AI coding assistant (Pi, Claude Code, Cursor, Codex, Agent-Skills).

    \b
    Examples:
        reki install
        reki install --platform pi
        reki install --platform claude --project
        reki install --platform cursor
    """
    resolved_platform = detect_environment() if platform == "auto" else platform.lower()
    scope_str = "project" if project else "global"

    console.print(f"[bold cyan]Installing rekipedia skill for {resolved_platform} ({scope_str} scope)…[/bold cyan]")
    try:
        written_files = install_skill_files(resolved_platform, project=project)
        for f in written_files:
            console.print(f"  [green]✓[/green] Written: [bold]{f}[/bold]")
        console.print(f"[bold green]Successfully installed rekipedia skill for {resolved_platform}![/bold green]")
        if project:
            console.print("[dim]Tip: commit these files with git so teammates also get the skill.[/dim]")
    except Exception as exc:
        console.print(f"[bold red]Installation failed:[/bold red] {exc}")
