#!/usr/bin/env python3
"""Docker sandbox entrypoint — pure static analysis, NO network / NO LLM calls.

Usage (inside container):
    python3 analyze_shard.py <shard_json_path> <output_json_path>

Reads a Shard JSON from *shard_json_path*, runs all extractors against every
file listed in the shard, merges results, and writes a single AnalysisResult
JSON to *output_json_path*.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) != 3:
        print("Usage: analyze_shard.py <shard_json_path> <output_json_path>", file=sys.stderr)
        sys.exit(1)

    shard_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])

    shard_data = json.loads(shard_path.read_text())
    root = Path(shard_data["root"])
    shard_id = shard_data["shard_id"]
    files = shard_data.get("files", [])

    # Import extractors (available inside the container via PYTHONPATH)
    from rekipedia.extractors import ALL_EXTRACTORS  # noqa: PLC0415
    from rekipedia.models.contracts import AnalysisResult  # noqa: PLC0415

    merged = AnalysisResult(shard_id=shard_id, files_seen=[], entry_points=[])

    for file_info in files:
        rel_path = file_info["path"]
        abs_path = root / rel_path

        if not abs_path.exists():
            merged.risks.append(f"missing: {rel_path}")
            continue

        handled = False
        for extractor in ALL_EXTRACTORS:
            if extractor.can_handle(abs_path):
                try:
                    result = extractor.extract(abs_path, root)
                    _merge(merged, result)
                    handled = True
                    break
                except Exception as exc:  # noqa: BLE001
                    merged.risks.append(f"extractor error on {rel_path}: {exc}")
                    break

        if not handled:
            merged.files_seen.append(rel_path)

    output_path.write_text(merged.model_dump_json(by_alias=True))


def _merge(target , src ) -> None:
    target.files_seen.extend(src.files_seen)
    target.entry_points.extend(src.entry_points)
    target.symbols.extend(src.symbols)
    target.relationships.extend(src.relationships)
    target.build_commands.extend(src.build_commands)
    target.test_commands.extend(src.test_commands)
    target.risks.extend(src.risks)
    target.evidence.update(src.evidence)


if __name__ == "__main__":
    main()
