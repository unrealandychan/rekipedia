"""Export knowledge as JSON files + manifest.json."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from rekipedia.models.contracts import AnalysisResult, FileManifest


class JsonExporter:
    def __init__(self, output_dir: Path) -> None:
        self._exports_dir = output_dir / "exports"

    def export(
        self,
        run_id: str,
        files: list[FileManifest],
        combined: AnalysisResult,
        pages: dict[str, tuple[str, str]],
        diagrams: dict[str, tuple[str, str]],
    ) -> None:
        self._exports_dir.mkdir(parents=True, exist_ok=True)

        # symbols.json
        symbols_path = self._exports_dir / "symbols.json"
        symbols_path.write_text(
            json.dumps(
                [s.model_dump() for s in combined.symbols],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        # relationships.json
        rels_path = self._exports_dir / "relationships.json"
        rels_path.write_text(
            json.dumps(
                [r.model_dump(by_alias=True) for r in combined.relationships],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        # manifest.json
        nav_order: list[str] = []
        pages_meta: list[dict] = []
        try:
            import json as _json  # noqa: PLC0415
            nav_order = _json.loads(combined.evidence.get("nav_order", "[]"))
            pages_meta = _json.loads(combined.evidence.get("wiki_pages_meta", "[]"))
        except Exception:
            pass

        # Build ordered pages list: nav_order first, then any unordered remainder
        ordered_slugs = nav_order or list(pages.keys())
        pages_meta_by_slug = {p["slug"]: p for p in pages_meta}
        pages_list = []
        for slug in ordered_slugs:
            if slug not in pages:
                continue
            title = pages[slug][0]
            meta = pages_meta_by_slug.get(slug, {})
            entry: dict = {"slug": slug, "title": title}
            if "importance" in meta:
                entry["importance"] = meta["importance"]
            if "priority" in meta:
                entry["priority"] = meta["priority"]
            if "section" in meta:
                entry["section"] = meta["section"]
            if "tags" in meta:
                entry["tags"] = meta["tags"]
            pages_list.append(entry)
        # Append any slugs not in nav_order
        for slug, (title, _) in pages.items():
            if slug not in {e["slug"] for e in pages_list}:
                pages_list.append({"slug": slug, "title": title})

        manifest = {
            "run_id": run_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "file_count": len(files),
            "symbol_count": len(combined.symbols),
            "relationship_count": len(combined.relationships),
            "nav_order": ordered_slugs,
            "pages": pages_list,
            "diagrams": list(diagrams.keys()),
            "risks": combined.risks,
            "build_commands": combined.build_commands,
            "test_commands": combined.test_commands,
        }
        manifest_path = self._exports_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
