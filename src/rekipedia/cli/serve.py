"""`rekipedia serve` command — local web UI."""
from __future__ import annotations

import os
import webbrowser
from pathlib import Path

import click
import yaml

from rekipedia.models.contracts import LLMConfig


@click.command("serve")
@click.option(
    "--repo",
    default=".",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Repository root (default: current directory).",
)
@click.option("--port", default=7070, show_default=True, help="Port to listen on.")
@click.option("--host", default="127.0.0.1", show_default=True, help="Host to bind to.")
@click.option("--output-dir", default=None, type=click.Path(path_type=Path))
@click.option("--model", default=None, envvar="REKIPEDIA_MODEL")
@click.option("--open/--no-open", "open_browser", default=True, help="Auto-open browser.")
def serve_cmd(
    repo: Path,
    port: int,
    host: str,
    output_dir: Path | None,
    model: str | None,
    open_browser: bool,
) -> None:
    """Start the rekipedia web UI.

    \b
    Examples:
        rekipedia serve
        rekipedia serve --port 8080
        rekipedia serve --repo ./my-project --no-open
    """
    import uvicorn  # noqa: PLC0415 — lazy import keeps startup fast

    repo = repo.resolve()
    output_dir = (output_dir or repo / ".rekipedia").resolve()

    cfg_path = repo / ".rekipedia" / "config.yml"
    cfg = yaml.safe_load(cfg_path.read_text()) if cfg_path.exists() else {}
    llm_raw = cfg.get("llm", {}) if isinstance(cfg, dict) else {}
    llm_config = LLMConfig(
        model=os.environ.get("REKIPEDIA_MODEL") or model or llm_raw.get("model", "ollama/llama4"),
        api_key=os.environ.get("REKIPEDIA_API_KEY") or llm_raw.get("api_key", ""),
        base_url=os.environ.get("REKIPEDIA_BASE_URL") or llm_raw.get("base_url", ""),
        temperature=llm_raw.get("temperature", 0.2),
    )

    from rekipedia.server.app import create_app  # noqa: PLC0415

    app = create_app(repo_root=repo, output_dir=output_dir, llm_config=llm_config)

    url = f"http://{host}:{port}"
    click.echo(f"  rekipedia serve → {url}")
    click.echo(f"  repo       : {repo}")
    click.echo(f"  output-dir : {output_dir}")
    click.echo(f"  model      : {llm_config.model}")

    if open_browser:
        import threading  # noqa: PLC0415

        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    uvicorn.run(app, host=host, port=port, log_level="warning")
