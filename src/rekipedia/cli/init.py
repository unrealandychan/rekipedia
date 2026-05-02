"""`rekipedia init` command — scaffold the .rekipedia/ bundle in a repo."""
from __future__ import annotations

from pathlib import Path

import click
import yaml
from rich.console import Console

console = Console()

_DEFAULT_CONFIG: dict = {
    "version": 1,
    "ignore": [
        ".git",
        "node_modules",
        "__pycache__",
        ".rekipedia",
    ],
    "languages": ["python", "typescript"],
    "llm": {
        "model": "ollama/llama4",
        "api_key": "",
        "base_url": "",
        "temperature": 0.2,
    },
}

_GITIGNORE_ENTRY = ".rekipedia/store.db\n"


def run_init(repo_path: Path) -> None:
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
            yaml.dump(_DEFAULT_CONFIG, default_flow_style=False, sort_keys=False),
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
def init_cmd(repo: Path) -> None:
    """Initialise rekipedia in REPO (default: current directory)."""
    run_init(repo.resolve())
