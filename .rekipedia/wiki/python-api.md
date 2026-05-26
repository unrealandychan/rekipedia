---
slug: python-api
title: "Public Python-Callable API Surface"
section: api-reference
tags: [reference, api]
pin: false
importance: 70
created_at: 2026-05-26T09:14:32Z
rekipedia_version: 0.17.25
---

# Public Python-Callable API Surface

This page documents the reusable, programmatic callable surface visible in the repository analysis, with emphasis on functions and classes that other code can import and call directly. It intentionally excludes test fixtures, benchmark entry points, and Go-side CLI commands. The goal is to identify the Python-facing analysis and extraction APIs, explain what they do, and show how they fit into the broader extraction pipeline.

## Scope and Package Breakdown

The Python-relevant callable surface in the analysis data is concentrated in three areas:

1. **Python extraction helpers and benchmark harnesses** under `benchmarks/`
2. **Fixture application code** in `benchmarks/fixtures/python_web_app/app.py`
3. **The Go implementation of the extraction/analyse pipeline** that Python code may invoke indirectly through exported Go APIs or process boundaries

Even though many reusable APIs are implemented in Go, they are still the practical public surface for programmatic use in the repository: the pipeline is exposed through constructor/runner types such as [`NewRegistry`](go/internal/extractor/extractor.go#L24), [`NewPythonExtractor`](go/internal/extractor/python.go#L28), [`NewTypeScriptExtractor`](go/internal/extractor/typescript.go#L28), [`NewGoExtractor`](go/internal/extractor/golang.go#L19), and orchestrators like [`RunDigest`](go/internal/orchestrator/run_digest.go#L48), [`RunUpdate`](go/internal/orchestrator/run_update.go#L30), [`RunAsk`](go/internal/orchestrator/run_ask.go#L59), and [`StreamAsk`](go/internal/orchestrator/run_ask.go#L112).

> **Sources:** `benchmarks/run_extraction.py` · `benchmarks/fixtures/python_web_app/app.py` · `go/internal/extractor/extractor.go` · `go/internal/extractor/python.go` · `go/internal/orchestrator/run_digest.go` · `go/internal/orchestrator/run_update.go` · `go/internal/orchestrator/run_ask.go`

## Python Benchmark and Extraction Harness

The Python module [`benchmarks.run_extraction`](benchmarks/run_extraction.py#L1) is the clearest native Python entry point in the analysis data. It provides a small benchmark harness around extraction behavior, with two callable functions intended for reuse in local experimentation:

| Symbol | Signature | Purpose | Source |
|---|---|---|---|
| [`run_extraction_benchmark`](benchmarks/run_extraction.py#L19) | `run_extraction_benchmark(verbose)` | Runs extraction accuracy benchmarks and returns a results dict | [`benchmarks/run_extraction.py`](benchmarks/run_extraction.py#L19-L74) |
| [`run_performance_benchmark`](benchmarks/run_extraction.py#L77) | `run_performance_benchmark(verbose)` | Benchmarks extraction speed using the Python fixture | [`benchmarks/run_extraction.py`](benchmarks/run_extraction.py#L77-L112) |
| [`main`](benchmarks/run_extraction.py#L115) | `main()` | Script entry point for the benchmark harness | [`benchmarks/run_extraction.py`](benchmarks/run_extraction.py#L115-L142) |

The benchmark module is useful as a reference for how the repository expects extraction to be orchestrated from Python, but it is not the primary API for application integration. Its value is in demonstrating the data flow: fixture files are scanned, extraction is measured, and results are returned in a structured form.

### Invocation Example

```python
from benchmarks.run_extraction import run_extraction_benchmark, run_performance_benchmark

results = run_extraction_benchmark(verbose=True)
speed = run_performance_benchmark(verbose=False)

print(results)
print(speed)
```

Because the analysis data does not include function bodies, the exact shape of the returned dictionaries should be treated as observed-by-name only. However, the docstring on [`run_extraction_benchmark`](benchmarks/run_extraction.py#L19) explicitly states that it “Returns results dict.”

> **Sources:** `benchmarks/run_extraction.py` · L19–L142 · [`run_extraction_benchmark`](benchmarks/run_extraction.py#L19) · [`run_performance_benchmark`](benchmarks/run_extraction.py#L77)

## Python Fixture Surface

The Python fixture application in [`benchmarks.fixtures.python_web_app.app`](benchmarks/fixtures/python_web_app/app.py#L1) is not a library package, but it is part of the observable callable surface used to validate extraction behavior. Its symbols show the kinds of Python constructs the extractor is expected to recognize:

| Symbol | Signature | Purpose | Source |
|---|---|---|---|
| [`User`](benchmarks/fixtures/python_web_app/app.py#L5) | class `User` | Simple model-like class with initializer | [`benchmarks/fixtures/python_web_app/app.py`](benchmarks/fixtures/python_web_app/app.py#L5-L8) |
| [`User.__init__`](benchmarks/fixtures/python_web_app/app.py#L6) | `__init__(self, name, email)` | Initializes name and email fields | [`benchmarks/fixtures/python_web_app/app.py`](benchmarks/fixtures/python_web_app/app.py#L6-L8) |
| [`get_user`](benchmarks/fixtures/python_web_app/app.py#L10) | `get_user(user_id)` | Retrieve a user by ID | [`benchmarks/fixtures/python_web_app/app.py`](benchmarks/fixtures/python_web_app/app.py#L10-L12) |
| [`create_user`](benchmarks/fixtures/python_web_app/app.py#L14) | `create_user(name, email)` | Create a new user | [`benchmarks/fixtures/python_web_app/app.py`](benchmarks/fixtures/python_web_app/app.py#L14-L16) |
| [`index`](benchmarks/fixtures/python_web_app/app.py#L19) | `index(user_id)` | Top-level app handler | [`benchmarks/fixtures/python_web_app/app.py`](benchmarks/fixtures/python_web_app/app.py#L19-L21) |

These are not reusable APIs in the project sense, but they are important because they represent realistic extraction targets. In other words, they are the “inputs” against which the public extractor surface is validated.

> **Sources:** `benchmarks/fixtures/python_web_app/app.py` · L1–L21 · [`User`](benchmarks/fixtures/python_web_app/app.py#L5) · [`get_user`](benchmarks/fixtures/python_web_app/app.py#L10) · [`create_user`](benchmarks/fixtures/python_web_app/app.py#L14) · [`index`](benchmarks/fixtures/python_web_app/app.py#L19)

## Extraction Pipeline APIs

The programmatic extraction pipeline is centered around the extractor registry and language-specific extractor implementations.

### Extractor Registry

[`Extractor`](go/internal/extractor/extractor.go#L11) defines the interface that concrete extractors implement. [`Registry`](go/internal/extractor/extractor.go#L19) aggregates implementations and routes file extraction to the correct handler. The main reusable constructor is [`NewRegistry`](go/internal/extractor/extractor.go#L24).

| Symbol | Signature | Purpose | Source |
|---|---|---|---|
| [`Extractor`](go/internal/extractor/extractor.go#L11) | interface | Contract for file extractors | [`go/internal/extractor/extractor.go`](go/internal/extractor/extractor.go#L11-L16) |
| [`Registry`](go/internal/extractor/extractor.go#L19) | struct `Registry` | Maps files to extractors | [`go/internal/extractor/extractor.go`](go/internal/extractor/extractor.go#L19-L21) |
| [`NewRegistry`](go/internal/extractor/extractor.go#L24) | constructor | Builds a registry with available extractors | [`go/internal/extractor/extractor.go`](go/internal/extractor/extractor.go#L24-L33) |
| [`(r *Registry).ExtractFile`](go/internal/extractor/extractor.go#L37) | `ExtractFile` | Extracts a single file via the matching extractor | [`go/internal/extractor/extractor.go`](go/internal/extractor/extractor.go#L37-L47) |
| [`MergeResults`](go/internal/extractor/extractor.go#L50) | function | Merges extraction results from multiple files | [`go/internal/extractor/extractor.go`](go/internal/extractor/extractor.go#L50-L68) |

### Language Extractors

The concrete extractors are exposed as reusable constructors:

| Symbol | Signature | Purpose | Source |
|---|---|---|---|
| [`PythonExtractor`](go/internal/extractor/python.go#L25) | struct `PythonExtractor` | Python file extractor implementation | [`go/internal/extractor/python.go`](go/internal/extractor/python.go#L25-L25) |
| [`NewPythonExtractor`](go/internal/extractor/python.go#L28) | constructor | Creates a Python extractor | [`go/internal/extractor/python.go`](go/internal/extractor/python.go#L28-L28) |
| [`(e *PythonExtractor).CanHandle`](go/internal/extractor/python.go#L31) | `CanHandle` | Determines whether a file can be parsed as Python | [`go/internal/extractor/python.go`](go/internal/extractor/python.go#L31-L34) |
| [`(e *PythonExtractor).Extract`](go/internal/extractor/python.go#L37) | `Extract` | Parses Python source into symbols/relationships | [`go/internal/extractor/python.go`](go/internal/extractor/python.go#L37-L135) |
| [`ExtractPythonFromReader`](go/internal/extractor/python.go#L188) | function | Extracts Python symbols from an `io.Reader` | [`go/internal/extractor/python.go`](go/internal/extractor/python.go#L188-L201) |

TypeScript and Go support the same pattern:

| Symbol | Signature | Purpose | Source |
|---|---|---|---|
| [`TypeScriptExtractor`](go/internal/extractor/typescript.go#L25) | struct `TypeScriptExtractor` | TypeScript extractor implementation | [`go/internal/extractor/typescript.go`](go/internal/extractor/typescript.go#L25-L25) |
| [`NewTypeScriptExtractor`](go/internal/extractor/typescript.go#L28) | constructor | Creates a TypeScript extractor | [`go/internal/extractor/typescript.go`](go/internal/extractor/typescript.go#L28-L28) |
| [`(e *TypeScriptExtractor).CanHandle`](go/internal/extractor/typescript.go#L31) | `CanHandle` | Checks whether the file is TypeScript | [`go/internal/extractor/typescript.go`](go/internal/extractor/typescript.go#L31-L37) |
| [`(e *TypeScriptExtractor).Extract`](go/internal/extractor/typescript.go#L40) | `Extract` | Extracts TypeScript symbols and relationships | [`go/internal/extractor/typescript.go`](go/internal/extractor/typescript.go#L40-L141) |
| [`GoExtractor`](go/internal/extractor/golang.go#L16) | struct `GoExtractor` | Go extractor implementation | [`go/internal/extractor/golang.go`](go/internal/extractor/golang.go#L16-L16) |
| [`NewGoExtractor`](go/internal/extractor/golang.go#L19) | constructor | Creates a Go extractor | [`go/internal/extractor/golang.go`](go/internal/extractor/golang.go#L19-L19) |
| [`(e *GoExtractor).CanHandle`](go/internal/extractor/golang.go#L22) | `CanHandle` | Checks whether the file is Go | [`go/internal/extractor/golang.go`](go/internal/extractor/golang.go#L22-L24) |
| [`(e *GoExtractor).Extract`](go/internal/extractor/golang.go#L27) | `Extract` | Extracts Go symbols and relationships | [`go/internal/extractor/golang.go`](go/internal/extractor/golang.go#L27-L134) |

### Example: Programmatic File Extraction

```go
reg := extractor.NewRegistry()
result, err := reg.ExtractFile("path/to/module.py", content)
if err != nil {
    // handle error
}
merged := extractor.MergeResults([]models.AnalysisResult{result})
_ = merged
```

This is the most direct call chain for library consumers interested in extracting symbols from source files.

> **Sources:** `go/internal/extractor/extractor.go` · L11–L68 · [`Extractor`](go/internal/extractor/extractor.go#L11) · [`NewRegistry`](go/internal/extractor/extractor.go#L24) · [`MergeResults`](go/internal/extractor/extractor.go#L50) · `go/internal/extractor/python.go` · L25–L201 · [`ExtractPythonFromReader`](go/internal/extractor/python.go#L188)

## Orchestration and Analysis APIs

Above the file-level extractors sits the orchestration layer, which combines snapshotting, sharding, digesting, update flows, and interactive Q&A. These are the APIs most likely to be reused by other code.

### Core Orchestrator Types

| Symbol | Signature | Purpose | Source |
|---|---|---|---|
| [`AskOptions`](go/internal/orchestrator/run_ask.go#L34) | struct `AskOptions` | Options for ask/query workflows | [`go/internal/orchestrator/run_ask.go`](go/internal/orchestrator/run_ask.go#L34-L40) |
| [`AskResult`](go/internal/orchestrator/run_ask.go#L43) | struct `AskResult` | Result payload for ask workflows | [`go/internal/orchestrator/run_ask.go`](go/internal/orchestrator/run_ask.go#L43-L48) |
| [`DigestOptions`](go/internal/orchestrator/run_digest.go#L27) | struct `DigestOptions` | Configuration for digest runs | [`go/internal/orchestrator/run_digest.go`](go/internal/orchestrator/run_digest.go#L27-L36) |
| [`UpdateOptions`](go/internal/orchestrator/run_update.go#L16) | struct `UpdateOptions` | Configuration for update runs | [`go/internal/orchestrator/run_update.go`](go/internal/orchestrator/run_update.go#L16-L20) |
| [`ShardPlanner`](go/internal/orchestrator/sharding.go#L20) | struct `ShardPlanner` | Splits snapshots into manageable shards | [`go/internal/orchestrator/sharding.go`](go/internal/orchestrator/sharding.go#L20-L22) |
| [`Snapshotter`](go/internal/orchestrator/snapshotter.go#L57) | struct `Snapshotter` | Walks the repository and builds a snapshot | [`go/internal/orchestrator/snapshotter.go`](go/internal/orchestrator/snapshotter.go#L57-L62) |

### Primary Entry Functions

| Symbol | Signature | Purpose | Source |
|---|---|---|---|
| [`RunAsk`](go/internal/orchestrator/run_ask.go#L59) | function | Executes a non-streaming ask flow | [`go/internal/orchestrator/run_ask.go`](go/internal/orchestrator/run_ask.go#L59-L109) |
| [`StreamAsk`](go/internal/orchestrator/run_ask.go#L112) | function | Executes a streaming ask flow | [`go/internal/orchestrator/run_ask.go`](go/internal/orchestrator/run_ask.go#L112-L140) |
| [`RunDigest`](go/internal/orchestrator/run_digest.go#L48) | function | Runs the extraction/digest pipeline over shards | [`go/internal/orchestrator/run_digest.go`](go/internal/orchestrator/run_digest.go#L48-L312) |
| [`RunUpdate`](go/internal/orchestrator/run_update.go#L30) | function | Runs the update pipeline over changed content | [`go/internal/orchestrator/run_update.go`](go/internal/orchestrator/run_update.go#L30-L179) |
| [`NewShardPlanner`](go/internal/orchestrator/sharding.go#L26) | function | Creates a shard planner with a token budget | [`go/internal/orchestrator/sharding.go`](go/internal/orchestrator/sharding.go#L26-L36) |
| [`(sp *ShardPlanner).Plan`](go/internal/orchestrator/sharding.go#L39) | method | Produces shard plan from manifests | [`go/internal/orchestrator/sharding.go`](go/internal/orchestrator/sharding.go#L39-L62) |
| [`NewSnapshotter`](go/internal/orchestrator/snapshotter.go#L67) | function | Creates a snapshotter with ignore/language configuration | [`go/internal/orchestrator/snapshotter.go`](go/internal/orchestrator/snapshotter.go#L67-L86) |
| [`(s *Snapshotter).Snapshot`](go/internal/orchestrator/snapshotter.go#L89) | method | Produces a repository snapshot | [`go/internal/orchestrator/snapshotter.go`](go/internal/orchestrator/snapshotter.go#L89-L147) |

### Supporting Helpers

These are internal helpers, but they are still part of the callable surface and explain how orchestration works:

- [`extractShard`](go/internal/orchestrator/run_digest.go#L316)
- [`mergeInto`](go/internal/orchestrator/run_digest.go#L336)
- [`combineResults`](go/internal/orchestrator/run_digest.go#L349)
- [`tryRAGSearch`](go/internal/orchestrator/run_ask.go#L144)
- [`loadWikiPages`](go/internal/orchestrator/run_ask.go#L160)
- [`buildContext`](go/internal/orchestrator/run_ask.go#L219)
- [`finishDigest`](go/internal/orchestrator/helpers.go#L18)

### Cross-Module Dependency Table

| Module | Imports From | Called By | Calls Into | Inherits From |
|--------|-------------|-----------|------------|---------------|
| `go/internal/orchestrator/run_digest.go` | `go/internal/extractor`, `go/internal/rag`, `go/internal/storage`, `go/internal/models` | CLI/root entry paths, update flows | `extractShard`, `combineResults`, storage writes | — |
| `go/internal/orchestrator/run_update.go` | `go/internal/orchestrator/sharding`, `snapshotter`, `run_digest` | CLI/root entry paths | `RunDigest` | — |
| `go/internal/orchestrator/run_ask.go` | `go/internal/rag`, `go/internal/storage`, `go/internal/llm` | server ask endpoints | `buildContext`, `tryRAGSearch` | — |
| `go/internal/orchestrator/sharding.go` | `go/internal/models` | `RunDigest`, `RunUpdate` | `fileTokenEstimate`, `topLevelDir` | — |
| `go/internal/orchestrator/snapshotter.go` | `go/internal/models` | `RunUpdate` | file walking, hashing, language detection | — |

### Example: Pipeline Invocation

```go
snapshotter := orchestrator.NewSnapshotter(ignorePatterns, languages)
snap, err := snapshotter.Snapshot(repoRoot)
if err != nil {
    return err
}

planner := orchestrator.NewShardPlanner(12000)
shards := planner.Plan(snap.Manifests)

result, err := orchestrator.RunDigest(ctx, orchestrator.DigestOptions{
    RepoRoot: repoRoot,
    Shards:   shards,
})
if err != nil {
    return err
}
_ = result
```

This flow shows the typical pipeline chain: snapshot → shard planning → digest/extraction → merged analysis results.

> **Sources:** `go/internal/orchestrator/run_ask.go` · L34–L269 · `go/internal/orchestrator/run_digest.go` · L27–L399 · `go/internal/orchestrator/run_update.go` · L16–L179 · `go/internal/orchestrator/sharding.go` · L20–L114 · `go/internal/orchestrator/snapshotter.go` · L57–L172

## Analysis and Refinement APIs

For consumers interested in code-quality analysis over extracted symbols and relationships, the repository exposes a set of reusable detectors and enrichers.

### Refactor Detectors

[`DetectGodNodes`](go/internal/analysis/refactor_detector.go#L30), [`DetectCircularDeps`](go/internal/analysis/refactor_detector.go#L103), [`DetectDeadCode`](go/internal/analysis/refactor_detector.go#L204), [`DetectHighFanIn`](go/internal/analysis/refactor_detector.go#L234), [`DetectHighFanOut`](go/internal/analysis/refactor_detector.go#L279), [`DetectDeepInheritance`](go/internal/analysis/refactor_detector.go#L323), and [`DetectAll`](go/internal/analysis/refactor_detector.go#L404) form the public analysis API for refactoring heuristics.

### Refactor Types

| Symbol | Signature | Purpose | Source |
|---|---|---|---|
| [`RefactorIssue`](go/internal/analysis/refactor_types.go#L24) | struct `RefactorIssue` | Describes one detected issue | [`go/internal/analysis/refactor_types.go`](go/internal/analysis/refactor_types.go#L24-L38) |
| [`RefactorSummary`](go/internal/analysis/refactor_types.go#L41) | struct `RefactorSummary` | Aggregated issue counts | [`go/internal/analysis/refactor_types.go`](go/internal/analysis/refactor_types.go#L41-L45) |
| [`RefactorReport`](go/internal/analysis/refactor_types.go#L60) | struct `RefactorReport` | Full report structure | [`go/internal/analysis/refactor_types.go`](go/internal/analysis/refactor_types.go#L60-L65) |
| [`RefactorEnricher`](go/internal/analysis/refactor_enricher.go#L296) | struct `RefactorEnricher` | Adds LLM-backed enrichment to findings | [`go/internal/analysis/refactor_enricher.go`](go/internal/analysis/refactor_enricher.go#L296-L298) |
| [`NewRefactorEnricher`](go/internal/analysis/refactor_enricher.go#L302) | constructor | Creates a refactor enricher | [`go/internal/analysis/refactor_enricher.go`](go/internal/analysis/refactor_enricher.go#L302-L304) |

### Reusable Callables

| Symbol | Signature | Purpose | Source |
|---|---|---|---|
| [`DetectIssues`](go/internal/analysis/refactor_enricher.go#L99) | function | Detects and classifies issues from analysis results | [`go/internal/analysis/refactor_enricher.go`](go/internal/analysis/refactor_enricher.go#L99-L246) |
| [`AttachCallers`](go/internal/analysis/refactor_enricher.go#L249) | function | Adds caller context to findings | [`go/internal/analysis/refactor_enricher.go`](go/internal/analysis/refactor_enricher.go#L249-L264) |
| [`AttachNotes`](go/internal/analysis/refactor_enricher.go#L268) | function | Associates notes with findings | [`go/internal/analysis/refactor_enricher.go`](go/internal/analysis/refactor_enricher.go#L268-L290) |
| [`(e *RefactorEnricher).EnrichAll`](go/internal/analysis/refactor_enricher.go#L308) | method | Enriches all findings | [`go/internal/analysis/refactor_enricher.go`](go/internal/analysis/refactor_enricher.go#L308-L319) |
| [`(e *RefactorEnricher).Enrich`](go/internal/analysis/refactor_enricher.go#L324) | method | Enriches a list of findings | [`go/internal/analysis/refactor_enricher.go`](go/internal/analysis/refactor_enricher.go#L324-L347) |
| [`buildPrompt`](go/internal/analysis/refactor_enricher.go#L361) | function | Builds the LLM prompt for enrichment | [`go/internal/analysis/refactor_enricher.go`](go/internal/analysis/refactor_enricher.go#L361-L405) |
| [`parseEnrichment`](go/internal/analysis/refactor_enricher.go#L407) | function | Parses model output into structured enrichment | [`go/internal/analysis/refactor_enricher.go`](go/internal/analysis/refactor_enricher.go#L407-L422) |

### Example: Detection Pipeline

```go
issues := analysis.DetectAll(results)
enricher := analysis.NewRefactorEnricher(llmClient, store)
enriched, err := enricher.EnrichAll(ctx, issues)
if err != nil {
    return err
}
```

The detection API is deliberately split from enrichment: you can use the static detectors without any LLM dependency, then optionally add [`RefactorEnricher`](go/internal/analysis/refactor_enricher.go#L296) for more context.

> **Sources:** `go/internal/analysis/refactor_detector.go` · L19–L413 · `go/internal/analysis/refactor_enricher.go` · L99–L533 · `go/internal/analysis/refactor_types.go` · L24–L65

## Practical Invocation Examples

### Extract a Single Source File

Use the registry and a language-specific extractor:

```go
reg := extractor.NewRegistry()
res, err := reg.ExtractFile("app.py", sourceText)
if err != nil {
    return err
}
```

### Run a Repository Digest

A digest run generally combines snapshotting, shard planning, and extraction:

```go
opts := orchestrator.DigestOptions{
    RepoRoot: "/path/to/repo",
    // other options elided; see struct definition
}
report, err := orchestrator.RunDigest(ctx, opts)
if err != nil {
    return err
}
```

### Build or Query RAG Data

Once chunks and vectors are available, the RAG APIs are reusable on their own:

| Symbol | Signature | Purpose | Source |
|---|---|---|---|
| [`Chunk`](go/internal/rag/chunker.go#L11) | struct `Chunk` | Represents a text chunk | [`go/internal/rag/chunker.go`](go/internal/rag/chunker.go#L11-L17) |
| [`ChunkFile`](go/internal/rag/chunker.go#L40) | function | Splits source/doc files into chunks | [`go/internal/rag/chunker.go`](go/internal/rag/chunker.go#L40-L90) |
| [`EmbedPipeline`](go/internal/rag/embedder.go#L15) | struct `EmbedPipeline` | End-to-end embedding/search pipeline | [`go/internal/rag/embedder.go`](go/internal/rag/embedder.go#L15-L18) |
| [`NewEmbedPipeline`](go/internal/rag/embedder.go#L21) | constructor | Creates an embedding pipeline | [`go/internal/rag/embedder.go`](go/internal/rag/embedder.go#L21-L26) |
| [`(e *EmbedPipeline).Build`](go/internal/rag/embedder.go#L30) | method | Builds embeddings for chunks | [`go/internal/rag/embedder.go`](go/internal/rag/embedder.go#L30-L84) |
| [`(e *EmbedPipeline).Search`](go/internal/rag/embedder.go#L87) | method | Searches embedded chunks | [`go/internal/rag/embedder.go`](go/internal/rag/embedder.go#L87-L102) |
| [`VectorStore`](go/internal/rag/vector_store.go#L15) | struct `VectorStore` | Persistent embedding store | [`go/internal/rag/vector_store.go`](go/internal/rag/vector_store.go#L15-L18) |
| [`NewVectorStore`](go/internal/rag/vector_store.go#L27) | constructor | Creates a vector store | [`go/internal/rag/vector_store.go`](go/internal/rag/vector_store.go#L27-L29) |

```go
chunks := rag.ChunkFile(path, content)
store := rag.NewVectorStore()
pipeline := rag.NewEmbedPipeline(client, store)

if err := pipeline.Build(ctx, chunks); err != nil {
    return err
}
results, err := pipeline.Search(ctx, "initialization flow")
```

> **Sources:** `go/internal/rag/chunker.go` · L11–L94 · `go/internal/rag/embedder.go` · L15–L102 · `go/internal/rag/vector_store.go` · L15–L118

## Notes on Programmatic Use

The repository exposes a layered API surface:

- **Lowest level:** file extractors like [`PythonExtractor`](go/internal/extractor/python.go#L25) and [`GoExtractor`](go/internal/extractor/golang.go#L16)
- **Mid level:** registry and merge helpers like [`NewRegistry`](go/internal/extractor/extractor.go#L24) and [`MergeResults`](go/internal/extractor/extractor.go#L50)
- **High level:** orchestrators such as [`RunDigest`](go/internal/orchestrator/run_digest.go#L48), [`RunUpdate`](go/internal/orchestrator/run_update.go#L30), [`RunAsk`](go/internal/orchestrator/run_ask.go#L59), and [`StreamAsk`](go/internal/orchestrator/run_ask.go#L112)
- **Analysis layer:** detectors like [`DetectAll`](go/internal/analysis/refactor_detector.go#L404) and enrichers like [`NewRefactorEnricher`](go/internal/analysis/refactor_enricher.go#L302)

For programmatic consumers, the best integration strategy is usually:
1. build or load a snapshot,
2. extract symbols/relationships through the registry,
3. persist via storage or feed into the orchestrator,
4. optionally run analysis/enrichment,
5. query with RAG/ask APIs if semantic lookup is needed.

> **Sources:** `go/internal/extractor/extractor.go` · L11–L68 · `go/internal/orchestrator/run_digest.go` · L48–L399 · `go/internal/analysis/refactor_detector.go` · L30–L413 · `go/internal/rag/embedder.go` · L15–L102