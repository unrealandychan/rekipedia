"""Export wiki pages and diagrams as Markdown files."""
from __future__ import annotations

from pathlib import Path


class MarkdownExporter:
    def __init__(self, output_dir: Path) -> None:
        self._wiki_dir = output_dir / "wiki"
        self._diagram_dir = output_dir / "diagrams"

    def export(
        self,
        pages: dict[str, tuple[str, str]],
        diagrams: dict[str, tuple[str, str]],
    ) -> None:
        """Write pages to `wiki/` and diagrams to `diagrams/`.

        Args:
            pages: {slug: (title, markdown_content)}
            diagrams: {name: (diagram_type, mermaid_content)}
        """
        self._wiki_dir.mkdir(parents=True, exist_ok=True)
        self._diagram_dir.mkdir(parents=True, exist_ok=True)

        for slug, (_title, content) in pages.items():
            out = self._wiki_dir / f"{slug}.md"
            # Never overwrite a pinned page
            if out.exists() and _is_pinned(out):
                continue
            out.write_text(content, encoding="utf-8")

        for name, (_dtype, content) in diagrams.items():
            out = self._diagram_dir / f"{name}.md"
            out.write_text(f"```mermaid\n{content}\n```\n", encoding="utf-8")


def _is_pinned(path: Path) -> bool:
    import re
    text = path.read_text(encoding="utf-8")
    return bool(re.search(r"^pin:\s*true", text, re.MULTILINE))
