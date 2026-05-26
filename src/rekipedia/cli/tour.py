"""reki tour — generate a guided learning walkthrough sorted by dependency depth."""
from __future__ import annotations

import json
from pathlib import Path

import click
from rich.console import Console

console = Console()


@click.command("tour")
@click.argument("repo", default=".", metavar="REPO")
@click.option("--output", "-o", default=None, help="Save tour to this file")
@click.option(
    "--format", "fmt",
    default="text",
    type=click.Choice(["text", "json"]),
    help="Output format",
)
def tour_cmd(repo: str, output: str | None, fmt: str) -> None:
    """Generate a guided learning walkthrough sorted by dependency depth."""
    from rekipedia.analysis.tour import build_tour
    from rekipedia.storage.sqlite_store import SqliteStore

    repo_path = Path(repo).resolve()
    db_path = repo_path / ".rekipedia" / "store.db"
    # also check alternate name used by some commands
    if not db_path.exists():
        alt = repo_path / ".rekipedia" / "rekipedia.db"
        if alt.exists():
            db_path = alt

    if not db_path.exists():
        console.print(
            f"[red]❌ No scan found at {repo_path / '.rekipedia' / 'store.db'}"
            f" — run `reki scan .` first[/red]"
        )
        raise SystemExit(1)

    store = SqliteStore(db_path)
    with store:
        run_id = store.get_latest_run_id(str(repo_path))
        if not run_id:
            console.print(
                "[red]❌ No scan runs found — run `reki scan .` first[/red]"
            )
            raise SystemExit(1)

        tour = build_tour(store, run_id, repo_path)

    if fmt == "json":
        out_text = json.dumps(tour, indent=2)
        if output:
            Path(output).write_text(out_text)
            console.print(f"[green]✅ Tour saved to {output}[/green]")
        else:
            click.echo(out_text)
        return

    # ── text output ────────────────────────────────────────────────────────
    repo_name = Path(tour["repo"]).name
    date_str = tour["generated_at"][:10]
    total = tour["total_files"]
    phases = tour["phases"]
    non_empty = [p for p in phases if p["files"]]
    n_phases = len(non_empty)

    lines: list[str] = []
    lines.append(f"🗺️  Guided Tour — {repo_name}")
    lines.append(f"Generated {date_str} | {total} files | {n_phases} phases\n")

    for phase in phases:
        files = phase["files"]
        if not files:
            continue
        header = f"Phase {phase['phase']} — {phase['name']} ({len(files)} files)"
        lines.append(f"━━━ {header} {'━' * max(0, 50 - len(header))}")
        lines.append(f"  {phase['description']}\n")
        for idx, f in enumerate(files, 1):
            lines.append(f"  {idx}. {f['path']}")
            if f["symbols"]:
                lines.append(f"     Symbols: {', '.join(f['symbols'])}")
            lines.append(f"     {f['description']}")
            lines.append("")

    out_text = "\n".join(lines)

    if output:
        Path(output).write_text(out_text)
        console.print(f"[green]✅ Tour saved to {output}[/green]")
    else:
        click.echo(out_text)
