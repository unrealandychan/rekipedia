"""reki hotspots — architectural hotspot detection (hub & bridge nodes)."""
from __future__ import annotations

import json
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

console = Console()


def _truncate(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def _render_table(hubs: list[dict], bridges: list[dict], top: int) -> None:
    console.print(f"\n🏗  [bold]Architectural Hotspots[/bold] — top {top}\n")

    # Hub nodes
    console.print("[bold yellow]HUB NODES[/bold yellow] (most connected)")
    hub_tbl = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
    hub_tbl.add_column("Rank", justify="right", style="dim", width=5)
    hub_tbl.add_column("Symbol", min_width=30)
    hub_tbl.add_column("File", min_width=30)
    hub_tbl.add_column("In", justify="right", width=5)
    hub_tbl.add_column("Out", justify="right", width=5)
    hub_tbl.add_column("Total", justify="right", width=6)

    for rank, node in enumerate(hubs, 1):
        hub_tbl.add_row(
            str(rank),
            _truncate(node["name"], 35),
            _truncate(node.get("file", ""), 35),
            str(node["in_degree"]),
            str(node["out_degree"]),
            str(node["total_degree"]),
        )
    console.print(hub_tbl)

    console.print()
    console.print("[bold yellow]BRIDGE NODES[/bold yellow] (cross-boundary connectors)")
    bridge_tbl = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
    bridge_tbl.add_column("Rank", justify="right", style="dim", width=5)
    bridge_tbl.add_column("Symbol", min_width=30)
    bridge_tbl.add_column("File", min_width=30)
    bridge_tbl.add_column("In×Out", justify="right", width=8)

    for rank, node in enumerate(bridges, 1):
        bridge_tbl.add_row(
            str(rank),
            _truncate(node["name"], 35),
            _truncate(node.get("file", ""), 35),
            str(node["bridge_score"]),
        )
    console.print(bridge_tbl)
    console.print()


def _render_md(hubs: list[dict], bridges: list[dict], top: int) -> str:
    lines = [f"# Architectural Hotspots — top {top}", ""]
    lines += [
        "## Hub Nodes (most connected)",
        "",
        "| Rank | Symbol | File | In | Out | Total |",
        "|-----:|--------|------|---:|----:|------:|",
    ]
    for rank, node in enumerate(hubs, 1):
        lines.append(
            f"| {rank} | `{node['name']}` | {node.get('file', '')} "
            f"| {node['in_degree']} | {node['out_degree']} | {node['total_degree']} |"
        )

    lines += [
        "",
        "## Bridge Nodes (cross-boundary connectors)",
        "",
        "| Rank | Symbol | File | In×Out |",
        "|-----:|--------|------|-------:|",
    ]
    for rank, node in enumerate(bridges, 1):
        lines.append(
            f"| {rank} | `{node['name']}` | {node.get('file', '')} | {node['bridge_score']} |"
        )

    lines.append("")
    return "\n".join(lines)


@click.command("hotspots")
@click.argument("repo", default=".", type=click.Path())
@click.option("--top", default=10, show_default=True, help="Number of nodes to show")
@click.option(
    "--format",
    "fmt",
    default="table",
    show_default=True,
    type=click.Choice(["table", "json", "md"]),
    help="Output format",
)
def hotspots_cmd(repo: str, top: int, fmt: str) -> None:
    """Identify architectural hotspots: hub nodes and bridge nodes."""
    from rekipedia.analysis.graph_analysis import get_bridge_nodes, get_hub_nodes
    from rekipedia.storage.sqlite_store import SqliteStore

    repo_path = Path(repo).resolve()
    db_path = repo_path / ".rekipedia" / "store.db"
    if not db_path.exists():
        alt = repo_path / ".rekipedia" / "rekipedia.db"
        if alt.exists():
            db_path = alt
    if not db_path.exists():
        console.print(f"[red]No rekipedia DB at {db_path}. Run `reki scan` first.[/red]")
        raise click.Abort()

    with SqliteStore(db_path) as store:
        run_id = store.get_latest_run_id(str(repo_path))
        if not run_id:
            console.print("[red]No scan runs found.[/red]")
            raise click.Abort()
        hubs = get_hub_nodes(store, run_id, top_n=top)
        bridges = get_bridge_nodes(store, run_id, top_n=top)

    if fmt == "json":
        click.echo(json.dumps({"hub_nodes": hubs, "bridge_nodes": bridges}, indent=2))
    elif fmt == "md":
        click.echo(_render_md(hubs, bridges, top))
    else:
        _render_table(hubs, bridges, top)
