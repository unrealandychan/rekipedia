---
slug: technical-debt
title: "Code Debt, Test Gaps, and Maintenance Risks"
section: development
tags: [contributing, internals]
pin: false
importance: 70
created_at: 2026-05-26T09:14:58Z
rekipedia_version: 0.17.25
---

# Code Debt, Test Gaps, and Maintenance Risks

## Highest-Risk Issues

The most consequential debt in this repository is concentrated in the refactor-analysis pipeline and its surrounding runtime dependencies. The primary risk is not a lack of functionality, but the combination of broad traversal logic, heuristic classification, and several external integrations that can fail in ways that are hard to detect until a scan/update run is already in progress. In particular, the detector/enricher stack in [`detect_god_nodes`](src/rekipedia/analysis/refactor_detector.py#L30), [`detect_circular_deps`](src/rekipedia/analysis/refactor_detector.py#L103), [`detect_dead_code`](src/rekipedia/analysis/refactor_detector.py#L204), and [`detect_issues`](src/rekipedia/analysis/refactor_enricher.py#L99) is intentionally heuristic-driven. That is appropriate for “find likely debt” workflows, but it means false positives and false negatives are an inherent maintenance risk, especially when the code also depends on the shape of symbol metadata from [`Symbol`](src/rekipedia/models/contracts.py#L53) and relationship records from [`Relationship`](src/rekipedia/models/contracts.py#L64).

A second high-risk area is the LLM integration in [`Client`](src/rekipedia/llm/client.py#L110) and the orchestration layers that call it, such as [`RunDigest`](src/rekipedia/orchestrator/run_digest.py#L48), [`RunAsk`](src/rekipedia/orchestrator/run_ask.py#L59), and [`PlannerAgent`](src/rekipedia/synthesis/planner.py#L77). These code paths are covered by tests, but they still rely on third-party APIs and retry behavior that can degrade operational reliability if provider semantics change.

Finally, the storage layer and server entry points are reasonably well-tested, but they include a large amount of logic that is easy to regress when schema or template behavior changes. The strongest evidence of stability is the breadth of tests around [`Store`](src/rekipedia/storage/store.go#L20), [`Server`](src/rekipedia/server/server.go#L35), and their helper flows, but the maintenance burden remains non-trivial because these modules are the connective tissue for almost every feature.

> **Sources:** `go/internal/analysis/refactor_detector.go` · L30–L413 · [`detect_god_nodes`](go/internal/analysis/refactor_detector.go#L30), [`detect_circular_deps`](go/internal/analysis/refactor_detector.go#L103), [`detect_dead_code`](go/internal/analysis/refactor_detector.go#L204), [`detect_high_fan_in`](go/internal/analysis/refactor_detector.go#L234), [`detect_high_fan_out`](go/internal/analysis/refactor_detector.go#L279), [`detect_deep_inheritance`](go/internal/analysis/refactor_detector.go#L323)  
> **Sources:** `go/internal/analysis/refactor_enricher.go` · L99–L357 · [`detect_issues`](go/internal/analysis/refactor_enricher.go#L99), [`AttachCallers`](go/internal/analysis/refactor_enricher.go#L249), [`AttachNotes`](go/internal/analysis/refactor_enricher.go#L268), [`RefactorEnricher`](go/internal/analysis/refactor_enricher.go#L296)  
> **Sources:** `go/internal/llm/client.go` · L110–L385 · [`Client`](go/internal/llm/client.go#L110), [`CallWithRetry`](go/internal/llm/client.go#L166), [`StreamCall`](go/internal/llm/client.go#L204), [`Embed`](go/internal/llm/client.go#L234)

## Issues Table

| Issue | Location | Impact | Recommended Remediation |
|---|---|---|---|
| Heuristic debt detectors can over/under-report because they infer smell categories from metadata and naming patterns | [`detect_god_nodes`](go/internal/analysis/refactor_detector.go#L30), [`detect_dead_code`](go/internal/analysis/refactor_detector.go#L204), [`detect_deep_inheritance`](go/internal/analysis/refactor_detector.go#L323) | Medium-high: noisy findings reduce trust in generated reports and can cause real issues to be ignored | Tighten scoring thresholds, add fixture-based regression tests for borderline cases, and document the expected false-positive envelope |
| Cycle detection and enrichment have multi-step graph traversal logic with deduplication/canonicalization concerns | [`detect_circular_deps`](go/internal/analysis/refactor_detector.go#L103), [`findCycles`](go/internal/analysis/refactor_enricher.go#L428), [`cycleKey`](go/internal/analysis/refactor_enricher.go#L466) | High: duplicated or missed cycles can distort refactor priorities | Add directed graph fixtures with overlapping cycles, self-loops, and disconnected components; assert canonical cycle formatting |
| LLM-backed enrichment introduces provider/network fragility into the analysis pipeline | [`Client`](go/internal/llm/client.go#L110), [`New`](go/internal/llm/client.go#L120), [`CallWithRetry`](go/internal/llm/client.go#L166), [`RunDigest`](go/internal/orchestrator/run_digest.go#L48), [`PlannerAgent.Plan`](go/internal/synthesis/planner.go#L88) | High: transient provider failures or API drift can break synthesis and update flows | Keep the retry/backoff behavior explicit, add tests for provider error classes, and isolate parsing from transport concerns |
| Storage and alias layers duplicate CRUD surfaces across `store.go` and `aliases.go` | [`Store`](go/internal/storage/store.go#L20), [`UpsertRun`](go/internal/storage/aliases.go#L9), [`GetAllRelationships`](go/internal/storage/aliases.go#L64) | Medium: duplicated entry points increase the chance of inconsistency during schema changes | Treat aliases as thin compatibility wrappers only; add contract tests around alias parity with direct store methods |
| Server endpoints embed substantial rendering and query logic in a single module | [`handleAPIAskStream`](go/internal/server/server.go#L232), [`handleAPIWikiSearch`](go/internal/server/server.go#L802), [`listPagesAndSections`](go/internal/server/server.go#L466) | Medium-high: regressions in one endpoint can affect unrelated routes because of shared internal helpers | Split complex read paths into smaller helpers with focused tests around search, page listing, and graph assembly |
| Export/build steps depend on version metadata and file-system writes without much separation from presentation | [`BuildMarkdown`](go/internal/analysis/refactor_writer.go#L177), [`WriteRefactorOutputs`](go/internal/analysis/refactor_writer.go#L269), [`_rekipedia_version`](go/internal/analysis/refactor_writer.go#L44) | Medium: version or format changes can break generated artifacts | Add golden-file tests for markdown/json outputs and keep version injection as a small, injectable dependency |
| Cross-repo search and graph computations rely on repository-walker style operations and concurrency | [`search_all_repos`](src/rekipedia/analysis/cross_repo_search.py), [`compute_impact`](src/rekipedia/analysis/impact.py), [`compute_transitive_impact`](src/rekipedia/analysis/impact.py) | Medium: concurrency and repository enumeration bugs can skew ranking or omit repos | Add deterministic ordering tests and stress cases for empty, missing, and large repo lists |
| Test utilities and fixtures are heavily reused, which is good coverage but increases coupling to exact fixture shapes | `tests/fixtures/mini-py-repo/*`, `tests/fixtures/mini-ts-repo/*`, [`makeTestRepo`](go/cmd/rekipedia/cmd/refactor_test.go#L50), [`makeTestServer`](go/internal/server/server_test.go#L17) | Low-medium: a fixture change can cascade across many tests | Keep fixtures intentionally small and versioned; prefer helper builders over implicit fixture file assumptions |
| External dependency on SQLite implementation and database migration path is central to persistence | [`Open`](go/internal/storage/store.go#L26), [`migrate`](go/internal/storage/store.go#L50), `modernc.org/sqlite` | Medium: SQL driver or migration issues affect every persistence-backed command | Maintain migration-focused tests and pin driver behavior with CI; document schema compatibility expectations |
| Template rendering and frontmatter stripping logic can silently change output structure | [`renderTemplate`](go/internal/server/server.go#L103), [`stripFrontmatter`](go/internal/server/server.go#L940), [`handleWikiPage`](go/internal/server/server.go#L147) | Medium: user-facing pages may render incorrectly while API behavior appears fine | Add rendering golden tests and keep frontmatter parsing isolated from HTML/template concerns |

> **Sources:** `go/internal/analysis/refactor_detector.go` · L30–L413 · [`detect_god_nodes`](go/internal/analysis/refactor_detector.go#L30), [`detect_circular_deps`](go/internal/analysis/refactor_detector.go#L103), [`detect_dead_code`](go/internal/analysis/refactor_detector.go#L204), [`detect_high_fan_in`](go/internal/analysis/refactor_detector.go#L234), [`detect_high_fan_out`](go/internal/analysis/refactor_detector.go#L279), [`detect_deep_inheritance`](go/internal/analysis/refactor_detector.go#L323)  
> **Sources:** `go/internal/analysis/refactor_enricher.go` · L99–L357 · [`detect_issues`](go/internal/analysis/refactor_enricher.go#L99), [`findCycles`](go/internal/analysis/refactor_enricher.go#L428), [`AttachCallers`](go/internal/analysis/refactor_enricher.go#L249), [`AttachNotes`](go/internal/analysis/refactor_enricher.go#L268)  
> **Sources:** `go/internal/server/server.go` · L103–L955 · [`renderTemplate`](go/internal/server/server.go#L103), [`listPagesAndSections`](go/internal/server/server.go#L466), [`handleAPIWikiSearch`](go/internal/server/server.go#L802), [`stripFrontmatter`](go/internal/server/server.go#L940)  
> **Sources:** `go/internal/storage/store.go` · L26–L575 · [`Open`](go/internal/storage/store.go#L26), [`migrate`](go/internal/storage/store.go#L50), [`SaveSymbols`](go/internal/storage/store.go#L170), [`SaveRelationships`](go/internal/storage/store.go#L221)

## Debt by Subsystem

### Analysis and Refactor Detection

This subsystem is the clearest source of visible technical debt because it encodes policy in code: what counts as dead code, what counts as a “god node,” and how cycles are deduplicated. The core functions are compact, but they depend on metadata invariants from [`AnalysisResult`](go/internal/models/contracts.go#L82), [`Symbol`](go/internal/models/contracts.go#L53), and [`Relationship`](go/internal/models/contracts.go#L64). That makes the code powerful but also brittle: if a producer changes symbol shape, every heuristic changes behavior.

The most notable entry points are [`DetectGodNodes`](go/internal/analysis/refactor_detector.go#L30), [`DetectCircularDeps`](go/internal/analysis/refactor_detector.go#L103), [`DetectDeadCode`](go/internal/analysis/refactor_detector.go#L204), [`DetectHighFanIn`](go/internal/analysis/refactor_detector.go#L234), [`DetectHighFanOut`](go/internal/analysis/refactor_detector.go#L279), and [`DetectDeepInheritance`](go/internal/analysis/refactor_detector.go#L323). They are individually tested in [`go/internal/analysis/refactor_detector_test.go`](go/internal/analysis/refactor_detector_test.go), which is a strong sign of maturity, but the subsystem still depends on heuristic thresholds and path-based exclusions.

### Orchestration, LLM, and Synthesis

The orchestration layer is structurally healthy but maintenance-heavy. [`RunAsk`](go/internal/orchestrator/run_ask.go#L59), [`RunDigest`](go/internal/orchestrator/run_digest.go#L48), and [`RunUpdate`](go/internal/orchestrator/run_update.go#L30) form the main execution flow, while [`PlannerAgent.Plan`](go/internal/synthesis/planner.go#L88) and [`PageBuilder.BuildAll`](go/internal/synthesis/page_builder.go#L71) generate downstream artifacts. The debt here is mostly in control flow complexity rather than code style: these functions need to coordinate storage, extraction, LLM calls, and output generation.

The good news is that the surrounding tests are broad. There are explicit tests for planner fallback behavior, page building, and LLM client behavior, which reduces the risk that this complexity is completely unbounded.

### Storage, Server, and API Surfaces

The persistence layer is a classic “central dependency” subsystem. [`Store`](go/internal/storage/store.go#L20) owns SQLite setup, schema migration, and all major CRUD methods. The wrapper aliases in [`go/internal/storage/aliases.go`](go/internal/storage/aliases.go) preserve compatibility, but they also mean that API surface area is larger than the core schema would suggest.

The server layer compounds this by exposing many routes from a single [`Server`](go/internal/server/server.go#L35) implementation. The code is not obviously problematic, but methods like [`handleAPIGraph`](go/internal/server/server.go#L649), [`handleAPIWikiSearch`](go/internal/server/server.go#L802), and [`listPagesAndSections`](go/internal/server/server.go#L466) are large enough that maintenance requires discipline. This is one of the better-covered areas in the repository, which is a positive counterbalance.

### Python and Cross-Repo Analysis

The Python-facing analysis modules such as [`rekipedia.analysis.cross_repo_search`](src/rekipedia/analysis/cross_repo_search.py) and [`rekipedia.analysis.impact`](src/rekipedia/analysis/impact.py) show more algorithmic debt than structural debt. They are doing the right job, but their correctness depends on ranking math, repository enumeration, and thread-pool behavior. That makes them more sensitive to performance and ordering regressions than the more deterministic storage layer.

> **Sources:** `go/internal/analysis/refactor_detector.go` · L30–L413 · [`DetectAll`](go/internal/analysis/refactor_detector.go#L404)  
> **Sources:** `go/internal/orchestrator/run_ask.go` · L59–L269 · [`RunAsk`](go/internal/orchestrator/run_ask.go#L59), [`buildContext`](go/internal/orchestrator/run_ask.go#L219)  
> **Sources:** `go/internal/orchestrator/run_digest.go` · L48–L399 · [`RunDigest`](go/internal/orchestrator/run_digest.go#L48), [`combineResults`](go/internal/orchestrator/run_digest.go#L349)  
> **Sources:** `go/internal/storage/store.go` · L26–L575 · [`Open`](go/internal/storage/store.go#L26), [`SaveSymbols`](go/internal/storage/store.go#L170), [`ListWikiPages`](go/internal/storage/store.go#L291)  
> **Sources:** `go/internal/server/server.go` · L35–L955 · [`handleAPIGraph`](go/internal/server/server.go#L649), [`handleAPIWikiSearch`](go/internal/server/server.go#L802), [`stripFrontmatter`](go/internal/server/server.go#L940)

## Test Gaps and Areas That Are Well Covered

The repository is not broadly under-tested. In fact, several subsystems are quite well covered, and that matters when prioritizing debt:

- The refactor detector is well covered by [`go/internal/analysis/refactor_detector_test.go`](go/internal/analysis/refactor_detector_test.go), including empty-input cases, deduplication, threshold boundaries, and self-loop exclusions.
- The enricher has dedicated tests for prompt construction, parsing, caller attachment, and LLM failure behavior in [`go/internal/analysis/refactor_enricher_test.go`](go/internal/analysis/refactor_enricher_test.go).
- Storage has an especially strong suite in [`go/internal/storage/store_test.go`](go/internal/storage/store_test.go), including lifecycle, multiple runs, manifest handling, notes, tree data, and relationships.
- The server is also comparatively healthy: [`go/internal/server/server_test.go`](go/internal/server/server_test.go) covers health, API pages, graph endpoints, wiki rendering, missing pages, and error paths.
- LLM client behavior is not neglected; [`go/internal/llm/client_test.go`](go/internal/llm/client_test.go) exercises request/stream/embed flows, cancellation, transient error classification, and message building.

That said, the most visible gaps are not “no tests at all” but rather “tests that prove behavior on ideal or fixture-shaped inputs.” The most useful additions would be boundary tests around long, unusual, or partially malformed inputs in the heuristic detectors, plus golden tests for generated markdown and server rendering. There is also a gap in cross-module integration tests that exercise a full chain end-to-end.

### Balanced Coverage Summary

| Subsystem | Coverage Signal | Risk Still Remaining |
|---|---|---|
| Refactor detection | High, with targeted detector tests | Heuristic thresholds and metadata drift |
| Storage | High, with lifecycle and schema-ish coverage | Migration and compatibility changes |
| Server | High, with route/error coverage | Rendering and multi-helper coupling |
| LLM client | Good, with transport simulations | Provider drift and retry semantics |
| Cross-repo search / impact analysis | Moderate; fewer visible targeted tests in the analysis data | Ordering, concurrency, and ranking regressions |

> **Sources:** `go/internal/analysis/refactor_detector_test.go` · L16–L394 · [`TestDetectGodNodes_DetectsHub`](go/internal/analysis/refactor_detector_test.go#L23), [`TestDetectCircularDeps_SimpleCycle`](go/internal/analysis/refactor_detector_test.go#L88), [`TestDetectDeadCode_PrivatePythonFlagged`](go/internal/analysis/refactor_detector_test.go#L135), [`TestDetectDeepInheritance_Detected`](go/internal/analysis/refactor_detector_test.go#L281)  
> **Sources:** `go/internal/analysis/refactor_enricher_test.go` · L45–L413 · [`TestDetectGodClass`](go/internal/analysis/refactor_enricher_test.go#L45), [`TestAttachCallers`](go/internal/analysis/refactor_enricher_test.go#L184), [`TestParseEnrichmentAllFields`](go/internal/analysis/refactor_enricher_test.go#L250), [`TestEnricherLLMErrorLeavesFieldsEmpty`](go/internal/analysis/refactor_enricher_test.go#L328)  
> **Sources:** `go/internal/storage/store_test.go` · L22–L467 · [`TestRunLifecycle`](go/internal/storage/store_test.go#L37), [`TestMultipleRunsIsolated`](go/internal/storage/store_test.go#L184), [`TestUpsertTree`](go/internal/storage/store_test.go#L392)  
> **Sources:** `go/internal/server/server_test.go` · L27–L396 · [`TestHealth`](go/internal/server/server_test.go#L27), [`TestAPIGraph`](go/internal/server/server_test.go#L203), [`TestWikiPageRendered`](go/internal/server/server_test.go#L91), [`TestAPIAskBadJSON`](go/internal/server/server_test.go#L187)  
> **Sources:** `go/internal/llm/client_test.go` · L88–L295 · [`TestCallSuccess`](go/internal/llm/client_test.go#L138), [`TestStreamCall`](go/internal/llm/client_test.go#L180), [`TestEmbedSuccess`](go/internal/llm/client_test.go#L221), [`TestIsTransient`](go/internal/llm/client_test.go#L247)

## Dependency and Maintenance Concerns

The main maintenance concern is third-party dependency concentration around a few pivotal interfaces. The Go stack depends on `github.com/sashabaranov/go-openai` in [`Client`](go/internal/llm/client.go#L110), `modernc.org/sqlite` in [`Store`](go/internal/storage/store.go#L20), `github.com/go-chi/chi/v5` in [`Server`](go/internal/server/server.go#L35), and `github.com/google/uuid` in orchestration paths like [`RunDigest`](go/internal/orchestrator/run_digest.go#L48) and [`RunUpdate`](go/internal/orchestrator/run_update.go#L30). None of these are inherently problematic, but they are “blast radius” dependencies: if any shifts, many call sites break.

The second concern is the internal contract layer in [`go/internal/models/contracts.go`](go/internal/models/contracts.go). This file is the schema backbone for symbols, relationships, wiki pages, shards, scan metadata, and LLM configuration. That is a good design choice for traceability, but it also means that contract changes have wide downstream impact.

The third concern is long-term drift between analysis and presentation layers. Functions like [`BuildMarkdown`](go/internal/analysis/refactor_writer.go#L177), [`export_graphml`](src/rekipedia/analysis/graph_export.py), and server rendering helpers all transform the same underlying data into different formats. The repository already has strong test coverage for many of these paths, but the coupling itself means compatibility work will remain ongoing.

> **Sources:** `go/internal/llm/client.go` · L110–L385 · [`Client`](go/internal/llm/client.go#L110), [`CallWithRetry`](go/internal/llm/client.go#L166), [`Embed`](go/internal/llm/client.go#L234)  
> **Sources:** `go/internal/storage/store.go` · L20–L575 · [`Store`](go/internal/storage/store.go#L20), [`migrate`](go/internal/storage/store.go#L50)  
> **Sources:** `go/internal/server/server.go` · L35–L955 · [`Server`](go/internal/server/server.go#L35), [`newRouter`](go/internal/server/server.go#L50), [`handleAPIWikiSearch`](go/internal/server/server.go#L802)  
> **Sources:** `go/internal/models/contracts.go` · L6–L169 · [`LLMConfig`](go/internal/models/contracts.go#L6), [`AnalysisResult`](go/internal/models/contracts.go#L82), [`WikiPlan`](go/internal/models/contracts.go#L139), [`ScanMeta`](go/internal/models/contracts.go#L160)