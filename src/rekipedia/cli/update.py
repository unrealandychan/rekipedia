"""`rekipedia update` command — incremental refresh."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from rekipedia.models.contracts import LLMConfig

console = Console()


def _load_config(repo: Path) -> dict:
    from rekipedia.config.loader import load_config
    return load_config(repo)


@click.command("update")
@click.argument(
    "repo",
    default=".",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
)
@click.option("--model", default=None, envvar="REKIPEDIA_MODEL", help="LLM model override.")
@click.option("--no-docker", is_flag=True, default=False, help="Skip Docker, run extractors in-process.")
@click.option("--output-dir", default=None, type=click.Path(path_type=Path), help="Output directory (default: REPO/.rekipedia).")
@click.option("--languages", "-l", default=None, help="Comma-separated list of languages to include, e.g. python,typescript,go. Default: all.")
@click.option("--impact-only", is_flag=True, default=False, help="BFS-selective regeneration: only re-generate wiki pages for transitively affected modules.")
def update_cmd(repo: Path, model: str | None, no_docker: bool, output_dir: Path | None, languages: str | None, impact_only: bool) -> None:
    """Incrementally refresh the wiki for files changed since the last scan.

    Re-extracts only changed files and re-synthesises all wiki pages.
    Falls back to a full scan if no previous successful scan exists.

    \b
    Examples:
        rekipedia update .
        rekipedia update ./my-project --no-docker
        rekipedia update . --impact-only
        REKIPEDIA_MODEL=gpt-4o rekipedia update .
    """
    repo = repo.resolve()
    output_dir = (output_dir or repo / ".rekipedia").resolve()

    cfg = _load_config(repo)
    llm_cfg_raw = cfg.get("llm", {})

    llm_config = LLMConfig(
        model=os.environ.get("REKIPEDIA_MODEL") or model or llm_cfg_raw.get("model", "ollama/llama4"),
        api_key=os.environ.get("REKIPEDIA_API_KEY") or llm_cfg_raw.get("api_key", ""),
        base_url=os.environ.get("REKIPEDIA_BASE_URL") or llm_cfg_raw.get("base_url", ""),
        temperature=llm_cfg_raw.get("temperature", 0.2),
    )

    console.print(f"[bold green]rekipedia update[/bold green] {repo}")
    console.print(f"  model    : [cyan]{llm_config.model}[/cyan]")
    console.print(f"  output   : [cyan]{output_dir}[/cyan]")
    console.print(f"  runner   : [cyan]{'local (--no-docker)' if no_docker else 'auto'}[/cyan]")

    if not impact_only:
        console.print(
            "  [dim]Tip: use [bold]--impact-only[/bold] for BFS-selective wiki regeneration "
            "(skips unaffected modules, reducing LLM calls by 80-90% on large repos).[/dim]"
        )

    lang_list: list[str] | None = (
        [lang.strip().lower() for lang in languages.split(",") if lang.strip()] if languages else None
    )
    if lang_list:
        console.print(f"  languages: [cyan]{', '.join(lang_list)}[/cyan]")
    if impact_only:
        console.print("  [bold cyan]impact-only[/bold cyan]: BFS-selective wiki regeneration enabled")

    from rekipedia.orchestrator.run_update import run_update

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("Starting…", total=None)

        def _log(msg: str) -> None:
            progress.update(task, description=msg)

        try:
            run_update(
                repo_root=repo,
                output_dir=output_dir,
                llm_config=llm_config,
                force_local=no_docker,
                progress=_log,
                languages=lang_list,
                impact_only=impact_only,
            )
        except Exception as exc:
            console.print(f"[bold red]Error:[/bold red] {exc}")
            sys.exit(1)

    console.print("[bold green]✓ Update complete[/bold green]")
    console.print(f"  Wiki pages  : {output_dir / 'wiki'}")
    console.print(f"  Diagrams    : {output_dir / 'diagrams'}")
    console.print(f"  Manifest    : {output_dir / 'exports' / 'manifest.json'}")
    console.print(f"  Database    : {output_dir / 'store.db'}")
