"""Incremental update pipeline for `rekipedia update`.

Flow:
    1. Find the last successful scan run for this repo.
    2. If none → fall back to a full scan via run_digest().
    3. Snapshot the repo and diff against stored file hashes.
    4. If nothing changed → report up-to-date and return early.
    5. Create a new run; re-extract only changed shards.
    6. Carry forward symbols / relationships for unchanged files.
    7. Re-synthesise all wiki pages (full context always needed).
    8. Export markdown + JSON.
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Callable

from rekipedia.models.contracts import AnalysisResult, FileManifest, LLMConfig
from rekipedia.orchestrator.run_digest import run_digest, _combine_results
from rekipedia.orchestrator.sharding import ShardPlanner
from rekipedia.orchestrator.snapshotter import Snapshotter
from rekipedia.sandbox.runner import BaseRunner, get_runner
from rekipedia.storage.sqlite_store import SqliteStore


def run_update(
    repo_root: Path,
    output_dir: Path,
    llm_config: LLMConfig | None = None,
    *,
    force_local: bool = False,
    progress: Callable[[str], None] | None = None,
    languages: list[str] | None = None,
) -> None:
    """Incremental update pipeline.

    Re-extracts only files whose SHA-256 has changed since the last
    successful scan, then re-synthesises wiki pages with the full
    combined symbol index.

    Args:
        repo_root: Absolute path to the repository to scan.
        output_dir: `.rekipedia/` directory; DB + wiki output goes here.
        llm_config: LLM settings; defaults to LLMConfig().
        force_local: Skip Docker even if available.
        progress: Optional callback that receives status strings for display.
    """
    llm_config = llm_config or LLMConfig()
    _log = progress or (lambda _: None)

    db_path = output_dir / "store.db"
    store = SqliteStore(db_path)
    store.open()

    try:
        # ── 1. Find last successful run ───────────────────────────────
        last_run_id = store.get_latest_run_id(str(repo_root))

        if last_run_id is None:
            _log("No previous scan found — running full scan…")
            store.close()
            run_digest(
                repo_root=repo_root,
                output_dir=output_dir,
                llm_config=llm_config,
                force_local=force_local,
                progress=progress,
                languages=languages,
            )
            return

        _log(f"Last run: {last_run_id[:8]}")

        # ── 2. Snapshot current state ─────────────────────────────────
        _log("Snapshotting repository…")
        snapshotter = Snapshotter(repo_root, languages=languages)
        current_files = snapshotter.snapshot()
        current_map: dict[str, FileManifest] = {f.path: f for f in current_files}

        # ── 3. Diff against stored hashes ─────────────────────────────
        prev_files = store.get_files_for_run(last_run_id)
        prev_map: dict[str, str] = {f["path"]: f["sha256"] for f in prev_files}

        changed: list[FileManifest] = [
            f for f in current_files
            if f.path not in prev_map or prev_map[f.path] != f.sha256
        ]
        deleted_paths: set[str] = set(prev_map.keys()) - set(current_map.keys())
        changed_paths: set[str] = {f.path for f in changed} | deleted_paths

        if not changed and not deleted_paths:
            _log("No changes detected — wiki is already up to date.")
            store.close()
            return

        _log(
            f"  {len(changed)} changed / new file(s), "
            f"{len(deleted_paths)} deleted"
        )

        # ── 4. Create a new run ───────────────────────────────────────
        run_id = str(uuid.uuid4())
        store.upsert_run(run_id, str(repo_root))
        _log(f"Run {run_id[:8]} started")

        # Persist full current snapshot
        store.upsert_snapshot(run_id, [f.model_dump() for f in current_files])
        for f in current_files:
            store.upsert_file(run_id, f.path, f.sha256, f.size_bytes, f.language)

        # ── 5. Carry forward unchanged symbols / relationships ────────
        carried_syms = store.copy_unchanged_symbols(last_run_id, run_id, changed_paths)
        carried_rels = store.copy_unchanged_relationships(last_run_id, run_id, changed_paths)
        _log(f"  Carried forward {carried_syms} symbols, {carried_rels} relationships")

        # ── 6. Re-extract changed shards ──────────────────────────────
        merged_results: list[AnalysisResult] = []

        if changed:
            _log("Planning shards for changed files…")
            planner = ShardPlanner()
            shards = planner.plan(changed, llm_config)
            _log(f"  {len(shards)} shard(s)")

            runner: BaseRunner = get_runner(force_local=force_local)
            _log(f"Using {type(runner).__name__}")

            for i, shard in enumerate(shards, 1):
                _log(f"  Extracting shard {i}/{len(shards)}: {shard.shard_id}")
                result = runner.run(shard, repo_root)
                merged_results.append(result)

                symbols_dicts = [s.model_dump() for s in result.symbols]
                rels_dicts = [r.model_dump(by_alias=True) for r in result.relationships]
                store.upsert_symbols(run_id, symbols_dicts)
                store.upsert_relationships(run_id, rels_dicts)

        # ── 7. Synthesise wiki pages (always full re-synthesis) ───────
        _log("Synthesising wiki pages…")
        from rekipedia.synthesis.page_builder import PageBuilder  # noqa: PLC0415
        from rekipedia.synthesis.diagram_builder import DiagramBuilder  # noqa: PLC0415

        all_rels_raw = store.get_all_relationships(run_id)

        # Build a combined AnalysisResult for the page builder
        combined = _combine_results(merged_results) if merged_results else AnalysisResult(
            shard_id="update",
            files_seen=list(current_map.keys()),
            entry_points=[],
        )
        # Enrich with any symbols carried forward (for page context)
        all_symbols_raw = store.get_all_symbols(run_id)
        _log(f"  {len(all_symbols_raw)} total symbols in index")

        builder = PageBuilder(llm_config)
        pages = builder.build(combined)

        diagram_builder = DiagramBuilder()
        diagrams = diagram_builder.build(all_rels_raw)

        for slug, (title, content) in pages.items():
            store.upsert_page(run_id, slug, title, content)
        for name, (dtype, content) in diagrams.items():
            store.upsert_diagram(run_id, name, dtype, content)

        # ── 8. Export ─────────────────────────────────────────────────
        _log("Exporting…")
        from rekipedia.exporters.markdown_export import MarkdownExporter  # noqa: PLC0415
        from rekipedia.exporters.json_export import JsonExporter  # noqa: PLC0415

        MarkdownExporter(output_dir).export(pages, diagrams)
        JsonExporter(output_dir).export(run_id, current_files, combined, pages, diagrams)

        store.update_run_status(run_id, "success")
        _log("Done.")

    except Exception:
        # Best-effort status update — run_id may not exist yet if we raised early
        try:
            store.update_run_status(run_id, "failed")  # type: ignore[possibly-undefined]
        except Exception:
            pass
        store.close()
        raise

    store.close()
