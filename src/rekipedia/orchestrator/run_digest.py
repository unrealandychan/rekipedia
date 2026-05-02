"""Main orchestration pipeline for `rekipedia scan`.

Flow:
    1. Snapshot repo → list[FileManifest]
    2. Shard files → list[Shard]
    3. Extract shards in parallel (ThreadPoolExecutor)
    4. Build diagrams (used by architecture page)
    5. Synthesise wiki pages in parallel (ThreadPoolExecutor)
    6. Export markdown + JSON
"""
from __future__ import annotations

import json
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable

from rekipedia.models.contracts import AnalysisResult, LLMConfig
from rekipedia.orchestrator.sharding import ShardPlanner
from rekipedia.orchestrator.snapshotter import Snapshotter
from rekipedia.sandbox.runner import BaseRunner, get_runner
from rekipedia.storage.sqlite_store import SqliteStore

logger = logging.getLogger("rekipedia")

# Max parallel workers for shard extraction and wiki page generation
_MAX_SHARD_WORKERS = 4
_MAX_PAGE_WORKERS = 4


def run_digest(
    repo_root: Path,
    output_dir: Path,
    llm_config: LLMConfig | None = None,
    *,
    force_local: bool = False,
    verbose: bool = False,
    progress: Callable[[str], None] | None = None,
    languages: list[str] | None = None,
) -> None:
    """Full scan pipeline.

    Args:
        repo_root: Absolute path to the repository to scan.
        output_dir: `.rekipedia/` directory; DB + wiki output goes here.
        llm_config: LLM settings; defaults to LLMConfig() which uses ollama/llama4.
        force_local: Skip Docker even if available.
        verbose: Enable debug logging (litellm, HTTP, stack traces).
        progress: Optional callback that receives status strings for display.
    """
    if verbose:
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        )
        logging.getLogger("rekipedia").setLevel(logging.DEBUG)
        logging.getLogger("LiteLLM").setLevel(logging.DEBUG)
        logging.getLogger("httpx").setLevel(logging.DEBUG)
        import litellm
        litellm._turn_on_debug()  # type: ignore[attr-defined]
        logger.debug("Verbose mode ON — all debug logs enabled")
    else:
        logging.basicConfig(level=logging.WARNING)

    from tqdm import tqdm  # noqa: PLC0415

    llm_config = llm_config or LLMConfig()
    _log = progress or (lambda _: None)

    def _vlog(msg: str) -> None:
        _log(msg)
        logger.debug(msg)

    run_id = str(uuid.uuid4())
    db_path = output_dir / "store.db"

    store = SqliteStore(db_path)
    store.open()

    try:
        store.upsert_run(run_id, str(repo_root))
        _vlog(f"Run {run_id[:8]} started")

        # ── 1. Snapshot ──────────────────────────────────────────────
        _vlog("Snapshotting repository…")
        snapshotter = Snapshotter(repo_root, languages=languages)
        files = snapshotter.snapshot()
        _vlog(f"  {len(files)} files found")

        store.upsert_snapshot(run_id, [f.model_dump() for f in files])
        for f in files:
            store.upsert_file(run_id, f.path, f.sha256, f.size_bytes, f.language)

        # ── 2. Shard ─────────────────────────────────────────────────
        _vlog("Planning shards…")
        planner = ShardPlanner()
        shards = planner.plan(files, llm_config)
        _vlog(f"  {len(shards)} shards planned")

        # ── 3. Extract shards in parallel ────────────────────────────
        runner: BaseRunner = get_runner(force_local=force_local)
        runner_name = type(runner).__name__
        _vlog(f"Using {runner_name} with up to {_MAX_SHARD_WORKERS} parallel workers")

        merged_results: list[AnalysisResult] = [None] * len(shards)  # type: ignore[list-item]
        shard_errors: list[str] = []

        shard_bar = tqdm(
            total=len(shards),
            desc="🔍 Extracting shards",
            unit="shard",
            dynamic_ncols=True,
            leave=True,
        )

        with ThreadPoolExecutor(max_workers=_MAX_SHARD_WORKERS) as executor:
            future_to_idx = {
                executor.submit(runner.run, shard, repo_root): (i, shard)
                for i, shard in enumerate(shards)
            }
            for future in as_completed(future_to_idx):
                i, shard = future_to_idx[future]
                shard_bar.set_postfix(id=shard.shard_id[:12])
                try:
                    result = future.result()
                    merged_results[i] = result
                    _vlog(f"  ✓ {shard.shard_id}: {len(result.symbols)} symbols, {len(result.relationships)} rels")
                except Exception as exc:
                    logger.error("Shard %s failed: %s", shard.shard_id, exc, exc_info=verbose)
                    shard_errors.append(f"{shard.shard_id}: {exc}")
                    merged_results[i] = AnalysisResult(
                        shard_id=shard.shard_id, files_seen=[], entry_points=[],
                        risks=[f"extraction failed: {exc}"]
                    )
                finally:
                    shard_bar.update(1)

        shard_bar.close()

        if shard_errors:
            _vlog(f"  ⚠ {len(shard_errors)} shard(s) failed — continuing with partial results")

        # Persist all results after parallel extraction (SQLite writes must be serial)
        for result in merged_results:
            if result:
                store.upsert_symbols(run_id, [s.model_dump() for s in result.symbols])
                store.upsert_relationships(run_id, [r.model_dump(by_alias=True) for r in result.relationships])

        # ── 4. Build diagrams ─────────────────────────────────────────
        _vlog("Building diagrams…")
        _log("Building diagrams…")
        from rekipedia.synthesis.diagram_builder import DiagramBuilder  # noqa: PLC0415

        all_symbols_raw = store.get_all_symbols(run_id)
        all_rels_raw = store.get_all_relationships(run_id)
        _vlog(f"  Total symbols: {len(all_symbols_raw)}, relationships: {len(all_rels_raw)}")

        combined = _combine_results([r for r in merged_results if r])
        diagram_builder = DiagramBuilder()
        diagrams = diagram_builder.build(all_rels_raw, entry_points=combined.entry_points)
        _vlog(f"  Built {len(diagrams)} diagram(s)")

        combined.evidence["pre_built_module_graph"] = diagrams.get("module-graph", (None, ""))[1]
        combined.evidence["pre_built_dependency_graph"] = diagrams.get("class-hierarchy", (None, ""))[1]

        # ── 5. Plan wiki structure then generate pages ────────────────
        _log("Planning wiki structure…")
        from rekipedia.synthesis.planner import PlannerAgent  # noqa: PLC0415
        from rekipedia.synthesis.page_builder import PageBuilder  # noqa: PLC0415

        combined_for_build = _combine_results([r for r in merged_results if r])
        combined_for_build.evidence["pre_built_module_graph"] = combined.evidence["pre_built_module_graph"]
        combined_for_build.evidence["pre_built_dependency_graph"] = combined.evidence["pre_built_dependency_graph"]

        planner = PlannerAgent(llm_config)

        # Live spinner for planner — shows thinking phases while LLM call blocks
        plan_bar = tqdm(
            bar_format="  {desc}",
            dynamic_ncols=True,
            leave=False,
        )

        def _plan_progress(msg: str) -> None:
            plan_bar.set_description_str(msg)
            plan_bar.refresh()

        wiki_plan = planner.plan(combined_for_build, diagrams=diagrams, progress_cb=_plan_progress)
        plan_bar.set_description_str(f"✅ {wiki_plan}")
        plan_bar.refresh()
        plan_bar.close()
        _log(f"  Wiki plan: {wiki_plan}")
        _vlog(f"  Wiki plan: {wiki_plan}")

        page_bar = tqdm(
            total=len(wiki_plan.pages),
            desc="📝 Generating wiki pages",
            unit="page",
            dynamic_ncols=True,
            leave=True,
        )

        builder = PageBuilder(llm_config)

        # Pre-build full payload once, then slice per page spec
        from rekipedia.synthesis.page_builder import _build_payload, _slice_payload  # noqa: PLC0415
        full_payload = _build_payload(combined_for_build, diagrams=diagrams)

        pages: dict[str, tuple[str, str]] = {}

        with ThreadPoolExecutor(max_workers=_MAX_PAGE_WORKERS) as executor:
            future_to_spec = {
                executor.submit(
                    builder._build_page_from_spec,
                    spec,
                    _slice_payload(full_payload, spec.get("required_data")),
                ): spec
                for spec in wiki_plan.pages
            }
            for future in as_completed(future_to_spec):
                spec = future_to_spec[future]
                slug = spec["slug"]
                page_bar.set_postfix(page=slug)
                try:
                    result = future.result()
                    if result:
                        pages[slug] = result
                        _vlog(f"  ✓ {slug}: {len(result[1])} chars")
                except Exception as exc:
                    logger.error("Page %s failed: %s", slug, exc, exc_info=verbose)
                    title = spec.get("title", slug.replace("-", " ").title())
                    pages[slug] = (title, f"# {title}\n\n> *Generation failed: {exc}*\n")
                finally:
                    page_bar.update(1)

        page_bar.close()

        # Store nav order in evidence for web UI
        combined_for_build.evidence["nav_order"] = json.dumps(wiki_plan.nav_order)
        combined_for_build.evidence["wiki_sections"] = json.dumps(wiki_plan.sections)
        combined_for_build.evidence["index_slug"] = wiki_plan.index_slug
        combined_for_build.evidence["wiki_pages_meta"] = json.dumps(
            [{k: v for k, v in p.items() if k != "focus"} for p in wiki_plan.pages]
        )

        for slug, (title, content) in pages.items():
            store.upsert_page(run_id, slug, title, content)
        for name, (dtype, content) in diagrams.items():
            store.upsert_diagram(run_id, name, dtype, content)

        # ── 6. Export ────────────────────────────────────────────────
        _vlog("Exporting…")
        _log("Exporting…")
        from rekipedia.exporters.json_export import JsonExporter  # noqa: PLC0415
        from rekipedia.exporters.markdown_export import MarkdownExporter  # noqa: PLC0415

        MarkdownExporter(output_dir).export(pages, diagrams)
        JsonExporter(output_dir).export(run_id, files, combined, pages, diagrams)

        # ── 7. Write scan_meta.json ───────────────────────────────────
        from rekipedia.rag.scan_meta import write_scan_meta  # noqa: PLC0415

        write_scan_meta(
            output_dir,
            repo_path=str(repo_root),
            model=llm_config.model,
            run_id=run_id,
            file_count=len(files),
            page_count=len(pages),
        )
        _vlog("scan_meta.json written")

        # ── 8. RAG embed (optional — skip if no embed key configured) ─
        embed_model = (
            __import__("os").environ.get("REKIPEDIA_EMBED_MODEL", "")
            or getattr(llm_config, "embed_model", "")
        )
        skip_embed = __import__("os").environ.get("REKIPEDIA_SKIP_EMBED", "").lower() in (
            "1", "true", "yes"
        )
        # Only embed when an explicit embed model is set (avoids surprise API calls)
        if embed_model and not skip_embed:
            _log("Building RAG embed index…")
            from rekipedia.rag.embedder import EmbedPipeline  # noqa: PLC0415
            from rekipedia.rag.scan_meta import patch_scan_meta  # noqa: PLC0415

            embed_bar = tqdm(
                bar_format="  {desc}",
                dynamic_ncols=True,
                leave=False,
            )

            def _embed_progress(msg: str) -> None:
                embed_bar.set_description_str(msg)
                embed_bar.refresh()

            try:
                pipe = EmbedPipeline(output_dir, llm_config)
                n_chunks = pipe.build(repo_root, progress_cb=_embed_progress)
                embed_bar.set_description_str(f"✅ Embedded {n_chunks} chunks")
                embed_bar.refresh()
                patch_scan_meta(output_dir, embedded=True, embed_model=embed_model)
            except Exception as embed_exc:
                logger.warning("RAG embed failed (non-fatal): %s", embed_exc)
                embed_bar.set_description_str(f"⚠ Embed skipped: {embed_exc}")
                embed_bar.refresh()
            finally:
                embed_bar.close()
        else:
            if not skip_embed:
                _vlog("REKIPEDIA_EMBED_MODEL not set — skipping RAG embed")

        store.update_run_status(run_id, "success")
        _vlog("Done.")

    except Exception:
        store.update_run_status(run_id, "failed")
        raise
    finally:
        store.close()


def _combine_results(results: list[AnalysisResult]) -> AnalysisResult:
    if not results:
        return AnalysisResult(shard_id="all", files_seen=[], entry_points=[])

    combined = AnalysisResult(shard_id="all", files_seen=[], entry_points=[])
    for r in results:
        combined.files_seen.extend(r.files_seen)
        combined.entry_points.extend(r.entry_points)
        combined.symbols.extend(r.symbols)
        combined.relationships.extend(r.relationships)
        combined.build_commands.extend(r.build_commands)
        combined.test_commands.extend(r.test_commands)
        combined.risks.extend(r.risks)
        combined.evidence.update(r.evidence)
    return combined
