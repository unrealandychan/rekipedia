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

from rekipedia.models.contracts import AnalysisResult, LLMConfig
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
    with_git: bool = False,
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
        # Suppress LiteLLM info/help spam on stderr — users only need to see rekipedia output
        logging.getLogger("LiteLLM").setLevel(logging.ERROR)
        logging.getLogger("litellm").setLevel(logging.ERROR)
        logging.getLogger("httpx").setLevel(logging.ERROR)
        logging.getLogger("httpcore").setLevel(logging.ERROR)
        try:
            import litellm as _litellm
            _litellm.suppress_debug_info = True  # suppress "Give Feedback / Provider List" prints
        except Exception:
            pass

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

        # ── 1.6. Git history ─────────────────────────────────────────
        if with_git:
            try:
                from rekipedia.extractors.git_extractor import commits_to_dicts, extract_commits
                _vlog("⠙ 🔀 Indexing git history…")
                git_commits = extract_commits(repo_root)
                if git_commits:
                    store.store_commits(commits_to_dicts(git_commits))
                    _vlog(f"⠙ 🔀 Indexing git history… ({len(git_commits)} commits)")
                else:
                    _vlog("⠙ 🔀 No git history found (skipped)")
            except Exception as _git_err:
                logger.debug("Git extraction failed (non-fatal): %s", _git_err)


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

            focus_files = [f for f in files if _matches_focus(f.path)]
            skipped = len(files) - len(focus_files)
            _vlog(f"  --focus: {len(focus_files)} files matched ({skipped} skipped)")
            _log(f"  --focus: {len(focus_files)}/{len(files)} files in focus")
            if not focus_files:
                _vlog("  WARNING: no files matched focus patterns — falling back to all files")
                focus_files = files
            extraction_files = focus_files
        else:
            extraction_files = files

        # ── 2. Shard ─────────────────────────────────────────────────
        _vlog("Planning shards…")
        planner = ShardPlanner()
        shards = planner.plan(extraction_files, llm_config)
        _vlog(f"  {len(shards)} shards planned")

        # ── 3. Extract shards in parallel ────────────────────────────
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
            transient=False,
        )

        with _rich_progress:
            shard_task = _rich_progress.add_task(
                f"[cyan]🔍 Shard 0/{len(shards)}",
                total=len(shards),
            )
            _shard_done = 0

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
                        _rich_progress.update(
                            shard_task,
                            advance=1,
                            description=f"[cyan]🔍 Shard {_shard_done}/{len(shards)}",
                        )
                        _log(f"Shard {_shard_done}/{len(shards)}")

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
            transient=True,
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

        combined_for_build = _combine_results([r for r in merged_results if r])
        from rekipedia.analysis.resolution import resolve_relationships
        combined_for_build = resolve_relationships(combined_for_build)
        combined_for_build.evidence["pre_built_module_graph"] = combined.evidence["pre_built_module_graph"]
        combined_for_build.evidence["pre_built_dependency_graph"] = combined.evidence["pre_built_dependency_graph"]

        if no_llm:
            from rekipedia.synthesis.planner import WikiPlan
            wiki_plan = WikiPlan.default(combined_for_build)
            _vlog("  --no-llm: skipped PlannerAgent, using default wiki plan")
        else:
            planner = PlannerAgent(llm_config)

            # Live spinner for planner — shows thinking phases while LLM call blocks
            _plan_progress_msgs: list[str] = []

            def _plan_progress(msg: str) -> None:
                _plan_progress_msgs.append(msg)
                _log(msg)

            wiki_plan = planner.plan(combined_for_build, diagrams=diagrams, progress_cb=_plan_progress)
        _log(f"  Wiki plan: {wiki_plan}")
        _vlog(f"  Wiki plan: {wiki_plan}")

        pages: dict[str, tuple[str, str]] = {}

        if no_llm:
            # --no-llm: skip all LLM page generation, write stub pages only
            for spec in wiki_plan.pages:
                slug = spec["slug"]
                title = spec.get("title", slug)
                stub = (
                    f"# {title}\n\n"
                    "> Generated with `--no-llm`. "
                    "Run `reki scan` with an LLM provider for full wiki content.\n"
                )
                pages[slug] = (stub, "")
        else:
            builder = PageBuilder(llm_config, doc_type=doc_type)
            from rekipedia.synthesis.page_builder import _build_payload, _slice_payload
            full_payload = _build_payload(combined_for_build, diagrams=diagrams)

            _page_rich = Progress(
                TextColumn("[bold green]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                TimeRemainingColumn(),
                transient=False,
                refresh_per_second=4,
            )
            with _page_rich:
                page_task = _page_rich.add_task(
                    f"[green]📝 Page 0/{len(wiki_plan.pages)}",
                    total=len(wiki_plan.pages),
                )
                _page_done = 0

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
                            _page_rich.update(
                                page_task,
                                advance=1,
                                description=f"[green]📝 Page {_page_done}/{len(wiki_plan.pages)}",
                            )
                            _log(f"Page {_page_done}/{len(wiki_plan.pages)}")

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

        MarkdownExporter(output_dir).export(pages, diagrams)
        JsonExporter(output_dir).export(run_id, files, combined, pages, diagrams)

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
                pipe = EmbedPipeline(output_dir, llm_config)
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
