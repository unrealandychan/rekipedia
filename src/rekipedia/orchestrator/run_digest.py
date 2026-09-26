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
import shutil
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from rich.console import Console as _Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeRemainingColumn,
)

_console = _Console(stderr=False)
if __import__("os").environ.get("REKIPEDIA_QUIET") == "1":
    _console.quiet = True

from rekipedia.models.contracts import AnalysisResult, LLMConfig


class StepEmitter:
    """Owns both the rich progress bar and the CLI callback channel.

    Calling :py:meth:`step` forwards *msg* to both sinks so callers no
    longer need to maintain two separate update lines.
    """

    def __init__(
        self,
        rich_progress: "Progress | None",
        task_id: "int | None",
        callback: "Callable[[str], None]",
    ) -> None:
        self._rich_progress = rich_progress
        self._task_id = task_id
        self._callback = callback

    def step(self, msg: str, *, advance: int = 1, description: str | None = None) -> None:
        """Advance the rich bar and fire the callback with *msg*."""
        if self._rich_progress is not None and self._task_id is not None:
            kwargs: dict = {"advance": advance}
            if description is not None:
                kwargs["description"] = description
            self._rich_progress.update(self._task_id, **kwargs)
        self._callback(msg)
from rekipedia.orchestrator.sharding import ShardPlanner
from rekipedia.orchestrator.snapshotter import Snapshotter
from rekipedia.sandbox.runner import BaseRunner, get_runner
from rekipedia.storage.sqlite_store import SqliteStore

logger = logging.getLogger("rekipedia")

# Max parallel workers for wiki page generation
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
    no_llm: bool = False,
    stdout_refactor: bool = False,
    focus_globs: list[str] | None = None,
    doc_type: str = "default",
    workers: int = 4,
    publish_dir: str | None = None,
    community_sharding: bool = False,
    force: bool = False,
    persona: str = "senior-dev",
    preset: str | None = None,
    use_engine: str = "internal",
) -> None:
    """Full scan pipeline.

    Args:
        repo_root: Absolute path to the repository to scan.
        output_dir: `.rekipedia/` directory; DB + wiki output goes here.
        llm_config: LLM settings; defaults to LLMConfig() which uses ollama/llama4.
        force_local: Skip Docker even if available.
        verbose: Enable debug logging (litellm, HTTP, stack traces).
        progress: Optional callback that receives status strings for display.
        languages: Optional list of language names to include (e.g. ["python"]).
        no_llm: Skip LLM enrichment for refactoring issues (static analysis only).
        stdout_refactor: When True, also print REFACTOR.md to stdout after writing.
        focus_globs: Optional list of glob patterns (relative to repo_root).
            When set, only files matching at least one pattern are extracted and
            used for wiki generation.  All other files are snapshotted for the
            DB but skipped during extraction.  Examples::

                ["src/auth/**", "src/payment/**"]
                ["*.rs", "Cargo.toml"]
                ["src/api/"]
        community_sharding: When True, group related files by real import/call
            edges from the previous scan before token-budget splitting.  Uses
            label-propagation on the actual dependency graph so semantically
            coupled files land in the same LLM context window.
            Requires at least one prior successful scan of the same repo;
            falls back to default directory-based sharding on the first run.
    """
    import os
    if os.environ.get("REKIPEDIA_QUIET") == "1":
        _console.quiet = True
    else:
        _console.quiet = False

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

    llm_config = llm_config or LLMConfig()
    _log = progress or (lambda _: None)

    def _vlog(msg: str) -> None:
        _log(msg)
        logger.debug(msg)

    run_id = str(uuid.uuid4())
    db_path = output_dir / "store.db"

    store = SqliteStore(db_path)
    store.open()

    # Reset token counter for this scan run
    from rekipedia.llm.client import TOKEN_COUNTER
    TOKEN_COUNTER.reset()

    try:
        store.upsert_run(run_id, str(repo_root))
        _vlog(f"Run {run_id[:8]} started")

        # ── 1. Snapshot ──────────────────────────────────────────────
        _vlog("Snapshotting repository…")
        snapshotter = Snapshotter(repo_root, languages=languages)
        files = snapshotter.snapshot()
        _vlog(f"  {len(files)} files found")

        store.upsert_snapshot(run_id, [f.model_dump() for f in files])
        store.upsert_files_batch(run_id, files)

        # ── Incremental scan optimization ──────────────────────────────
        extraction_files = files
        is_incremental = False
        changed_paths = set()
        last_run_id = None
        
        if not force:
            last_run_id = store.get_latest_run_id(str(repo_root))
            if last_run_id:
                _vlog(f"Found previous successful run {last_run_id[:8]} — checking for changes")
                prev_files = store.get_files_for_run(last_run_id)
                prev_map = {f["path"]: f["sha256"] for f in prev_files}
                
                current_map = {f.path: f for f in files}
                changed_files = [
                    f for f in files
                    if f.path not in prev_map or prev_map[f.path] != f.sha256
                ]
                deleted_paths = set(prev_map.keys()) - set(current_map.keys())
                changed_paths = {f.path for f in changed_files} | deleted_paths
                
                if not changed_files and not deleted_paths:
                    _vlog("No changes detected — repository is already up to date.")
                    _log("No changes detected — repository is already up to date.")
                    
                    # Carry forward ALL symbols and relationships to the new run
                    carried_syms = store.copy_unchanged_symbols(last_run_id, run_id, set())
                    carried_rels = store.copy_unchanged_relationships(last_run_id, run_id, set())
                    
                    # Also carry forward pages and page sources
                    all_page_slugs = store.get_all_page_slugs(last_run_id)
                    store.copy_pages(last_run_id, run_id, all_page_slugs)
                    store.carry_forward_page_sources(last_run_id, run_id, all_page_slugs)
                    
                    # Copy diagrams
                    from rekipedia.storage._helpers import _now
                    if "scan_diagrams" in store._table_names():
                        store._c.execute(
                            "INSERT OR REPLACE INTO scan_diagrams (run_id, name, type, content, updated_at) "
                            "SELECT ?, name, type, content, ? FROM scan_diagrams WHERE run_id = ?",
                            [run_id, _now(), last_run_id]
                        )
                        store._c.commit()
                    
                    # Update status to success and exit early
                    store.update_run_status(run_id, "success")
                    store.close()
                    return

                _vlog(f"  Incremental re-scan: {len(changed_files)} changed/new file(s), {len(deleted_paths)} deleted")
                _log(f"  Incremental re-scan: {len(changed_files)} changed/new file(s), {len(deleted_paths)} deleted")
                
                carried_syms = store.copy_unchanged_symbols(last_run_id, run_id, changed_paths)
                carried_rels = store.copy_unchanged_relationships(last_run_id, run_id, changed_paths)
                _vlog(f"  Carried forward {carried_syms} symbols, {carried_rels} relationships")
                
                extraction_files = changed_files
                is_incremental = True

        # ── 1.5. Focus filter ─────────────────────────────────────────
        if focus_globs:
            import fnmatch as _fnmatch
            def _matches_focus(file_rel: str) -> bool:
                for pattern in focus_globs:
                    # normalise pattern: strip leading ./ or /
                    pat = pattern.lstrip("./")
                    if _fnmatch.fnmatch(file_rel, pat):
                        return True
                    # also try matching against just the filename
                    if _fnmatch.fnmatch(file_rel.split("/")[-1], pat):
                        return True
                    # treat trailing / as directory prefix
                    if pat.endswith("/") and file_rel.startswith(pat):
                        return True
                return False

            focus_files = [f for f in extraction_files if _matches_focus(f.path)]
            skipped = len(extraction_files) - len(focus_files)
            _vlog(f"  --focus: {len(focus_files)} files matched ({skipped} skipped)")
            _log(f"  --focus: {len(focus_files)}/{len(extraction_files)} files in focus")
            if not focus_files:
                _vlog("  WARNING: no files matched focus patterns — falling back to all files")
                focus_files = extraction_files
            extraction_files = focus_files

        # ── 2. Shard ─────────────────────────────────────────────────
        _vlog("Planning shards…")
        if community_sharding:
            from rekipedia.analysis.graph_communities import detect_communities
            from rekipedia.orchestrator.sharding import CommunityShardPlanner

            # Use real import/call edges from the *previous* successful scan
            # of this repo (stored in SQLite).  On a first-time scan there is
            # no prior run, so we fall back to the default directory-based
            # ShardPlanner and warn the user.
            prev_run_id = store.get_latest_run_id(str(repo_root))
            real_edges: list[tuple[str, str]] = []
            if prev_run_id:
                prev_rels = store.get_all_relationships(prev_run_id)
                real_edges = [
                    (r["from_"], r["to"])
                    for r in prev_rels
                    if r.get("kind") in ("import", "imports", "call", "calls")
                    and r.get("from_") and r.get("to")
                ]
                _vlog(f"  community-sharding: loaded {len(real_edges)} import/call edges from previous scan")

            if real_edges:
                community_map = detect_communities(real_edges)
                n_communities = len(set(community_map.values()))
                planner: ShardPlanner = CommunityShardPlanner()
                shards = planner.plan_with_communities(extraction_files, community_map, llm_config)
                _vlog(f"  {len(shards)} community-aware shards planned ({n_communities} communities)")
            else:
                _vlog(
                    "  community-sharding: no prior import graph found "
                    "(first scan or empty repo) — falling back to default sharding"
                )
                _log("  ⚠ --community-sharding: no prior scan found; run a second scan to enable community-aware sharding.")
                planner = ShardPlanner()
                shards = planner.plan(extraction_files, llm_config)
                _vlog(f"  {len(shards)} shards planned (fallback)")
        else:
            planner = ShardPlanner()
            shards = planner.plan(extraction_files, llm_config)
            _vlog(f"  {len(shards)} shards planned")

        # ── 3. Extract shards in parallel (or delegate to external engine) ──
        if use_engine == "codebase-memory":
            _log("Delegating symbol extraction to codebase-memory-mcp engine…")
            from rekipedia.extractors.bridge.codebase_memory_bridge import CodebaseMemoryAdapter
            bridge_result = CodebaseMemoryAdapter.execute_bridge(repo_root)
            merged_results = [bridge_result]
            store.upsert_symbols(run_id, [s.model_dump() for s in bridge_result.symbols])
            store.upsert_relationships(run_id, [r.model_dump(by_alias=True) for r in bridge_result.relationships])
            _vlog(f"  codebase-memory: imported {len(bridge_result.symbols)} symbols and {len(bridge_result.relationships)} relationships")
        else:
            runner: BaseRunner = get_runner(force_local=force_local)
            runner_name = type(runner).__name__
            _vlog(f"Using {runner_name} with up to {workers} parallel workers")

            merged_results: list[AnalysisResult] = [None] * len(shards)  # type: ignore[list-item]
            shard_errors: list[str] = []

            _rich_progress = Progress(
                SpinnerColumn(),
                TextColumn("[bold cyan]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                TimeRemainingColumn(),
                console=_console,
                transient=False,
                disable=_console.quiet,
            )

            with _rich_progress:
                shard_task = _rich_progress.add_task(
                    f"[cyan]🔍 Shard 0/{len(shards)}",
                    total=len(shards),
                )
                _shard_done = 0
                _shard_emitter = StepEmitter(_rich_progress, shard_task, _log)

                with ThreadPoolExecutor(max_workers=workers) as executor:
                    future_to_idx = {
                        executor.submit(runner.run, shard, repo_root): (i, shard)
                        for i, shard in enumerate(shards)
                    }
                    for future in as_completed(future_to_idx):
                        i, shard = future_to_idx[future]
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
                            _shard_done += 1
                            _shard_emitter.step(
                                f"Shard {_shard_done}/{len(shards)}",
                                description=f"[cyan]🔍 Shard {_shard_done}/{len(shards)}",
                            )

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
        from rekipedia.synthesis.diagram_builder import DiagramBuilder

        all_symbols_raw = store.get_all_symbols(run_id)
        all_rels_raw = store.get_all_relationships(run_id)
        _vlog(f"  Total symbols: {len(all_symbols_raw)}, relationships: {len(all_rels_raw)}")

        if is_incremental:
            from rekipedia.models.contracts import Symbol, Relationship
            symbols_obj = []
            for s in all_symbols_raw:
                try:
                    symbols_obj.append(Symbol.model_validate(s))
                except Exception:
                    pass

            rels_obj = []
            for r in all_rels_raw:
                # Sanitize evidence_tag if it's not a valid literal value
                if r.get("evidence_tag") not in ("EXTRACTED", "INFERRED", "AMBIGUOUS"):
                    r["evidence_tag"] = "EXTRACTED"
                try:
                    rels_obj.append(Relationship.model_validate(r))
                except Exception:
                    pass
            files_seen = [f.path for f in files]
            
            combined = AnalysisResult(
                shard_id=run_id,
                files_seen=files_seen,
                entry_points=_combine_results([r for r in merged_results if r]).entry_points,
                symbols=symbols_obj,
                relationships=rels_obj,
                build_commands=_combine_results([r for r in merged_results if r]).build_commands,
                test_commands=_combine_results([r for r in merged_results if r]).test_commands,
                risks=_combine_results([r for r in merged_results if r]).risks,
            )
        else:
            combined = _combine_results([r for r in merged_results if r])
        from rekipedia.analysis.resolution import resolve_relationships
        combined = resolve_relationships(combined)
        diagram_builder = DiagramBuilder()
        diagrams = diagram_builder.build(all_rels_raw, entry_points=combined.entry_points)
        _vlog(f"  Built {len(diagrams)} diagram(s)")

        combined.evidence["pre_built_module_graph"] = diagrams.get("module-graph", (None, ""))[1]
        combined.evidence["pre_built_dependency_graph"] = diagrams.get("class-hierarchy", (None, ""))[1]

        # ── 4.5. Refactor enrichment ──────────────────────────────────
        _vlog("Running refactor issue detection…")
        _log("Detecting refactoring issues…")
        from rekipedia.analysis.refactor_enricher import RefactorEnricher
        from rekipedia.llm.client import LLMClient

        _enricher_caller = None if no_llm else LLMClient(llm_config)
        enricher = RefactorEnricher(_enricher_caller)
        notes_raw = store.get_rationale_notes(run_id)

        _enrich_count = [0]
        _enrich_total_holder: list[int] = []

        def _enrich_progress(msg: str) -> None:
            _log(msg)

        _enrich_rich = Progress(
            SpinnerColumn(),
            TextColumn("[bold yellow]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=_console,
            transient=True,
            disable=_console.quiet,
        )
        with _enrich_rich:
            # We don't know total until detect_issues runs inside enrich_all,
            # so start indeterminate then update when first callback fires
            _etask = _enrich_rich.add_task("[yellow]🔧 Enriching refactor issues…", total=None)

            _etask_total_set = [False]

            def _enrich_progress_rich(msg: str) -> None:
                _log(msg)
                # Parse "Enriched N/M" to update bar
                if "/" in msg and not _etask_total_set[0]:
                    try:
                        _, total_str = msg.split("/", 1)
                        total = int(total_str.strip().split()[0])
                        _enrich_rich.update(_etask, total=total,
                                            description="[yellow]🔧 Enriching refactor issues…")
                        _etask_total_set[0] = True
                    except (ValueError, IndexError):
                        pass
                if "/" in msg:
                    _enrich_rich.update(_etask, advance=1)

            refactor_issues = enricher.enrich_all(combined, notes=notes_raw, progress_cb=_enrich_progress_rich)
        _vlog(f"  {len(refactor_issues)} refactoring issue(s) detected")
        if no_llm:
            _vlog("  --no-llm: skipped LLM enrichment for refactoring issues")
        # Persist as JSON in evidence so exporters can surface it
        import json as _json
        combined.evidence["refactor_issues"] = _json.dumps(
            [i.to_dict() for i in refactor_issues], ensure_ascii=False
        )

        # ── 5. Plan wiki structure then generate pages ────────────────
        _log("Planning wiki structure…")
        from rekipedia.synthesis.page_builder import PageBuilder
        from rekipedia.synthesis.planner import PlannerAgent

        if is_incremental:
            combined_for_build = combined
        else:
            combined_for_build = _combine_results([r for r in merged_results if r])
        from rekipedia.analysis.resolution import resolve_relationships
        combined_for_build = resolve_relationships(combined_for_build)
        combined_for_build.evidence["pre_built_module_graph"] = combined.evidence["pre_built_module_graph"]
        combined_for_build.evidence["pre_built_dependency_graph"] = combined.evidence["pre_built_dependency_graph"]

        # Hyperedge detection (N-ary design patterns & architectural motifs)
        from rekipedia.analysis.hyperedge_detector import detect_hyperedges
        _llm_for_hyperedges = None if no_llm else LLMClient(llm_config)
        detected_hyperedges = detect_hyperedges(
            combined_for_build.symbols,
            combined_for_build.relationships,
            llm_client=_llm_for_hyperedges,
        )
        combined_for_build.hyperedges = detected_hyperedges
        store.upsert_hyperedges(run_id, detected_hyperedges)
        if detected_hyperedges:
            _vlog(f"  Detected {len(detected_hyperedges)} hyperedge(s)")

        planner = PlannerAgent(llm_config)

        # Live spinner for planner — shows thinking phases while LLM call blocks
        _plan_progress_msgs: list[str] = []

        def _plan_progress(msg: str) -> None:
            _plan_progress_msgs.append(msg)
            _log(msg)

        wiki_plan = planner.plan(combined_for_build, diagrams=diagrams, progress_cb=_plan_progress, persona=persona, preset=preset)
        _log(f"  Wiki plan: {wiki_plan}")
        _vlog(f"  Wiki plan: {wiki_plan}")

        _page_rich = Progress(
            TextColumn("[bold green]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeRemainingColumn(),
            console=_console,
            transient=False,
            refresh_per_second=4,
            disable=_console.quiet,
        )

        builder = PageBuilder(llm_config, doc_type=doc_type)

        # Pre-build full payload once, then slice per page spec
        from rekipedia.synthesis.page_builder import _build_payload, _slice_payload
        full_payload = _build_payload(combined_for_build, diagrams=diagrams)

        pages: dict[str, tuple[str, str]] = {}

        with _page_rich:
            page_task = _page_rich.add_task(
                f"[green]📝 Page 0/{len(wiki_plan.pages)}",
                total=len(wiki_plan.pages),
            )
            _page_done = 0
            _page_emitter = StepEmitter(_page_rich, page_task, _log)

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
                        _page_done += 1
                        _page_emitter.step(
                            f"Page {_page_done}/{len(wiki_plan.pages)}",
                            description=f"[green]📝 Page {_page_done}/{len(wiki_plan.pages)}",
                        )

        # Store nav order in evidence for web UI
        combined_for_build.evidence["nav_order"] = json.dumps(wiki_plan.nav_order)
        combined_for_build.evidence["wiki_sections"] = json.dumps(wiki_plan.sections)
        combined_for_build.evidence["index_slug"] = wiki_plan.index_slug
        combined_for_build.evidence["wiki_pages_meta"] = json.dumps(
            [{k: v for k, v in p.items() if k != "focus"} for p in wiki_plan.pages]
        )

        store.upsert_pages_batch(run_id, pages)
        for slug, _ in pages.items():
            store.upsert_page_sources(run_id, slug, combined_for_build.files_seen)
        for name, (dtype, content) in diagrams.items():
            store.upsert_diagram(run_id, name, dtype, content)

        # ── 6. Export ────────────────────────────────────────────────
        _vlog("Exporting…")
        _log("Exporting…")
        from rekipedia.exporters.json_export import JsonExporter
        from rekipedia.exporters.markdown_export import MarkdownExporter

        _log("Exporting wiki...")
        from rekipedia.exporters.json_export import JsonExporter
        from rekipedia.exporters.markdown_export import MarkdownExporter

        MarkdownExporter(output_dir, llm_client=None if no_llm else getattr(planner, "_client", None)).export(pages, diagrams, run_id=run_id, store=store)
        JsonExporter(output_dir).export(run_id, files, combined, pages, diagrams)

        # Write per-section index pages with full metadata (OKF §6 progressive disclosure)
        try:
            import json as _json
            from rekipedia.exporters.section_index import write_section_indexes
            manifest_path = output_dir / "exports" / "manifest.json"
            if manifest_path.exists():
                manifest_data = _json.loads(manifest_path.read_text(encoding="utf-8"))
                write_section_indexes(output_dir / "wiki", manifest_data.get("pages", []))
        except Exception:
            pass  # best-effort; never fail a scan over index generation

        # ── 7. Write scan_meta.json ───────────────────────────────────
        from rekipedia.rag.scan_meta import write_scan_meta

        write_scan_meta(
            output_dir,
            repo_path=str(repo_root),
            model=llm_config.model,
            run_id=run_id,
            file_count=len(files),
            page_count=len(pages),
        )
        _vlog("scan_meta.json written")

        # ── 7a. Standalone interactive graph.html (Graphify pattern) ─────
        try:
            from rekipedia.analysis.graph_export import export_interactive_html
            all_syms = store.get_all_symbols(run_id)
            all_rels = store.get_all_relationships(run_id)
            god_nodes_list = store.get_god_nodes(run_id, top_n=10)
            hypers_list = store.get_hyperedges(run_id)
            g_nodes = [
                {"id": s.name, "name": s.name, "kind": s.kind, "file": s.file}
                for s in all_syms if s.name
            ]
            existing_ids = {n["id"] for n in g_nodes}
            g_edges = []
            for r in all_rels:
                frm = r.get("from_", "") or r.get("from", "")
                to = r.get("to", "")
                if frm and to:
                    if frm not in existing_ids:
                        g_nodes.append({"id": frm, "name": frm, "kind": "module", "file": ""})
                        existing_ids.add(frm)
                    if to not in existing_ids:
                        g_nodes.append({"id": to, "name": to, "kind": "module", "file": ""})
                        existing_ids.add(to)
                    g_edges.append({"source": frm, "target": to, "kind": r.get("kind", "calls")})
            g_html = export_interactive_html(
                nodes=g_nodes,
                edges=g_edges,
                god_nodes=[{"name": n, "degree": d} for n, d in god_nodes_list],
                hyperedges=hypers_list,
                title=f"{repo_root.name} · Codebase Knowledge Graph",
            )
            (output_dir / "graph.html").write_text(g_html, encoding="utf-8")
            _vlog("graph.html written")
        except Exception as _g_exc:
            logger.debug("Failed to write standalone graph.html: %s", _g_exc)

        # ── 7b. Agent hint files & .mcp.json ─────────────────────────────
        from rekipedia.orchestrator.agent_hints import (
            update_gitignore,
            write_agent_hints,
            write_mcp_json,
        )
        written_hints = write_agent_hints(repo_root)
        for p in written_hints:
            logger.info("Wrote agent hint: %s", p)
        write_mcp_json(repo_root)
        update_gitignore(repo_root)

        # ── 7c. Refactor report ───────────────────────────────────────────
        from rekipedia.analysis.refactor_writer import write_refactor_outputs

        _vlog("Writing refactor report…")
        _log("Writing refactor report…")
        write_refactor_outputs(
            combined_for_build,
            output_dir,
            stdout=stdout_refactor,
        )
        _vlog("REFACTOR.md + refactor_report.json written")

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
            from rekipedia.rag.embedder import EmbedPipeline
            from rekipedia.rag.scan_meta import patch_scan_meta

            _embed_msgs: list[str] = []

            def _embed_progress(msg: str) -> None:
                _embed_msgs.append(msg)
                _log(msg)

            try:
                pipe = EmbedPipeline(output_dir, llm_config, store=store, run_id=run_id)
                if is_incremental and pipe.is_built():
                    _log("Updating RAG index (incremental)…")
                    n_chunks = pipe.update(
                        repo_root=repo_root,
                        changed_files=list(changed_paths),
                        last_run_id=last_run_id,
                        new_run_id=run_id,
                        progress_cb=_embed_progress,
                    )
                    _log(f"✅ RAG index updated — {n_chunks} chunks re-embedded")
                else:
                    n_chunks = pipe.build(repo_root, progress_cb=_embed_progress)
                    _log(f"✅ Embedded {n_chunks} chunks")
                patch_scan_meta(output_dir, embedded=True, embed_model=embed_model)
            except Exception as embed_exc:
                logger.warning("RAG embed failed (non-fatal): %s", embed_exc)
                _log(f"⚠ Embed skipped: {embed_exc}")
        else:
            if not skip_embed:
                _vlog("REKIPEDIA_EMBED_MODEL not set — skipping RAG embed")

        store.update_run_status(run_id, "success")
        _vlog("Done.")

        # ── Token usage summary ───────────────────────────────────────
        from rekipedia.llm.client import TOKEN_COUNTER
        if TOKEN_COUNTER.calls > 0:
            _console.print(
                f"\n[bold cyan]📊 {TOKEN_COUNTER.summary()}[/bold cyan]"
            )
            _log(TOKEN_COUNTER.summary())

        if publish_dir:
            _auto_publish(repo_root, output_dir, publish_dir)

        # ── Document extraction (opt-in) ─────────────────────────────
        from rekipedia.config.loader import load_config as _load_config
        _doc_cfg = _load_config(repo_root).get("documents", {})
        if _doc_cfg.get("enabled", False):
            _vlog("Extracting document files…")
            _log("Extracting documents…")
            from rekipedia.extractors.document_extractor import DocumentExtractor, SUPPORTED_EXTENSIONS
            _doc_extractor = DocumentExtractor()
            _max_mb = _doc_cfg.get("max_file_size_mb", 50) * 1024 * 1024
            _doc_extensions = set(_doc_cfg.get("extensions", list(SUPPORTED_EXTENSIONS)))
            _doc_files = [
                repo_root / f.path
                for f in files
                if Path(f.path).suffix.lower() in _doc_extensions
                and (repo_root / f.path).stat().st_size <= _max_mb
            ]
            _vlog(f"  Found {len(_doc_files)} document file(s)")
            _all_doc_chunks = []
            for _doc_path in _doc_files:
                _chunks = _doc_extractor.extract(_doc_path)
                _rel = str(_doc_path.relative_to(repo_root))
                for _c in _chunks:
                    _c.doc_path = _rel
                _all_doc_chunks.extend(_chunks)
                if _doc_cfg.get("wiki_page_per_doc", True) and _chunks:
                    _doc_text = "\n\n".join(f"**Page {c.page_number}:** {c.text}" for c in _chunks[:20])
                    _slug = "doc-" + _rel.replace("/", "-").replace(".", "-")
                    _title = f"📄 {Path(_rel).name}"
                    _summary = f"# {_title}\n\n**Source:** `{_rel}`\n\n{_doc_text}"
                    store.upsert_page(run_id, _slug, _title, _summary)
                    if _doc_cfg.get("thumbnails", False) and _doc_path.suffix.lower() == ".pdf":
                        _thumb_bytes = _doc_extractor.thumbnail(_doc_path, dpi=_doc_cfg.get("thumbnail_dpi", 150))
                        if _thumb_bytes:
                            _assets_dir = output_dir / "wiki" / "assets"
                            _assets_dir.mkdir(parents=True, exist_ok=True)
                            (_assets_dir / f"{_slug}-thumb.png").write_bytes(_thumb_bytes)
                            _summary = f"![thumbnail](assets/{_slug}-thumb.png)\n\n{_summary}"
                            store.upsert_page(run_id, _slug, _title, _summary)
            if _all_doc_chunks:
                store.upsert_document_chunks(run_id, [
                    {"doc_path": c.doc_path, "page_number": c.page_number,
                     "text": c.text, "bounding_box": c.bounding_box}
                    for c in _all_doc_chunks
                ])
                _vlog(f"  Stored {len(_all_doc_chunks)} document chunk(s)")

    except Exception:
        store.update_run_status(run_id, "failed")
        raise
    finally:
        store.close()


def _auto_publish(repo_root: Path, output_dir: Path, publish_dir: str) -> None:
    """Copy wiki, diagrams, and manifest to publish_dir."""
    pub = Path(publish_dir)
    if not pub.is_absolute():
        pub = (repo_root / pub).resolve()

    # wiki/*.md
    wiki_src = output_dir / "wiki"
    wiki_dst = pub / "wiki"
    if wiki_src.exists():
        wiki_dst.mkdir(parents=True, exist_ok=True)
        for md_file in wiki_src.glob("*.md"):
            shutil.copy2(md_file, wiki_dst / md_file.name)

    # diagrams/*.md
    diag_src = output_dir / "diagrams"
    diag_dst = pub / "diagrams"
    if diag_src.exists():
        diag_dst.mkdir(parents=True, exist_ok=True)
        for md_file in diag_src.glob("*.md"):
            shutil.copy2(md_file, diag_dst / md_file.name)

    # exports/manifest.json
    manifest_src = output_dir / "exports" / "manifest.json"
    if manifest_src.exists():
        pub.mkdir(parents=True, exist_ok=True)
        shutil.copy2(manifest_src, pub / "manifest.json")

    _console.print(f"[green]✔[/] Published wiki to {pub}")


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
