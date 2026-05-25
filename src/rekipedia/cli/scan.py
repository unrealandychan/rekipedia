"""`rekipedia scan` command — full repo analysis."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from rekipedia.config.loader import load_config
from rekipedia.models.contracts import LLMConfig

console = Console()


def _load_config(repo: Path) -> dict:
    return load_config(repo)


def _run_with_refactor(repo: Path, output_dir: Path, verbose: bool) -> None:
    """Run static analysis and write REFACTOR.md after a scan."""
    try:
        from rekipedia.cli.refactor import _build_static_report, _static_walk
        findings = _static_walk(repo)
        report = _build_static_report(repo, findings)
        out_path = output_dir / "REFACTOR.md"
        output_dir.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report, encoding="utf-8")
        console.print(f"  REFACTOR.md : {out_path}")
    except Exception as exc:
        if verbose:
            console.print_exception(show_locals=True)
        else:
            console.print(f"[yellow]  --with-refactor failed: {exc}[/yellow]")


@click.command("scan")
@click.argument(
    "repo",
    default=".",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
)
@click.option("--model", default=None, envvar="REKIPEDIA_MODEL", help="LLM model override.")
@click.option("--no-docker", is_flag=True, default=False, help="Skip Docker, run extractors in-process.")
@click.option("--output-dir", default=None, type=click.Path(path_type=Path), help="Output directory (default: REPO/.rekipedia).")
@click.option("--verbose", "-v", is_flag=True, default=False, help="Enable debug logging (litellm, HTTP, full tracebacks).")
@click.option("--embed-model", default=None, envvar="REKIPEDIA_EMBED_MODEL", help="Embedding model for RAG index (e.g. text-embedding-3-small). If set, auto-embeds after scan.")
@click.option("--embed-provider", default=None, envvar="REKIPEDIA_EMBED_PROVIDER", help="Embedding provider prefix (e.g. openai, ollama, azure). Combined with --embed-model as 'provider/model'.")
@click.option("--languages", "-l", default=None, help="Comma-separated list of languages to include, e.g. python,typescript,go. Default: all.")
@click.option("--force", "-f", is_flag=True, default=False, help="Force re-scan even if a completed scan already exists in the DB.")
@click.option("--no-llm", is_flag=True, default=False, help="Skip all LLM calls — run static analysis only (zero API calls, ~5-10s). All commands except `reki ask` work without an API key.")
@click.option("--stdout", "stdout_refactor", is_flag=True, default=False, help="Print REFACTOR.md to stdout after scan (useful for piping to Claude Code).")
@click.option("--with-refactor", is_flag=True, default=False, help="Auto-generate REFACTOR.md after scan completes.")
@click.option(
    "--doc-type",
    "doc_type",
    default="default",
    show_default=True,
    type=click.Choice(["default", "api-ref", "tutorial", "runbook", "adr", "changelog"], case_sensitive=False),
    help=(
        "Wiki page generation style. "
        "'default' = balanced overview; 'api-ref' = function/class reference; "
        "'tutorial' = step-by-step; 'runbook' = ops procedures; "
        "'adr' = Architecture Decision Records; 'changelog' = what changed and migration notes."
    ),
    envvar="REKIPEDIA_DOC_TYPE",
)
@click.option(
    "--focus", "-F",
    "focus",
    multiple=True,
    default=None,
    help=(
        "Only extract and document files matching this glob pattern (relative to REPO). "
        "Can be repeated: --focus src/auth/** --focus src/payment/**. "
        "Shortens scan time and generates a focused wiki for a sub-system. "
        "Set env var REKIPEDIA_FOCUS (comma-separated) as an alternative."
    ),
    envvar="REKIPEDIA_FOCUS",
)
@click.option("--workers", "-w", default=None, type=int, metavar="N",
    help="Number of parallel workers for file extraction (default: min(4, cpu_count))")
def scan_cmd(
    repo: Path,
    model: str | None,
    no_docker: bool,
    output_dir: Path | None,
    verbose: bool,
    embed_model: str | None,
    embed_provider: str | None,
    languages: str | None,
    force: bool,
    no_llm: bool,
    stdout_refactor: bool,
    with_refactor: bool,
    focus: tuple[str, ...],
    doc_type: str,
    workers: int | None,
) -> None:
    """Scan REPO and (re)build the rekipedia knowledge store.

    Produces wiki pages in OUTPUT_DIR/wiki/, diagrams in OUTPUT_DIR/diagrams/,
    a JSON manifest in OUTPUT_DIR/exports/manifest.json, and a refactoring
    report in OUTPUT_DIR/REFACTOR.md + OUTPUT_DIR/refactor_report.json.

    By default, scan is skipped if a completed scan already exists in the DB.
    Use --force to re-scan regardless.

    \b
    Examples:
        rekipedia scan .
        rekipedia scan ./my-project --no-docker
        rekipedia scan . --verbose
        rekipedia scan . --force          # force re-scan even if DB exists
        rekipedia scan . --no-llm         # static analysis only, skip LLM enrichment
        rekipedia scan . --stdout | claude # pipe refactor guide to Claude
        rekipedia scan . --with-refactor  # also generate REFACTOR.md
        REKIPEDIA_MODEL=gpt-4o rekipedia scan .
    """
    repo = repo.resolve()
    output_dir = (output_dir or repo / ".rekipedia").resolve()

    # ── Workers resolution ─────────────────────────────────────────────────────
    if workers is None:
        env_val = os.environ.get('REKIPEDIA_WORKERS', '0')
        workers = int(env_val) or min(4, os.cpu_count() or 4)

    # ── Skip if already scanned (unless --force) ──────────────────────────────
    if not force:
        db_path = output_dir / "store.db"
        if db_path.exists():
            try:
                from rekipedia.storage.sqlite_store import SqliteStore
                with SqliteStore(db_path) as _store:
                    _existing = _store.get_latest_run_id(str(repo))
                if _existing:
                    console.print(
                        f"[bold yellow]⏭  Scan skipped[/bold yellow] — completed scan already exists "
                        f"([dim]{db_path}[/dim])\n"
                        f"  Use [bold]--force[/bold] / [bold]-f[/bold] to re-scan."
                    )
                    return
            except Exception:
                pass  # DB unreadable — proceed with scan

    cfg = _load_config(repo)
    llm_cfg_raw = cfg.get("llm", {})

    llm_config = LLMConfig(
        model=model or llm_cfg_raw.get("model", "ollama/llama4"),
        api_key=llm_cfg_raw.get("api_key", ""),
        base_url=llm_cfg_raw.get("base_url", ""),
        temperature=llm_cfg_raw.get("temperature", 0.2),
        embed_model=embed_model or llm_cfg_raw.get("embed_model", ""),
        embed_provider=embed_provider or llm_cfg_raw.get("embed_provider", ""),
        embed_api_key=llm_cfg_raw.get("embed_api_key") or llm_cfg_raw.get("api_key", ""),
        embed_base_url=llm_cfg_raw.get("embed_base_url") or "",
    )

    console.print(f"[bold green]rekipedia scan[/bold green] {repo}")
    console.print(f"  model    : [cyan]{llm_config.model}[/cyan]")
    console.print(f"  output   : [cyan]{output_dir}[/cyan]")
    console.print(f"  runner   : [cyan]{'local (--no-docker)' if no_docker else 'auto'}[/cyan]")
    focus_list: list[str] | None = None
    if focus:
        # Support comma-separated values from env var
        focus_list = [p.strip() for item in focus for p in item.split(",") if p.strip()]
        console.print(f"  focus    : [cyan]{', '.join(focus_list)}[/cyan]")
    if doc_type != "default":
        console.print(f"  doc-type : [magenta]{doc_type}[/magenta]")
    if llm_config.embed_model:
        _em = f"{llm_config.embed_provider}/{llm_config.embed_model}" if llm_config.embed_provider else llm_config.embed_model
        console.print(f"  embed    : [cyan]{_em}[/cyan]")
        console.print(f"  embed url: [cyan]{llm_config.embed_base_url or '(default: api.openai.com)'}[/cyan]")
        console.print(f"  embed key: [cyan]{'(set)' if llm_config.embed_api_key else '(not set)'}[/cyan]")
    if verbose:
        console.print("  mode     : [yellow]verbose (debug logging ON)[/yellow]")
    # Parse languages filter — CLI flag takes priority; fall back to config.yml
    lang_list: list[str] | None = None
    if languages:
        lang_list = [lang.strip().lower() for lang in languages.split(",") if lang.strip()]
        console.print(f"  languages: [cyan]{', '.join(lang_list)}[/cyan]")
    elif cfg.get("languages"):
        lang_list = [lang.strip().lower() for lang in cfg["languages"] if lang.strip()]
        console.print(f"  languages: [cyan]{', '.join(lang_list)}[/cyan] [dim](from config.yml)[/dim]")
    else:
        console.print("  languages: [cyan]all[/cyan]")

    if workers > 1:
        console.print(f"  workers  : [cyan]{workers}[/cyan]")

    console.rule()

    from rekipedia.orchestrator.run_digest import run_digest

    # In verbose mode: print each log line directly so tqdm + log interleave cleanly
    # In normal mode: update a Rich spinner so the user sees live phase labels
    if verbose:
        def _log(msg: str) -> None:
            console.print(f"  [dim]{msg}[/dim]")

        try:
            run_digest(
                repo_root=repo,
                output_dir=output_dir,
                llm_config=llm_config,
                force_local=no_docker,
                verbose=verbose,
                progress=_log,
                languages=lang_list,
                no_llm=no_llm,
                stdout_refactor=stdout_refactor,
                focus_globs=focus_list,
                doc_type=doc_type,
                workers=workers,
            )
        except Exception:
            console.print_exception(show_locals=True)
            sys.exit(1)
    else:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            TimeElapsedColumn(),
            console=console,
            transient=False,
        ) as progress:
            task = progress.add_task("Scanning…", total=None)

            def _log(msg: str) -> None:
                progress.update(task, description=msg)

            try:
                run_digest(
                    repo_root=repo,
                    output_dir=output_dir,
                    llm_config=llm_config,
                    force_local=no_docker,
                    verbose=verbose,
                    progress=_log,
                    languages=lang_list,
                    no_llm=no_llm,
                    stdout_refactor=stdout_refactor,
                    focus_globs=focus_list,
                    doc_type=doc_type,
                    workers=workers,
                )
            except Exception as exc:
                progress.stop()
                console.print(f"[bold red]Error:[/bold red] {exc}")
                console.print("[dim]Tip: run with --verbose for full debug output[/dim]")
                sys.exit(1)

    console.rule()
    console.print("[bold green]✓ Scan complete[/bold green]")
    console.print(f"  Wiki pages  : {output_dir / 'wiki'}")
    console.print(f"  Diagrams    : {output_dir / 'diagrams'}")
    console.print(f"  Manifest    : {output_dir / 'exports' / 'manifest.json'}")
    console.print(f"  Refactor    : {output_dir / 'REFACTOR.md'}")
    console.print(f"  Database    : {output_dir / 'store.db'}")

    # ── Auto-generate .mcp.json at repo root ──────────────────────────────────
    from rekipedia.cli.mcp_server import write_mcp_json
    write_mcp_json(repo)

    # ── Optional: generate REFACTOR.md ────────────────────────────────────────
    if with_refactor:
        console.rule()
        console.print("[bold cyan]rekipedia refactor[/bold cyan] (triggered by --with-refactor)")
        _run_with_refactor(repo, output_dir, verbose)
