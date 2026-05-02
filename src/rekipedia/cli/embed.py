"""rekipedia embed — build / refresh the RAG FAISS index for a scanned repo.

Usage:
    rekipedia embed [REPO_PATH] [--output-dir DIR] [--model MODEL] [--top-k N]

Embeds all source files in REPO_PATH into a FAISS index stored under
.rekipedia/rag/.  Requires a prior `rekipedia scan`.
Set REKIPEDIA_EMBED_MODEL to override the embedding model (default:
text-embedding-3-small).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import click
from rich.console import Console

console = Console()

def _check_rag_deps() -> None:
    """Raise a friendly error if faiss-cpu / numpy are not installed."""
    missing = []
    try:
        import faiss  # noqa: F401
    except ImportError:
        missing.append("faiss-cpu")
    try:
        import numpy  # noqa: F401
    except ImportError:
        missing.append("numpy")
    if missing:
        console.print(
            f"[bold red]Missing RAG dependencies:[/] {', '.join(missing)}\n"
            "Install them with:\n\n"
            "  [bold]pip install rekipedia[rag][/]\n"
            "  or: uv add 'rekipedia[rag]'\n",
            highlight=False,
        )
        raise SystemExit(1)


@click.command("embed")
@click.argument("repo_path", default=".", type=click.Path(exists=True, file_okay=False))
@click.option(
    "--output-dir",
    default=None,
    help="Path to .rekipedia/ directory (default: REPO_PATH/.rekipedia/)",
)
@click.option(
    "--model",
    default=None,
    envvar="REKIPEDIA_EMBED_MODEL",
    help="Embedding model name (e.g. text-embedding-3-small). "
    "Can also be set via REKIPEDIA_EMBED_MODEL env var.",
)
@click.option(
    "--provider",
    default=None,
    envvar="REKIPEDIA_EMBED_PROVIDER",
    help="Embedding provider (e.g. openai, ollama, azure). "
    "Combined with --model as 'provider/model' for litellm routing.",
)
@click.option(
    "--api-key",
    default=None,
    envvar="OPENAI_API_KEY",
    help="API key for the embedding provider.",
)
@click.option(
    "--base-url",
    default=None,
    envvar="REKIPEDIA_BASE_URL",
    help="Custom base URL for the embedding provider.",
)
@click.option(
    "--top-k",
    default=8,
    show_default=True,
    help="Number of chunks returned per query (informational only; stored in meta).",
)
@click.option("--verbose", "-v", is_flag=True, help="Show debug output.")
def embed_cmd(
    repo_path: str,
    output_dir: str | None,
    model: str | None,
    provider: str | None,
    api_key: str | None,
    base_url: str | None,
    top_k: int,
    verbose: bool,
) -> None:
    """Build or refresh the RAG embed index for REPO_PATH."""
    _check_rag_deps()
    import logging  # noqa: PLC0415

    if verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.WARNING)

    repo = Path(repo_path).resolve()
    out = Path(output_dir).resolve() if output_dir else repo / ".rekipedia"

    if not out.exists():
        console.print(
            f"[red]No .rekipedia directory found at {out}.[/red]\n"
            "Run [bold]rekipedia scan[/bold] first."
        )
        sys.exit(1)

    # Load config.yml first, then CLI flags / env vars override
    from rekipedia.cli.scan import _load_config  # noqa: PLC0415
    from rekipedia.models.contracts import LLMConfig  # noqa: PLC0415
    from rekipedia.rag.embedder import EmbedPipeline  # noqa: PLC0415
    from rekipedia.rag.scan_meta import patch_scan_meta  # noqa: PLC0415

    cfg = _load_config(repo)
    llm_cfg = cfg.get("llm", {})

    embed_model = model or llm_cfg.get("embed_model") or "text-embedding-3-small"
    embed_provider = provider or llm_cfg.get("embed_provider", "")
    resolved_api_key = api_key or llm_cfg.get("embed_api_key") or llm_cfg.get("api_key", "")
    resolved_base_url = base_url or llm_cfg.get("embed_base_url") or llm_cfg.get("base_url", "")

    console.print(f"[bold cyan]rekipedia embed[/bold cyan]")
    console.print(f"  repo       : {repo}")
    console.print(f"  output-dir : {out}")
    if embed_provider:
        console.print(f"  model      : {embed_provider}/{embed_model}")
    else:
        console.print(f"  model      : {embed_model}")
    console.print(f"  base_url   : {resolved_base_url or '(default: api.openai.com)'}")
    console.print(f"  api_key    : {'(set)' if resolved_api_key else '(not set)'}")
    console.print()

    llm_config = LLMConfig(
        api_key=resolved_api_key,
        base_url=resolved_base_url,
        embed_model=embed_model,
        embed_provider=embed_provider,
        embed_api_key=resolved_api_key,
        embed_base_url=resolved_base_url,
    )

    pipe = EmbedPipeline(out, llm_config)

    from tqdm import tqdm  # noqa: PLC0415

    bar = tqdm(bar_format="  {desc}", dynamic_ncols=True, leave=False)

    def _progress(msg: str) -> None:
        bar.set_description_str(msg)
        bar.refresh()

    try:
        n = pipe.build(repo, progress_cb=_progress)
        bar.set_description_str(f"✅ Done — {n} chunks indexed")
        bar.refresh()
        bar.close()

        patch_scan_meta(out, embedded=True, embed_model=embed_model)
        meta = pipe.meta()

        console.print(f"\n[green]✅ FAISS index built successfully[/green]")
        if meta:
            console.print(f"   chunks : {meta.get('n_chunks', n)}")
            console.print(f"   dim    : {meta.get('dim', '?')}")
            console.print(f"   model  : {meta.get('model', embed_model)}")
        console.print(f"\nIndex saved to [bold]{out}/rag/[/bold]")
    except Exception as exc:
        bar.close()
        console.print(f"\n[red]Embed failed:[/red] {exc}")
        if verbose:
            import traceback  # noqa: PLC0415
            traceback.print_exc()
        sys.exit(1)
