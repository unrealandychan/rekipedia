"""rekipedia export — bundle wiki pages into a portable file.

Usage:
    rekipedia export [REPO_PATH] [--format md|zip|json] [--output PATH]

Formats:
    md   (default) — single combined Markdown file (nav_order preserved)
    zip  — zip of wiki/*.md + diagrams/*.md + exports/manifest.json
    json — manifest.json (already exists; this re-exports with latest metadata)
"""
from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

import click
from rich.console import Console

console = Console()

_FORMAT_CHOICES = click.Choice(["md", "zip", "json", "html", "graph", "graph-html", "graphml", "cypher", "obsidian", "bundle", "okf"], case_sensitive=False)


@click.command("export")
@click.argument("repo_path", default=".", type=click.Path(exists=True, file_okay=False))
@click.option(
    "--output-dir",
    default=None,
    help="Path to .rekipedia/ directory (default: REPO_PATH/.rekipedia/)",
)
@click.option(
    "--format", "fmt",
    default="md",
    type=_FORMAT_CHOICES,
    show_default=True,
    help="Output format: md (single file), zip (bundle), json (manifest only).",
)
@click.option(
    "--output", "-o",
    default=None,
    help="Destination file path. Defaults to .rekipedia/export.<ext>.",
)
@click.option(
    "--title",
    default=None,
    help="Title for the combined Markdown document (default: repo directory name).",
)
def export_cmd(
    repo_path: str,
    output_dir: str | None,
    fmt: str,
    output: str | None,
    title: str | None,
) -> None:
    """Export the wiki to a portable file.

    \b
    Examples:
        rekipedia export .
        rekipedia export . --format zip -o wiki.zip
        rekipedia export . --format md -o WIKI.md
    """
    repo = Path(repo_path).resolve()
    out_dir = Path(output_dir).resolve() if output_dir else repo / ".rekipedia"

    wiki_dir = out_dir / "wiki"
    diagrams_dir = out_dir / "diagrams"
    manifest_path = out_dir / "exports" / "manifest.json"

    if not wiki_dir.exists():
        console.print(
            f"[red]No wiki/ directory found at {wiki_dir}.[/red]\n"
            "Run [bold]rekipedia scan[/bold] first."
        )
        sys.exit(1)

    # Load manifest for nav_order + page metadata
    nav_order: list[str] = []
    pages_meta: dict[str, dict] = {}
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            nav_order = manifest.get("nav_order", [])
            for p in manifest.get("pages", []):
                pages_meta[p["slug"]] = p
        except Exception:
            pass

    # Collect all wiki pages in nav order
    all_pages = sorted(wiki_dir.glob("*.md"))
    if nav_order:
        # Sort by nav_order, append any not in nav_order alphabetically
        ordered = []
        slug_map = {p.stem: p for p in all_pages}
        for slug in nav_order:
            if slug in slug_map:
                ordered.append(slug_map[slug])
        remaining = [p for p in all_pages if p.stem not in set(nav_order)]
        all_pages = ordered + remaining

    doc_title = title or repo.name
    fmt = fmt.lower()

    if fmt == "okf":
        from rekipedia.exporters.okf_export import OkfExporter

        okf_dir = Path(output) if output else out_dir / "okf-bundle"
        okf_dir.mkdir(parents=True, exist_ok=True)
        exporter = OkfExporter(wiki_dir, diagrams_dir, repo)
        summary = exporter.export(okf_dir, pages_meta=pages_meta)
        console.print(
            f"[green]✅ OKF bundle exported:[/] {okf_dir}\n"
            f"   pages   : {len(summary['pages'])}\n"
            f"   diagrams: {len(summary['diagrams'])}\n"
            f"   format  : Open Knowledge Format v0.1"
        )
        return

    if fmt == "bundle":
        from rekipedia.exporters.bundle_export import BundleExporter

        bundle_dir = Path(output) if output else out_dir / "bundle"
        bundle_dir.mkdir(parents=True, exist_ok=True)
        exporter = BundleExporter(wiki_dir, diagrams_dir, repo)
        manifest = exporter.export(bundle_dir)
        console.print(
            f"[green]Bundle exported:[/] {bundle_dir}  "
            f"(bundle_id={manifest['bundle_id']}, {len(manifest['pages'])} pages)"
        )
        return

    if fmt == "obsidian":
        obs_dir = Path(output) if output else out_dir / "obsidian-vault"
        from rekipedia.analysis.graph_export import export_obsidian
        from rekipedia.storage.sqlite_store import SqliteStore
        db = out_dir / "store.db"
        if not db.exists():
            alt = out_dir / "rekipedia.db"
            if alt.exists():
                db = alt
            else:
                console.print("[red]No rekipedia DB. Run rekipedia scan first.[/red]")
                sys.exit(1)
        with SqliteStore(db) as store:
            run_id = store.latest_run_id()
            symbols = store.get_all_symbols(run_id)
            rels = store.get_all_relationships(run_id)
        written = export_obsidian(symbols, rels, obs_dir, wiki_dir=wiki_dir, diagrams_dir=diagrams_dir)
        console.print(f"[green]✅ Obsidian vault: {len(written)} notes written to {obs_dir}[/green]")
        return

    if fmt in ("graph", "graph-html"):
        from rekipedia.analysis.graph_export import export_interactive_html
        from rekipedia.storage.sqlite_store import SqliteStore
        db = out_dir / "store.db"
        if not db.exists():
            alt = out_dir / "rekipedia.db"
            if alt.exists():
                db = alt
            else:
                console.print("[red]No rekipedia DB. Run rekipedia scan first.[/red]")
                sys.exit(1)
        with SqliteStore(db) as store:
            run_id = store.get_latest_run_id(str(repo)) or store.latest_run_id()
            if not run_id:
                try:
                    row = store._c.execute("SELECT id FROM scan_runs ORDER BY rowid DESC LIMIT 1").fetchone()
                    if row:
                        run_id = row[0]
                except Exception:
                    pass
            symbols = store.get_all_symbols(run_id) if run_id else []
            rels = store.get_all_relationships(run_id) if run_id else []
            god_nodes = store.get_god_nodes(run_id, top_n=10) if run_id else []
            hyperedges = store.get_hyperedges(run_id) if run_id else []

        nodes = [
            {
                "id": s.name if hasattr(s, "name") else s.get("name", ""),
                "name": s.name if hasattr(s, "name") else s.get("name", ""),
                "kind": s.kind if hasattr(s, "kind") else s.get("kind", "module"),
                "file": s.file if hasattr(s, "file") else s.get("file", ""),
            }
            for s in symbols if (s.name if hasattr(s, "name") else s.get("name"))
        ]
        # Also ensure unique nodes for relation endpoints
        existing_node_ids = {n["id"] for n in nodes}
        edges = []
        for r in rels:
            frm = r.get("from_", "") or r.get("from", "") if isinstance(r, dict) else (r.from_ or "")
            to = r.get("to", "") if isinstance(r, dict) else r.to
            kind = r.get("kind", "") if isinstance(r, dict) else r.kind
            if frm and to:
                if frm not in existing_node_ids:
                    nodes.append({"id": frm, "name": frm, "kind": "module", "file": ""})
                    existing_node_ids.add(frm)
                if to not in existing_node_ids:
                    nodes.append({"id": to, "name": to, "kind": "module", "file": ""})
                    existing_node_ids.add(to)
                edges.append({"source": frm, "target": to, "kind": kind})

        god_nodes_data = [{"name": name, "degree": degree} for name, degree in god_nodes]

        dest = Path(output) if output else out_dir / "graph.html"
        dest.parent.mkdir(parents=True, exist_ok=True)
        html_content = export_interactive_html(
            nodes=nodes,
            edges=edges,
            god_nodes=god_nodes_data,
            hyperedges=hyperedges,
            title=f"{doc_title} · Knowledge Graph",
        )
        dest.write_text(html_content, encoding="utf-8")
        size_kb = dest.stat().st_size / 1024
        console.print(f"[green]✅ Exported interactive GRAPH HTML[/green] → [bold]{dest}[/bold] ({size_kb:.1f} KB)")
        console.print(f"   nodes  : {len(nodes)}")
        console.print(f"   edges  : {len(edges)}")
        return

    if fmt in ("graphml", "cypher"):
        from rekipedia.analysis.graph_export import export_cypher, export_graphml
        from rekipedia.storage.sqlite_store import SqliteStore
        db = out_dir / "store.db"
        if not db.exists():
            alt = out_dir / "rekipedia.db"
            if alt.exists():
                db = alt
            else:
                console.print("[red]No rekipedia DB. Run rekipedia scan first.[/red]")
                sys.exit(1)
        with SqliteStore(db) as store:
            run_id = store.latest_run_id()
            symbols = store.get_all_symbols(run_id)
            rels = store.get_all_relationships(run_id)
        ext_map = {"graphml": "graphml", "cypher": "cypher"}
        dest = Path(output) if output else out_dir / f"graph.{ext_map[fmt]}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        content = export_graphml(symbols, rels) if fmt == "graphml" else export_cypher(symbols, rels)
        dest.write_text(content, encoding="utf-8")
        size_kb = dest.stat().st_size / 1024
        console.print(f"[green]✅ Exported {fmt.upper()}[/green] → [bold]{dest}[/bold] ({size_kb:.1f} KB)")
        return

    if fmt == "html":
        html_dest = Path(output).resolve() if output else None
        actual_dest = _export_html(all_pages, pages_meta, out_dir, html_dest, doc_title)
        size_kb = actual_dest.stat().st_size / 1024
        console.print(f"[green]✅ Exported HTML[/green] → [bold]{actual_dest}[/bold] ({size_kb:.1f} KB)")
        console.print(f"   pages  : {len(all_pages)}")
        return

    ext = {"md": "md", "zip": "zip", "json": "json"}[fmt]

    dest = Path(output) if output else out_dir / f"export.{ext}"
    dest.parent.mkdir(parents=True, exist_ok=True)

    if fmt == "md":
        _export_md(all_pages, dest, doc_title, pages_meta)
    elif fmt == "zip":
        _export_zip(all_pages, diagrams_dir, manifest_path, dest, doc_title)
    elif fmt == "json":
        if not manifest_path.exists():
            console.print("[red]No manifest.json found. Run rekipedia scan first.[/red]")
            sys.exit(1)
        import shutil
        shutil.copy2(manifest_path, dest)

    size_kb = dest.stat().st_size / 1024
    console.print(f"[green]✅ Exported {fmt.upper()}[/green] → [bold]{dest}[/bold] ({size_kb:.1f} KB)")
    if fmt == "md":
        console.print(f"   pages  : {len(all_pages)}")
    elif fmt == "zip":
        with zipfile.ZipFile(dest) as z:
            console.print(f"   files  : {len(z.namelist())}")


# ---------------------------------------------------------------------------
# Format implementations
# ---------------------------------------------------------------------------

def _export_md(
    pages: list[Path],
    dest: Path,
    title: str,
    pages_meta: dict[str, dict],
) -> None:
    """Write a single combined Markdown file with a TOC."""
    lines: list[str] = [f"# {title}\n", "\n## Table of Contents\n"]

    # TOC
    for p in pages:
        slug = p.stem
        meta = pages_meta.get(slug, {})
        display_title = meta.get("title", slug.replace("-", " ").title())
        importance = meta.get("importance", "")
        imp_badge = f" *(importance: {importance})*" if importance else ""
        anchor = slug.replace(" ", "-").lower()
        lines.append(f"- [{display_title}](#{anchor}){imp_badge}\n")

    lines.append("\n---\n\n")

    # Pages
    for p in pages:
        slug = p.stem
        meta = pages_meta.get(slug, {})
        display_title = meta.get("title", slug.replace("-", " ").title())
        content = p.read_text(encoding="utf-8").strip()

        # Add section header with anchor
        lines.append(f'<a id="{slug}"></a>\n\n')
        lines.append(f"## {display_title}\n\n")

        # Importance + tags badge line
        badges: list[str] = []
        if "importance" in meta:
            badges.append(f"importance: **{meta['importance']}**")
        if "section" in meta:
            badges.append(f"section: `{meta['section']}`")
        if meta.get("tags"):
            badges.append("tags: " + ", ".join(f"`{t}`" for t in meta["tags"]))
        if badges:
            lines.append("> " + " · ".join(badges) + "\n\n")

        lines.append(content + "\n\n---\n\n")

    dest.write_text("".join(lines), encoding="utf-8")


def _export_zip(
    pages: list[Path],
    diagrams_dir: Path,
    manifest_path: Path,
    dest: Path,
    title: str,
) -> None:
    """Bundle wiki pages + diagrams + manifest into a zip file."""
    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for p in pages:
            zf.write(p, arcname=f"wiki/{p.name}")
        if diagrams_dir.exists():
            for d in sorted(diagrams_dir.glob("*.md")):
                zf.write(d, arcname=f"diagrams/{d.name}")
        if manifest_path.exists():
            zf.write(manifest_path, arcname="manifest.json")
        # Include a README pointing to the index page
        readme = f"# {title}\n\nGenerated by rekipedia.\n\nOpen `wiki/index.md` to start reading.\n"
        zf.writestr("README.md", readme)


def _export_html(
    pages: list,
    pages_meta: dict,
    out_dir: Path,
    dest: Path | None,
    title: str,
) -> Path:
    """Write an interactive self-contained HTML wiki file."""
    from rekipedia.exporters.html_export import HtmlExporter

    exporter = HtmlExporter(out_dir)

    # Build slug → (page_title, markdown) mapping
    nav_order: list[str] = []
    pages_dict: dict[str, tuple[str, str]] = {}
    sections_seen: list[str] = []

    for p in pages:
        slug = p.stem
        meta = pages_meta.get(slug, {})
        page_title = meta.get("title", slug.replace("-", " ").replace("_", " ").title())
        content = p.read_text(encoding="utf-8").strip()
        pages_dict[slug] = (page_title, content)
        nav_order.append(slug)
        sec = meta.get("section", "")
        if sec and sec not in sections_seen:
            sections_seen.append(sec)

    return exporter.export(
        pages_dict,
        nav_order=nav_order,
        sections=sections_seen,
        pages_meta=pages_meta,
        title=title,
        dest=dest,
    )
