---
slug: index
title: "Repository Overview"
section: getting-started
tags: [overview, getting-started, repository-structure]
pin: false
importance: 100
created_at: 2026-05-26T09:13:12Z
rekipedia_version: 0.17.25
---

# Repository Overview

## What it is

Rekipedia is a cross-language repository intelligence tool that scans source trees, extracts symbols and relationships, stores the results, and turns them into searchable documentation and interactive views. The project is intentionally split across two primary runtimes: a Python package for the main user workflow and analysis pipeline, and a Go implementation for the CLI/server/runtime core and higher-performance orchestration pieces. The codebase also includes benchmark fixtures and test repositories that make it easier to validate behavior end to end.

At a high level, first-time contributors should think of Rekipedia as a system that takes a codebase, analyzes it, and then exposes the results through commands like scan, search, serve, export, and update. The core data model for those results is defined in [`AnalysisResult`](go/internal/models/contracts.go#L82), [`Symbol`](go/internal/models/contracts.go#L53), and [`Relationship`](go/internal/models/contracts.go#L64). The Go runtime entry point is [`main`](go/cmd/rekipedia/main.go#L6), while the Python package entry point is [`src/rekipedia/__main__.py`](src/rekipedia/__main__.py).

## Key features

The repository is organized around a few major capabilities:

- **CLI-driven workflow** for scanning, querying, exporting, and updating repository analysis.
- **Source extraction** for multiple languages, including Python, Go, and TypeScript via language-specific extractors.
- **Search and retrieval** functionality that supports symbol lookup and RAG-style retrieval over scanned content.
- **Serve mode** that exposes a local web UI and API for browsing pages, graphs, and Q&A.
- **Export/update pipelines** that generate wiki pages and persist analysis state.
- **Benchmarks and fixtures** that provide reproducible inputs for performance and regression testing.
- **Storage-backed persistence** for runs, symbols, relationships, wiki pages, notes, and history.

A good way to orient yourself is to look at the runtime-facing modules:
- CLI commands in `src/rekipedia/cli/`
- Extraction logic in `src/rekipedia/extractors/`
- Search/RAG components in `src/rekipedia/rag/`
- Server and API in `src/rekipedia/server/`
- Persistence in `src/rekipedia/storage/`
- Equivalent Go implementations under `go/internal/`

## Primary runtimes

Rekipedia intentionally supports two runtime environments:

| Runtime | Role | Representative files |
|---|---|---|
| Python | Main package, CLI surface, extraction/search/export orchestration | `src/rekipedia/__init__.py`, `src/rekipedia/cli/scan.py`, `src/rekipedia/extractors/python_extractor.py`, `src/rekipedia/server/app.py` |
| Go | Fast CLI/server binary, storage-backed runtime, orchestration and analysis services | `go/cmd/rekipedia/main.go`, `go/cmd/rekipedia/cmd/root.go`, `go/internal/server/server.go`, `go/internal/orchestrator/run_digest.go` |

The Go side centers around the CLI entrypoint [`main`](go/cmd/rekipedia/main.go#L6) and the command tree rooted at [`Execute`](go/cmd/rekipedia/cmd/root.go#L44). The Python side is packaged in `pyproject.toml` and exposed through `src/rekipedia/__main__.py`.

## User-facing capabilities

Rekipedia’s public surface is built around a small set of commands and modes that users actually run.

### CLI

The CLI is the main entry point for interactive use. In the Go implementation, subcommands are registered from [`Execute`](go/cmd/rekipedia/cmd/root.go#L44) and implemented in files such as [`go/cmd/rekipedia/cmd/scan.go`](go/cmd/rekipedia/cmd/scan.go), [`go/cmd/rekipedia/cmd/search.go`](go/cmd/rekipedia/cmd/search.go), and [`go/cmd/rekipedia/cmd/serve.go`](go/cmd/rekipedia/cmd/serve.go). The Python package exposes parallel CLI modules under `src/rekipedia/cli/`, including [`src/rekipedia/cli/scan.py`](src/rekipedia/cli/scan.py) and [`src/rekipedia/cli/search.py`](src/rekipedia/cli/search.py).

### Scanning and extraction

Scanning walks a repository, detects supported file types, and extracts symbols plus relationships. The Go extractor registry is built around [`NewRegistry`](go/internal/extractor/extractor.go#L24), the [`Extractor`](go/internal/extractor/extractor.go#L11) interface, and concrete implementations such as [`PythonExtractor`](go/internal/extractor/python.go#L25), [`GoExtractor`](go/internal/extractor/golang.go#L16), and [`TypeScriptExtractor`](go/internal/extractor/typescript.go#L25). In Python, the equivalent extractors live in `src/rekipedia/extractors/`.

### Search

Search is exposed as a user command and backed by token scoring and retrieval data. In Go, search logic includes [`tokenizeSymbol`](go/cmd/rekipedia/cmd/search.go#L20) and [`scoreBM25`](go/cmd/rekipedia/cmd/search.go#L54). The Python side also provides cross-repo search support in [`src/rekipedia/analysis/cross_repo_search.py`](src/rekipedia/analysis/cross_repo_search.py) and RAG storage in `src/rekipedia/rag/`.

### Serve

Serve mode starts a local web app with wiki pages, graph browsing, ask endpoints, and API routes. The Go server implementation is centered on [`Server`](go/internal/server/server.go#L35) and handlers like [`(s *Server).Start`](go/internal/server/server.go#L71), [`(s *Server).handleIndex`](go/internal/server/server.go#L133), and [`(s *Server).handleAPIAsk`](go/internal/server/server.go#L274). The Python package has a parallel server app in [`src/rekipedia/server/app.py`](src/rekipedia/server/app.py).

### Export and update

Export/update workflows generate artifacts and persist them back into the repo state. In Go, these are surfaced through commands such as [`go/cmd/rekipedia/cmd/export.go`](go/cmd/rekipedia/cmd/export.go) and [`go/cmd/rekipedia/cmd/update.go`](go/cmd/rekipedia/cmd/update.go), while the orchestrator uses [`RunUpdate`](go/internal/orchestrator/run_update.go#L30) and the synthesis layer uses [`PageBuilder`](go/internal/synthesis/page_builder.go#L60) and [`PlannerAgent`](go/internal/synthesis/planner.go#L77). The Python side provides exporters in `src/rekipedia/exporters/`.

### Benchmarks

Benchmarks live under `benchmarks/` and include a dedicated runner at [`benchmarks/run_extraction.py`](benchmarks/run_extraction.py#L1). Fixtures include a small Python web app and a TypeScript React app to exercise extraction and analysis across languages.

### Test fixtures

The repository includes realistic fixtures for both the product test suite and benchmark coverage:
- `tests/fixtures/mini-py-repo/`
- `tests/fixtures/mini-ts-repo/`
- `benchmarks/fixtures/python_web_app/`
- `benchmarks/fixtures/typescript_react/`

These fixtures are useful when validating scanning, extraction, search, and serve behavior without needing a large external codebase.

## Quick start

A representative build-and-run path for the Go runtime is:

```bash
CGO_ENABLED=0 go build -ldflags "-s -w" -o /tmp/reki ./cmd/rekipedia
/tmp/reki --help
```

If you are working from the Python package, the repository also supports Python packaging/build workflows via `uv build` and `hatch build`, as reflected in the repository’s build command set.

## Repository map

Here is a small map of the major top-level directories and what they are for:

| Directory | Purpose |
|---|---|
| `src/rekipedia/` | Python package: CLI, extractors, analysis, RAG, server, storage, synthesis |
| `go/` | Go implementation: CLI commands, internal analysis/orchestration/server/storage layers |
| `benchmarks/` | Benchmark runner and reproducible extraction fixtures |
| `tests/` | End-to-end and unit tests plus fixture repositories |
| `docs/` | User and planning documentation |
| `algo/` | Algorithm notes and design docs |
| `schemas/` | JSON schemas for analysis and output contracts |
| `examples/` | Example configuration files |

## Architecture at a glance

At a high level, the repository is split into two complementary implementation tracks: Python for packaging and higher-level workflows, and Go for the main CLI/server/runtime path. The user-visible capabilities described on this page are implemented by layers that roughly flow from command entrypoints into orchestration, extraction/analysis, persistence, and presentation. For a deeper architectural view, start with the architecture pages and then follow the module-specific docs from there; this landing page intentionally stays at a contributor-friendly, high-level summary.

## Getting started as a contributor

If you are new to the repo, a practical onboarding path is:

1. Run the quick-start build command above.
2. Inspect the CLI entrypoints in `go/cmd/rekipedia/cmd/` and `src/rekipedia/cli/`.
3. Skim the extractors in `go/internal/extractor/` and `src/rekipedia/extractors/`.
4. Try the benchmark fixture runner in [`benchmarks/run_extraction.py`](benchmarks/run_extraction.py#L1).
5. Use the test fixtures under `tests/fixtures/` to understand expected input shapes.

> **Sources:** `go/cmd/rekipedia/main.go` · L6–L8 · [`main`](go/cmd/rekipedia/main.go#L6); `go/cmd/rekipedia/cmd/root.go` · L44–L48 · [`Execute`](go/cmd/rekipedia/cmd/root.go#L44); `go/internal/models/contracts.go` · L53–L94 · [`Symbol`](go/internal/models/contracts.go#L53) [`Relationship`](go/internal/models/contracts.go#L64) [`AnalysisResult`](go/internal/models/contracts.go#L82); `go/internal/extractor/extractor.go` · L11–L47 · [`Extractor`](go/internal/extractor/extractor.go#L11) [`NewRegistry`](go/internal/extractor/extractor.go#L24) [`(r *Registry).ExtractFile`](go/internal/extractor/extractor.go#L37); `go/internal/server/server.go` · L35–L375 · [`Server`](go/internal/server/server.go#L35) [`(s *Server).Start`](go/internal/server/server.go#L71) [`(s *Server).handleAPIAsk`](go/internal/server/server.go#L274); `go/internal/orchestrator/run_update.go` · L30–L179 · [`RunUpdate`](go/internal/orchestrator/run_update.go#L30); `go/internal/synthesis/page_builder.go` · L60–L133 · [`PageBuilder`](go/internal/synthesis/page_builder.go#L60); `go/internal/synthesis/planner.go` · L77–L116 · [`PlannerAgent`](go/internal/synthesis/planner.go#L77); `benchmarks/run_extraction.py` · L1–L112 · [`run_extraction_benchmark`](benchmarks/run_extraction.py#L19) [`run_performance_benchmark`](benchmarks/run_extraction.py#L77)