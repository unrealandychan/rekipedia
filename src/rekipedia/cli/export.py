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

_FORMAT_CHOICES = click.Choice(["md", "zip", "json"], case_sensitive=False)


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
        import shutil  # noqa: PLC0415
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
        if "tags" in meta and meta["tags"]:
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
