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

import contextlib
import logging
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from rekipedia.models.contracts import AnalysisResult, FileManifest, LLMConfig
from rekipedia.orchestrator.run_digest import _combine_results, run_digest
from rekipedia.orchestrator.sharding import ShardPlanner
from rekipedia.orchestrator.snapshotter import Snapshotter
from rekipedia.sandbox.runner import BaseRunner, get_runner
from rekipedia.storage.sqlite_store import SqliteStore

logger = logging.getLogger("rekipedia.run_update")

_MAX_SHARD_WORKERS = 4


def _compute_impact_affected_files(
    changed_paths: set[str],
    store: "SqliteStore",
    run_id: str,
) -> set[str]:
    """Use BFS impact analysis to find all files transitively affected by changed_paths.

    For each changed file, runs compute_impact() from analysis/impact.py and unions
    the returned affected_files sets together with the seed (changed) files.

    Returns an empty set when no relationships exist (caller should fall back).
    """
    from rekipedia.analysis.impact import compute_impact

    all_symbols_raw = store.get_all_symbols(run_id)
    all_rels_raw = store.get_all_relationships(run_id)

    if not all_rels_raw:
        return set()

    affected: set[str] = set(changed_paths)
    for file_path in changed_paths:
        result = compute_impact(
            target_file=file_path,
            relationships=all_rels_raw,
            symbols=all_symbols_raw,
            depth=5,
        )
        affected.update(result.get("affected_files", []))

    return affected


def run_update(
    repo_root: Path,
    output_dir: Path,
    llm_config: LLMConfig | None = None,
    *,
    force_local: bool = False,
    progress: Callable[[str], None] | None = None,
    languages: list[str] | None = None,
    impact_only: bool = False,
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
        impact_only: When True, use BFS impact analysis to only regenerate wiki
            pages for transitively affected modules. Reduces LLM calls by
            80-90% on large repos.
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
        store.upsert_files_batch(run_id, current_files)

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

            def _run_shard(shard):
                return shard, runner.run(shard, repo_root)

            with ThreadPoolExecutor(max_workers=_MAX_SHARD_WORKERS) as executor:
                future_to_shard = {executor.submit(_run_shard, s): s for s in shards}
                failed = 0
                for i, future in enumerate(as_completed(future_to_shard), 1):
                    shard = future_to_shard[future]
                    try:
                        _, result = future.result()
                        _log(f"  Extracted shard {i}/{len(shards)}: {shard.shard_id}")
                        merged_results.append(result)
                        symbols_dicts = [s.model_dump() for s in result.symbols]
                        rels_dicts = [r.model_dump(by_alias=True) for r in result.relationships]
                        store.upsert_symbols(run_id, symbols_dicts)
                        store.upsert_relationships(run_id, rels_dicts)
                    except Exception as exc:
                        failed += 1
                        logger.error("Shard %s failed: %s", shard.shard_id, exc)

            if failed == len(shards):
                raise RuntimeError(f"All {len(shards)} shard(s) failed during update extraction")

        # ── 7. Synthesise wiki pages ──────────────────────────────────
        _log("Synthesising wiki pages…")
        from rekipedia.synthesis.diagram_builder import DiagramBuilder
        from rekipedia.synthesis.page_builder import PageBuilder

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

        # ── Targeted re-synthesis: only pages whose sources changed ──
        # When --impact-only is set, further restrict to BFS-affected files
        if impact_only:
            _log("  Computing BFS impact graph for changed symbols…")
            impact_affected_files = _compute_impact_affected_files(
                changed_paths=changed_paths,
                store=store,
                run_id=run_id,
            )
            if impact_affected_files:
                _log(
                    f"  Impact-only: {len(impact_affected_files)} transitively affected file(s) "
                    f"(out of {len(changed_paths)} directly changed)"
                )
                synthesis_paths = impact_affected_files
            else:
                # Empty impact graph (e.g. brand new repo, no relationships yet) → fall back
                _log("  Impact graph empty — falling back to full changed-file synthesis…")
                synthesis_paths = changed_paths
        else:
            synthesis_paths = changed_paths

        affected_pages = store.get_pages_for_files(last_run_id, list(synthesis_paths))

        if not affected_pages:
            # No page_sources recorded yet (first update after upgrade) → full re-synthesis
            _log("  No page_sources recorded — running full re-synthesis (backward compat)…")
            builder = PageBuilder(llm_config)
            pages = builder.build(combined)

            diagram_builder = DiagramBuilder()
            diagrams = diagram_builder.build(all_rels_raw)

            store.upsert_pages_batch(run_id, pages)
            for slug, _ in pages.items():
                store.upsert_page_sources(run_id, slug, combined.files_seen)
            for name, (dtype, content) in diagrams.items():
                store.upsert_diagram(run_id, name, dtype, content)
        else:
            _log(f"  Re-synthesising {len(affected_pages)} affected page(s)…")
            all_page_slugs = store.get_all_page_slugs(last_run_id)
            unaffected = [s for s in all_page_slugs if s not in affected_pages]

            # Carry forward unaffected pages
            store.copy_pages(last_run_id, run_id, unaffected)
            store.carry_forward_page_sources(last_run_id, run_id, unaffected)

            # Re-synthesise affected pages
            builder = PageBuilder(llm_config)
            diagram_builder = DiagramBuilder()
            diagrams = diagram_builder.build(all_rels_raw)

            pages_dict: dict = {}
            # Load carried-forward pages for export
            for row in store.get_pages(run_id):
                # row is a tuple: (run_id, slug, title, content, pinned, updated_at)
                pages_dict[row[1]] = (row[2], row[3])

            for slug in affected_pages:
                result = builder.build_one(slug, combined)
                if result:
                    title, content = result
                    store.upsert_page(run_id, slug, title, content)
                    store.upsert_page_sources(run_id, slug, combined.files_seen)
                    pages_dict[slug] = (title, content)

            pages = pages_dict

            for name, (dtype, content) in diagrams.items():
                store.upsert_diagram(run_id, name, dtype, content)

        # ── 8. Export ─────────────────────────────────────────────────
        _log("Exporting…")
        from rekipedia.exporters.json_export import JsonExporter
        from rekipedia.exporters.markdown_export import MarkdownExporter

        MarkdownExporter(output_dir).export(pages, diagrams)
        JsonExporter(output_dir).export(run_id, current_files, combined, pages, diagrams)

        store.update_run_status(run_id, "success")
        _log("Done.")

        # ── 9. Incremental RAG embed ───────────────────────────────────
        try:
            from rekipedia.rag.embedder import EmbedPipeline
            pipe = EmbedPipeline(output_dir, llm_config, store=store, run_id=run_id)
            if pipe.is_built():
                _log("Updating RAG index (incremental)…")
                n_reembedded = pipe.update(
                    repo_root=repo_root,
                    changed_files=list(changed_paths),
                    last_run_id=last_run_id,
                    new_run_id=run_id,
                    progress_cb=_log,
                )
                _log(f"  RAG index updated — {n_reembedded} chunks re-embedded")
        except Exception as _rag_exc:
            import logging as _logging
            _logging.getLogger("rekipedia.run_update").warning("Incremental RAG embed failed (non-fatal): %s", _rag_exc)

    except Exception:
        # Best-effort status update — run_id may not exist yet if we raised early
        with contextlib.suppress(Exception):
            store.update_run_status(run_id, "failed")  # type: ignore[possibly-undefined]
        store.close()
        raise

    store.close()
