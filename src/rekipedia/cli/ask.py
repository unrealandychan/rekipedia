"""`rekipedia ask` — interactive grounded Q&A REPL."""
from __future__ import annotations

import os
from pathlib import Path

import click
import pyfiglet
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule
from rich.spinner import Spinner
from rich.text import Text

from rekipedia.models.contracts import LLMConfig

console = Console()

# ── Streaming config ─────────────────────────────────────────────────────────
# Streaming is ON by default. Disable via REKIPEDIA_STREAM=0 or --no-stream flag.
_STREAM_DEFAULT = os.environ.get("REKIPEDIA_STREAM", "1") != "0"


def _print_banner() -> None:
    """Print the REKIPEDIA ASCII art banner (two-line ansi_shadow layout)."""
    try:
        line1 = pyfiglet.figlet_format("REKI", font="ansi_shadow").rstrip("\n")
        line2 = pyfiglet.figlet_format("PEDIA", font="ansi_shadow").rstrip("\n")
    except pyfiglet.FontNotFound:
        line1 = pyfiglet.figlet_format("REKI", font="standard").rstrip("\n")
        line2 = pyfiglet.figlet_format("PEDIA", font="standard").rstrip("\n")
    console.print(Text(line1, style="bold cyan"))
    console.print(Text(line2, style="bold bright_cyan"))
    console.print("  📖  [bold cyan]Repository → Wiki[/bold cyan]  ·  [dim]powered by LLM[/dim]\n")


def _load_config(repo: Path) -> dict:
    from rekipedia.config.loader import load_config
    return load_config(repo)


def _build_llm_config(repo: Path, model: str | None) -> LLMConfig:
    cfg = _load_config(repo)
    llm_cfg_raw = cfg.get("llm", {})
    return LLMConfig(
        model=os.environ.get("REKIPEDIA_MODEL") or model or llm_cfg_raw.get("model", "ollama/llama4"),
        api_key=os.environ.get("REKIPEDIA_API_KEY") or llm_cfg_raw.get("api_key", ""),
        base_url=os.environ.get("REKIPEDIA_BASE_URL") or llm_cfg_raw.get("base_url", ""),
        temperature=llm_cfg_raw.get("temperature", 0.2),
    )


import re as _re


def _print_answer_citations(answer: str, repo_root: Path, console) -> None:
    """Print OSC-8 hyperlinks for any ``file:line`` references found in *answer*.

    Does nothing if no references are found or if OSC-8 is not supported.
    """
    from rekipedia.utils.terminal_links import file_hyperlink, osc8_supported

    if not osc8_supported():
        return

    # Match patterns like `src/foo.py:42` or src/foo.py:42
    pattern = _re.compile(r"`?(\S+\.(?:py|ts|tsx|go|rs|java|js|jsx|cpp|c|h))\s*:\s*(\d+)`?")
    matches = pattern.findall(answer)
    if not matches:
        return

    seen: set[str] = set()
    citations = []
    for filepath, lineno in matches:
        key = f"{filepath}:{lineno}"
        if key not in seen:
            seen.add(key)
            citations.append((filepath, int(lineno)))

    console.print("\n[dim]─── Sources ─────────────────────────────────[/dim]")
    for i, (filepath, lineno) in enumerate(citations, 1):
        link = file_hyperlink(filepath, lineno, repo_root=str(repo_root))
        console.print(f"  [dim]{i}.[/dim] {link}")
    console.print("[dim]────────────────────────────────────────────[/dim]")


def _answer_streaming(
    question: str,
    repo: Path,
    output_dir: Path,
    llm_config: LLMConfig,
    history: list[dict],
    *,
    stream: bool = True,
    pinned_files: list[str] | None = None,
) -> str | None:
    """Run one Q&A turn: spinner while waiting, then stream tokens via rich.Live.

    Args:
        question: The user's question.
        repo: Repository root.
        output_dir: `.rekipedia/` directory.
        llm_config: LLM settings.
        history: Conversation history.
        stream: If True (default), stream tokens with rich.Live Markdown rendering.
                If False, wait for full response then print at once.

    Returns:
        The full answer string, or None on error.
    """
    from rekipedia.orchestrator.run_ask import run_ask, stream_ask

    # Print question header
    console.print(Rule(style="dim"))
    console.print(f"[bold bright_yellow]❯[/bold bright_yellow] {question}\n")

    console.print(Rule("[bold bright_green]◆ Answer[/bold bright_green]", style="bright_green"))

    if not stream:
        # ── Non-streaming mode: spinner → full response ────────────────
        spinner_text = Spinner("dots", text=Text(" Searching wiki & reasoning…", style="dim"))
        answer: str | None = None
        with Live(spinner_text, console=console, refresh_per_second=12, transient=True):
            try:
                answer = run_ask(
                    question=question,
                    repo_root=repo,
                    output_dir=output_dir,
                    llm_config=llm_config,
                    history=history,
                    pinned_context=pinned_files,
                )
            except (RuntimeError, Exception) as exc:
                console.print(f"[bold red]Error:[/bold red] {exc}")
                return None
        console.print(Markdown(answer))
        _print_answer_citations(answer, repo, console)
        console.rule(style="dim")
        return answer

    # ── Streaming mode: spinner until first chunk, then live Markdown ──
    try:
        chunks_iter = stream_ask(
            question=question,
            repo_root=repo,
            output_dir=output_dir,
            llm_config=llm_config,
            history=history,
            pinned_context=pinned_files,
        )
    except (RuntimeError, Exception) as exc:
        console.print(f"[bold red]Error:[/bold red] {exc}")
        return None

    # Show spinner while waiting for first chunk
    spinner_text = Spinner("dots", text=Text(" Searching wiki & reasoning…", style="dim"))
    with Live(spinner_text, console=console, refresh_per_second=12, transient=True):
        try:
            first_chunk = next(chunks_iter)  # type: ignore[arg-type]
        except StopIteration:
            first_chunk = ""
        except Exception as exc:
            console.print(f"[bold red]LLM error:[/bold red] {exc}")
            return None

    # Phase 2: accumulate + render with rich.Live Markdown
    answer_parts = [first_chunk]
    try:
        with Live(
            Markdown(first_chunk),
            console=console,
            refresh_per_second=15,
        ) as live:
            for chunk in chunks_iter:  # type: ignore[union-attr]
                answer_parts.append(chunk)
                live.update(Markdown("".join(answer_parts)))
    except Exception as exc:
        console.print(f"\n[bold red]Stream error:[/bold red] {exc}")

    console.rule(style="dim")
    return "".join(answer_parts)


@click.command("ask")
@click.argument("question_arg", metavar="QUESTION", default=None, required=False)
@click.option("--question", "-q", default=None, help="Single question (non-interactive mode).")
@click.option(
    "--repo",
    default=".",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Repository root (default: current directory).",
)
@click.option("--model", default=None, envvar="REKIPEDIA_MODEL", help="LLM model override.")
@click.option("--output-dir", default=None, type=click.Path(path_type=Path), help="Output directory.")
@click.option("--history-limit", default=10, show_default=True, help="Max conversation turns to keep in context.")
@click.option("--no-save-session", is_flag=True, default=False, help="Do not save session history to disk.")
@click.option("--no-rewrite", is_flag=True, default=False, help="Disable silent query rewriting.")
@click.option(
    "--no-stream",
    is_flag=True,
    default=False,
    envvar="REKIPEDIA_STREAM",
    help=(
        "Disable streaming — wait for the full response before printing. "
        "Also controlled by REKIPEDIA_STREAM=0 env var."
    ),
)
@click.option(
    "--context", "-c",
    "pinned_files",
    multiple=True,
    metavar="FILE[:SYMBOL]",
    help="Pin a file (or file:symbol) into context. Can be repeated.",
)
def ask_cmd(
    question_arg: str | None,
    question: str | None,
    repo: Path,
    model: str | None,
    output_dir: Path | None,
    history_limit: int,
    no_save_session: bool,
    no_rewrite: bool,
    no_stream: bool,
    pinned_files: tuple[str, ...],
) -> None:
    """Interactive grounded Q&A about the scanned repository.

    Optionally pass QUESTION directly as a positional argument for single-shot mode.
    Starts a REPL loop if no question is provided — ask until you press Ctrl+C.
    Answers are streamed token-by-token with rich Markdown rendering (default).
    Use --no-stream or REKIPEDIA_STREAM=0 to wait for the full response first.
    Conversation history is kept for multi-turn context (--history-limit turns).

    \\b
    Examples:
        rekipedia ask                                   # interactive REPL
        rekipedia ask "How does the auth flow work?"    # positional single-shot
        rekipedia ask -q "What are the entry points?"  # flag single-shot
        rekipedia ask --no-stream                       # disable streaming
        rekipedia ask --repo ./my-project
        rekipedia ask --history-limit 20
    """
    import datetime
    import json as _json

    import sys

    repo = repo.resolve()
    output_dir = (output_dir or repo / ".rekipedia").resolve()
    llm_config = _build_llm_config(repo, model)

    # ── Early API key validation (issue #156) ────────────────────────────────
    model_name = os.environ.get("REKIPEDIA_MODEL") or llm_config.model
    base_url = os.environ.get("REKIPEDIA_BASE_URL") or llm_config.base_url

    _has_api_key = bool(
        os.environ.get("REKIPEDIA_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or os.environ.get("ANTHROPIC_API_KEY")
        or os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
        or llm_config.api_key
    )
    _needs_api_key = not model_name.startswith("ollama/") and not bool(base_url)

    if _needs_api_key and not _has_api_key:
        console.print("[bold red]✗[/bold red]  No LLM API key found.")
        console.print(
            "   Set [bold]REKIPEDIA_API_KEY[/bold] (or [bold]OPENAI_API_KEY[/bold]) before running [bold]reki ask[/bold]."
        )
        console.print(
            "   Other providers: [bold]REKIPEDIA_MODEL[/bold]=anthropic/claude-... [bold]REKIPEDIA_API_KEY[/bold]=sk-ant-... reki ask ..."
        )
        console.print("   Tip: run [bold]`reki scan . --no-llm`[/bold] for static analysis without an API key.")
        sys.exit(1)
    # ─────────────────────────────────────────────────────────────────────────
    # ─────────────────────────────────────────────────────────────────────────

    if no_rewrite:
        os.environ["REKIPEDIA_QUERY_REWRITE"] = "0"

    # Resolve streaming preference: --no-stream flag OR REKIPEDIA_STREAM=0
    use_stream = not no_stream and _STREAM_DEFAULT

    # Resolve question: positional arg takes precedence over -q flag
    single_question = question_arg or question

    # Conversation history: [{role, content}, ...]
    history: list[dict] = []

    def _append_history(q: str, answer: str) -> None:
        history.append({"role": "user", "content": q})
        history.append({"role": "assistant", "content": answer})
        # Keep only last history_limit * 2 messages (each turn = 2 msgs)
        max_msgs = history_limit * 2
        if len(history) > max_msgs:
            del history[:-max_msgs]

    def _save_session() -> None:
        if no_save_session or not history:
            return
        sessions_dir = output_dir / "sessions"
        sessions_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%dT%H%M%S")
        session_file = sessions_dir / f"{ts}.json"
        session_file.write_text(
            _json.dumps({"turns": history, "model": llm_config.model}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        console.print(f"[dim]Session saved → {session_file}[/dim]")

    if single_question:
        # Single-shot mode (no session save)
        _print_banner()
        _answer_streaming(single_question, repo, output_dir, llm_config, history=[], stream=use_stream, pinned_files=list(pinned_files))
        return

    # Interactive REPL
    _print_banner()

    wiki_dir = output_dir / "wiki"
    stream_label = "[dim]streaming[/dim]" if use_stream else "[dim]buffered[/dim]"
    panel_content = (
        f"[bold]Model[/bold]   [cyan]{llm_config.model}[/cyan]\n"
        f"[bold]Repo[/bold]    [cyan]{repo}[/cyan]\n"
        f"[bold]Wiki[/bold]    [cyan]{wiki_dir}/[/cyan]\n"
        f"[bold]History[/bold] [cyan]{history_limit} turns[/cyan]  "
        f"[bold]Output[/bold] {stream_label}\n\n"
        "[dim]Ask anything about the codebase. Type 'exit' or Ctrl+C to quit.[/dim]"
    )
    console.print(Panel(panel_content, title=" rekipedia ask ", border_style="cyan"))
    console.print()

    turn = 0
    while True:
        turn += 1
        try:
            user_input = console.input(f"\n[bold bright_yellow][{turn}] ❯ [/bold bright_yellow]").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]── session ended ──[/dim]")
            _save_session()
            break

        if not user_input:
            turn -= 1
            continue
        if user_input.lower() in ("exit", "quit", "q"):
            console.print("\n[dim]── session ended ──[/dim]")
            _save_session()
            break

        answer = _answer_streaming(user_input, repo, output_dir, llm_config, history=list(history), stream=use_stream, pinned_files=list(pinned_files))
        if answer:
            _append_history(user_input, answer)
