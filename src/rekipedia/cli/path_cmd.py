"""CLI command for tracing the shortest path between two symbols in the knowledge graph."""
from __future__ import annotations

import json
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel

console = Console()


@click.command("path")
@click.argument("from_symbol")
@click.argument("to_symbol")
@click.option(
    "--repo", "-r",
    default=".",
    type=click.Path(file_okay=False),
    help="Path to repository root (default: current directory).",
)
@click.option(
    "--json", "as_json",
    is_flag=True,
    default=False,
    help="Output results as JSON.",
)
def path_cmd(from_symbol: str, to_symbol: str, repo: str, as_json: bool) -> None:  # noqa: C901
    """Find and trace the shortest directed path between two symbols.

    \b
    Examples:
        reki path FastAPI ModelField
        reki path App.run SqliteStore
    """
    repo_root = Path(repo).resolve()
    db_path = repo_root / ".rekipedia" / "store.db"
    if not db_path.exists():
        if as_json:
            click.echo(json.dumps({"error": f"No store.db found at {db_path}. Run 'reki scan' first."}))
        else:
            console.print(f"[red]No knowledge store found at {db_path}.[/red]\nRun [bold]reki scan[/bold] first.")
        return

    from rekipedia.analysis.graph_analysis import compute_shortest_path
    from rekipedia.storage.sqlite_store import SqliteStore

    with SqliteStore(db_path) as store:
        run_id = store.get_latest_run_id(str(repo_root)) or store.latest_run_id()
        if not run_id:
            # Fallback to any run
            try:
                row = store._c.execute("SELECT id FROM scan_runs ORDER BY rowid DESC LIMIT 1").fetchone()
                if row:
                    run_id = row[0]
            except Exception:
                pass
        if not run_id:
            if as_json:
                click.echo(json.dumps({"error": "No scan runs found in database."}))
            else:
                console.print("[red]No scan runs found in database.[/red]")
            return

        rels = store.get_all_relationships(run_id)

    res = compute_shortest_path(from_symbol, to_symbol, rels)
    path_nodes = res.get("path")
    length = res.get("length")

    if not path_nodes:
        if as_json:
            click.echo(json.dumps({"path": None, "length": None, "reachable": False}))
        else:
            console.print(
                Panel(
                    f"No path found between [bold red]{from_symbol}[/bold red] and [bold red]{to_symbol}[/bold red].\n"
                    f"[dim]The two symbols are disconnected in the relationship graph.[/dim]",
                    title="Path Result",
                    border_style="red",
                )
            )
        return

    # Build edge details between consecutive hops
    rel_lookup: dict[tuple[str, str], dict] = {}
    for r in rels:
        frm = r.get("from_", "") or r.get("from", "") if isinstance(r, dict) else getattr(r, "from_", "")
        to = r.get("to", "") if isinstance(r, dict) else getattr(r, "to", "")
        if frm and to:
            rel_lookup[(frm, to)] = r

    hops = []
    for i in range(len(path_nodes) - 1):
        u, v = path_nodes[i], path_nodes[i + 1]
        edge_info = rel_lookup.get((u, v), {})
        kind = edge_info.get("kind", "calls") if isinstance(edge_info, dict) else getattr(edge_info, "kind", "calls")
        ev = edge_info.get("evidence_tag", "EXTRACTED") if isinstance(edge_info, dict) else getattr(edge_info, "evidence_tag", "EXTRACTED")
        file_path = edge_info.get("file", "") if isinstance(edge_info, dict) else getattr(edge_info, "file", "")
        hops.append({
            "from": u,
            "to": v,
            "kind": kind,
            "evidence_tag": ev,
            "file": file_path,
        })

    if as_json:
        click.echo(json.dumps({"path": path_nodes, "length": length, "hops": hops, "reachable": True}, indent=2))
        return

    # Rich terminal formatting
    console.print(f"\n[bold green]Shortest path ({length} hop{'s' if length != 1 else ''}):[/bold green]")
    for i, hop in enumerate(hops, 1):
        u = hop["from"]
        v = hop["to"]
        kind = hop["kind"]
        ev = hop["evidence_tag"]
        file_info = f" [dim]({hop['file']})[/dim]" if hop['file'] else ""
        console.print(
            f"  {i}. [bold cyan]{u}[/bold cyan] --[yellow]{kind}[/yellow] [[magenta]{ev}[/magenta]]--> [bold cyan]{v}[/bold cyan]{file_info}"
        )
    console.print()
