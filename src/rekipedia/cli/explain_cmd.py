"""CLI command for inspecting and explaining a symbol from the knowledge graph."""
from __future__ import annotations

import json
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


@click.command("explain")
@click.argument("symbol_name")
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
def explain_cmd(symbol_name: str, repo: str, as_json: bool) -> None:  # noqa: C901
    """Inspect a symbol: location, callers, callees, confidence tags, and patterns.

    \b
    Examples:
        reki explain SqliteStore
        reki explain run_digest
        reki explain APIRouter --json
    """
    repo_root = Path(repo).resolve()
    db_path = repo_root / ".rekipedia" / "store.db"
    if not db_path.exists():
        if as_json:
            click.echo(json.dumps({"error": f"No store.db found at {db_path}. Run 'reki scan' first."}))
        else:
            console.print(f"[red]No knowledge store found at {db_path}.[/red]\nRun [bold]reki scan[/bold] first.")
        return

    from rekipedia.storage.sqlite_store import SqliteStore

    with SqliteStore(db_path) as store:
        run_id = store.get_latest_run_id(str(repo_root)) or store.latest_run_id()
        if not run_id:
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

        symbols = store.get_all_symbols(run_id)
        rels = store.get_all_relationships(run_id)
        rationale_notes = store.get_rationale_notes(run_id)
        hyperedges = store.get_hyperedges(run_id)

    # Find matching symbol(s)
    matching_syms = [
        s for s in symbols
        if (s.name if hasattr(s, "name") else s.get("name")) == symbol_name
    ]
    sym_info = matching_syms[0] if matching_syms else None

    # Compute incoming (callers) and outgoing (callees)
    callers = []
    callees = []
    for r in rels:
        frm = r.get("from_", "") or r.get("from", "") if isinstance(r, dict) else (r.from_ or "")
        to = r.get("to", "") if isinstance(r, dict) else r.to
        kind = r.get("kind", "") if isinstance(r, dict) else r.kind
        conf = r.get("confidence", 1.0) if isinstance(r, dict) else getattr(r, "confidence", 1.0)
        ev = r.get("evidence_tag", "EXTRACTED") if isinstance(r, dict) else getattr(r, "evidence_tag", "EXTRACTED")
        file_path = r.get("file", "") if isinstance(r, dict) else getattr(r, "file", "")

        if to == symbol_name:
            callers.append({"symbol": frm, "kind": kind, "confidence": conf, "evidence_tag": ev, "file": file_path})
        if frm == symbol_name:
            callees.append({"symbol": to, "kind": kind, "confidence": conf, "evidence_tag": ev, "file": file_path})

    # Relevant rationale notes
    sym_file = (sym_info.file if hasattr(sym_info, "file") else sym_info.get("file")) if sym_info else ""
    sym_start = (sym_info.line_start if hasattr(sym_info, "line_start") else sym_info.get("line_start", 0)) if sym_info else 0
    sym_end = (sym_info.line_end if hasattr(sym_info, "line_end") else sym_info.get("line_end", 999999)) if sym_info else 999999

    relevant_notes = [
        n for n in rationale_notes
        if n.get("file") == sym_file and sym_start <= n.get("line", 0) <= sym_end
    ]

    # Relevant hyperedges (design patterns)
    participating_hyperedges = [
        h for h in hyperedges
        if symbol_name in h.get("nodes", [])
    ]

    result = {
        "symbol": symbol_name,
        "found": sym_info is not None or bool(callers or callees),
        "kind": (sym_info.kind if hasattr(sym_info, "kind") else sym_info.get("kind", "unknown")) if sym_info else "unknown",
        "file": sym_file,
        "line_start": sym_start,
        "line_end": sym_end,
        "degree": len(callers) + len(callees),
        "in_degree": len(callers),
        "out_degree": len(callees),
        "callers": callers,
        "callees": callees,
        "rationale_notes": relevant_notes,
        "hyperedges": participating_hyperedges,
    }

    if as_json:
        click.echo(json.dumps(result, indent=2))
        return

    # Rich formatting
    if not result["found"]:
        console.print(f"[yellow]Symbol '{symbol_name}' was not found in the codebase index.[/yellow]")
        return

    panel_title = f"[bold cyan]{symbol_name}[/bold cyan] ({result['kind']})"
    loc_info = f"[dim]Source: {result['file']}:{result['line_start']}-{result['line_end']}[/dim]" if result['file'] else ""
    deg_info = f"[bold]Degree:[/bold] {result['degree']} (in: {result['in_degree']}, out: {result['out_degree']})"

    body = f"{loc_info}\n{deg_info}\n"

    if participating_hyperedges:
        body += "\n[bold magenta]Design Patterns / Architectural Motifs:[/bold magenta]\n"
        for h in participating_hyperedges:
            body += f"  • [cyan]{h.get('concept')}[/cyan] ({h.get('pattern_type')}): {h.get('description', '')}\n"

    console.print(Panel(body.strip(), title=panel_title, border_style="cyan"))

    # Connections table
    if callers:
        t_in = Table(title=f"Incoming References / Callers ({len(callers)})", show_lines=False)
        t_in.add_column("Caller", style="bold cyan")
        t_in.add_column("Kind", style="yellow")
        t_in.add_column("Evidence", style="magenta")
        t_in.add_column("File", style="dim")
        for c in callers[:20]:
            t_in.add_row(c["symbol"], c["kind"], f"[{c['evidence_tag']}]", c.get("file", ""))
        console.print(t_in)

    if callees:
        t_out = Table(title=f"Outgoing References / Callees ({len(callees)})", show_lines=False)
        t_out.add_column("Callee", style="bold cyan")
        t_out.add_column("Kind", style="yellow")
        t_out.add_column("Evidence", style="magenta")
        t_out.add_column("File", style="dim")
        for c in callees[:20]:
            t_out.add_row(c["symbol"], c["kind"], f"[{c['evidence_tag']}]", c.get("file", ""))
        console.print(t_out)

    if relevant_notes:
        console.print("\n[bold yellow]Rationale Notes:[/bold yellow]")
        for n in relevant_notes:
            console.print(f"  • [[bold]{n.get('tag')}[/bold]] line {n.get('line')}: {n.get('content')}")
        console.print()
