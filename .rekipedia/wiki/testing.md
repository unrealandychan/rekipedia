---
slug: testing
title: "Test Strategy Across Python and Go"
section: development
tags: [testing, development]
pin: false
importance: 78
created_at: 2026-05-26T09:15:07Z
rekipedia_version: 0.17.25
---

# Test Strategy Across Python and Go

## Overview

This repository uses a deliberately broad test strategy that spans both the Python implementation under `tests/` and the Go implementation under `go/`. The overall shape is easy to see from the analysis data: Python tests concentrate on application-facing behavior, fixture-driven extraction scenarios, and performance-adjacent checks, while Go tests are organized by package and cover command wiring, extraction logic, storage, orchestration, server endpoints, and analysis utilities. Representative evidence for this coverage appears in Python tests such as [`tests/test_benchmarks.py`](tests/test_benchmarks.py) and Go tests such as [`TestPythonFunctions`](go/internal/extractor/extractor_test.go#L62) and [`TestOpenAndClose`](go/internal/storage/store_test.go#L22).

The repository also contains explicit benchmark fixtures and benchmark-style harness code in `benchmarks/`, including [`run_extraction_benchmark`](benchmarks/run_extraction.py#L19) and [`run_performance_benchmark`](benchmarks/run_extraction.py#L77). These are not classic microbenchmarks, but they validate extraction behavior and performance characteristics in a controlled way.

At a high level, the test strategy appears to emphasize:

- **Unit tests** for pure logic and small, deterministic functions.
- **Integration tests** for file-system, database, HTTP, and CLI wiring.
- **Fixture-based tests** for language extraction, repo scanning, and benchmark-like scenarios.
- **Benchmark-adjacent checks** that ensure performance-sensitive workflows remain stable enough for day-to-day development.

> **Sources:** `tests/` · `go/internal/**` · `benchmarks/` · [`run_extraction_benchmark`](benchmarks/run_extraction.py#L19) · [`run_performance_benchmark`](benchmarks/run_extraction.py#L77)

## Test Directory Map

The repository is split across several test directories and file families, each validating a specific slice of behavior.

| Test directory / file family | Primary behaviors validated | Representative coverage |
|---|---|---|
| `tests/` | Python CLI, analysis, export, storage, server, RAG, refactor, and watcher behaviors | [`tests/test_server.py`](tests/test_server.py), [`tests/test_sqlite_store.py`](tests/test_sqlite_store.py), [`tests/test_python_extractor.py`](tests/test_python_extractor.py) |
| `tests/fixtures/mini-py-repo/` | Synthetic Python repo used to exercise scanning/extraction flows | fixture files only; exercised indirectly by tests |
| `tests/fixtures/mini-ts-repo/` | Synthetic TypeScript repo used to exercise scanning/extraction flows | fixture files only; exercised indirectly by tests |
| `go/internal/*/*_test.go` | Package-level Go unit and integration-style tests | [`TestPythonClass`](go/internal/extractor/extractor_test.go#L83), [`TestAPIPages`](go/internal/server/server_test.go#L42), [`TestRunLifecycle`](go/internal/storage/store_test.go#L37) |
| `go/cmd/rekipedia/*_test.go` | Cobra command registration, flags, and command behavior | [`TestRootCommandHasSubcommands`](go/cmd/rekipedia/cmd/root_test.go#L19), [`TestHookInstall`](go/cmd/rekipedia/cmd/hook_test.go#L20), [`TestRefactorCmdRegistered`](go/cmd/rekipedia/cmd/refactor_test.go#L15) |
| `benchmarks/` | Extraction accuracy and performance-adjacent checks | [`run_extraction_benchmark`](benchmarks/run_extraction.py#L19), [`run_performance_benchmark`](benchmarks/run_extraction.py#L77) |

The test layout suggests a “test close to code” philosophy in Go, with most packages owning their own `*_test.go` files. In Python, the tests are broader and cover the application boundary from the `tests/` directory rather than being colocated with implementation modules.

> **Sources:** `tests/` · `tests/fixtures/mini-py-repo/` · `tests/fixtures/mini-ts-repo/` · `go/cmd/rekipedia/cmd/root_test.go` · `go/internal/extractor/extractor_test.go` · `benchmarks/run_extraction.py`

## Unit Tests

### Python unit tests

The Python test suite includes many focused tests with names indicating small, isolated behavior checks: for example, `tests/test_config_loader.py`, `tests/test_domain.py`, `tests/test_doc_type.py`, and `tests/test_confidence.py`. These appear to validate pure logic, parsing, and local transformations rather than external systems.

Even when the implementation touches larger workflows, the Python tests often pin down small pieces of behavior by using synthetic inputs. For instance, extractor-oriented tests such as [`tests/test_python_extractor.py`](tests/test_python_extractor.py), [`tests/test_typescript_extractor.py`](tests/test_typescript_extractor.py), and [`tests/test_multilang_extractors.py`](tests/test_multilang_extractors.py) strongly suggest unit-level verification of language-specific extraction behavior.

### Go unit tests

Go’s unit tests are explicit and granular, often directly targeting one function or small group of functions. Representative examples include:

- [`TestDefaultLLMConfig`](go/internal/models/contracts_test.go#L5) for default configuration values.
- [`TestIsTransient`](go/internal/llm/client_test.go#L247) for retry/error classification.
- [`TestDetectLanguage`](go/internal/orchestrator/orchestrator_test.go#L221) for language inference.
- [`TestBuildMarkdownHeader`](go/internal/analysis/refactor_writer_test.go#L212) for markdown formatting.
- [`TestGetGodNodes_Empty`](go/internal/graph/graph_analysis_test.go#L9) for empty-input graph analysis.

This style is especially strong in modules that expose pure functions or simple structs, such as [`splitLanguages`](go/cmd/rekipedia/cmd/scan.go#L165), [`tokenizeSymbol`](go/cmd/rekipedia/cmd/search.go#L20), and [`sanitizeSlug`](go/internal/synthesis/planner.go#L206).

### What unit tests tend to cover

| Area | Example evidence | Typical assertion style |
|---|---|---|
| Configuration and defaults | [`TestLoadLLMConfigDefaults`](go/cmd/rekipedia/cmd/root_test.go#L104) | value normalization, fallback defaults |
| Parsing and tokenization | [`tokenizeSymbol`](go/cmd/rekipedia/cmd/search.go#L20), [`splitLanguages`](go/cmd/rekipedia/cmd/scan.go#L165) | string splitting, scoring, normalization |
| Formatting and serialization | [`TestBuildMarkdownHeader`](go/internal/analysis/refactor_writer_test.go#L212) | output contains expected sections and structure |
| Graph metrics | [`TestGetHubNodes`](go/internal/graph/hub_gap_test.go#L9) | ordering, counts, thresholds |
| Storage helpers | [`TestDefaultPath`](go/internal/storage/store_test.go#L29) | path resolution, zero-value behavior |

> **Sources:** `tests/test_config_loader.py` · `tests/test_domain.py` · `go/internal/models/contracts_test.go` · `go/internal/llm/client_test.go` · `go/internal/orchestrator/orchestrator_test.go` · `go/internal/analysis/refactor_writer_test.go` · `go/internal/graph/graph_analysis_test.go`

## Integration Tests

### Python integration tests

The Python suite includes end-to-end style tests around API behavior and repo processing. Files such as [`tests/test_api.py`](tests/test_api.py), [`tests/test_graph_api.py`](tests/test_graph_api.py), [`tests/test_notes_server.py`](tests/test_notes_server.py), and [`tests/test_serve_coverage.py`](tests/test_serve_coverage.py) indicate that the Python side validates how components work together rather than only individual functions.

There are also tests that exercise the sandbox and workflow-style paths, such as [`tests/test_sandbox_coverage.py`](tests/test_sandbox_coverage.py) and [`tests/test_workers.py`](tests/test_workers.py). These are best understood as integration tests because they validate multiple modules and execution contexts interacting together.

### Go integration tests

Go has many package-level integration tests using temporary directories, mock servers, and in-memory stores. Representative examples include:

- [`TestAPIPages`](go/internal/server/server_test.go#L42) and [`TestAPIPageFound`](go/internal/server/server_test.go#L72) for HTTP route behavior.
- [`TestCallSuccess`](go/internal/llm/client_test.go#L138) and [`TestStreamCall`](go/internal/llm/client_test.go#L180) for HTTP-backed LLM client flows.
- [`TestRunLifecycle`](go/internal/storage/store_test.go#L37) and [`TestUpsertTree`](go/internal/storage/store_test.go#L392) for SQLite-backed persistence.
- [`TestEnrichAllEndToEnd`](go/internal/analysis/refactor_enricher_test.go#L351) for a multi-step enrichment path with a mock LLM server.

These tests generally build the smallest realistic environment needed: temporary files, mocked HTTP servers, and ephemeral stores. That makes them integration tests without requiring a full application deployment.

### Integration test focus by package

| Package/file family | Behaviors validated | Representative tests |
|---|---|---|
| `go/internal/server/` | HTTP routing, templates, JSON endpoints, content rendering | [`TestHealth`](go/internal/server/server_test.go#L27), [`TestAPIGraph`](go/internal/server/server_test.go#L203) |
| `go/internal/storage/` | SQLite CRUD, migrations, alias methods, isolation across runs | [`TestSaveAndListSymbols`](go/internal/storage/store_test.go#L66), [`TestMultipleRunsIsolated`](go/internal/storage/store_test.go#L184) |
| `go/internal/llm/` | HTTP client request/response handling and retries | [`TestStreamCall`](go/internal/llm/client_test.go#L180), [`TestEmbedSuccess`](go/internal/llm/client_test.go#L221) |
| `go/internal/orchestrator/` | snapshotting, sharding, language detection, token estimates | [`TestSnapshotterBasic`](go/internal/orchestrator/orchestrator_test.go#L13), [`TestShardPlannerSplitsOnBudget`](go/internal/orchestrator/orchestrator_test.go#L157) |

> **Sources:** `tests/test_api.py` · `tests/test_graph_api.py` · `tests/test_notes_server.py` · `go/internal/server/server_test.go` · `go/internal/storage/store_test.go` · `go/internal/llm/client_test.go` · `go/internal/orchestrator/orchestrator_test.go` · `go/internal/analysis/refactor_enricher_test.go`

## Fixture-Based Tests

Fixture-based tests are one of the strongest signals in this repository.

### Python fixtures

The `tests/fixtures/mini-py-repo/` and `tests/fixtures/mini-ts-repo/` directories provide small, realistic repositories for scanner and extractor tests. They are intentionally minimal, but they cover a range of language shapes: Python modules such as `core.py`, `main.py`, and `utils.py`, and TypeScript modules such as `src/index.ts` and `src/greet.ts`.

### Go fixture-driven tests

Go tests also use synthetic files and repository layouts. The extractor suite in [`go/internal/extractor/extractor_test.go`](go/internal/extractor/extractor_test.go) is especially fixture-heavy, with tests like:

- [`TestPythonFunctions`](go/internal/extractor/extractor_test.go#L62)
- [`TestPythonClass`](go/internal/extractor/extractor_test.go#L83)
- [`TestTSInterface`](go/internal/extractor/extractor_test.go#L237)
- [`TestConfigPackageJSON`](go/internal/extractor/extractor_test.go#L296)
- [`TestConfigPyprojectToml`](go/internal/extractor/extractor_test.go#L334)
- [`TestConfigGoMod`](go/internal/extractor/extractor_test.go#L378)

Other fixture-oriented examples include the refactor detector tests that create synthetic repos via [`makeTestRepo`](go/cmd/rekipedia/cmd/refactor_test.go#L50) and the hook tests that construct a temporary git directory via [`makeGitDir`](go/cmd/rekipedia/cmd/hook_test.go#L10).

### Why fixtures matter here

These tests protect behavior that depends on file shape, language conventions, and directory traversal rules. They validate that the system can recognize:

- Python function/class boundaries
- TypeScript classes and interfaces
- Configuration files like `package.json`, `pyproject.toml`, `Dockerfile`, `go.mod`, and `Makefile`
- Hidden/system directories that should be skipped
- Small repo layouts used by scan/shard planning

> **Sources:** `tests/fixtures/mini-py-repo/` · `tests/fixtures/mini-ts-repo/` · [`TestPythonFunctions`](go/internal/extractor/extractor_test.go#L62) · [`TestTSInterface`](go/internal/extractor/extractor_test.go#L237) · [`TestConfigGoMod`](go/internal/extractor/extractor_test.go#L378) · [`makeTestRepo`](go/cmd/rekipedia/cmd/refactor_test.go#L50) · [`makeGitDir`](go/cmd/rekipedia/cmd/hook_test.go#L10)

## Benchmark-Adjacent Checks

The repository includes checks that are adjacent to benchmarking: they are not always canonical benchmarks in the Go `testing.B` sense, but they exercise performance-sensitive paths and record outcomes.

### Python benchmark harness

The clearest example is [`benchmarks/run_extraction.py`](benchmarks/run_extraction.py). It exposes:

- [`run_extraction_benchmark`](benchmarks/run_extraction.py#L19), which reports extraction accuracy against benchmark fixtures.
- [`run_performance_benchmark`](benchmarks/run_extraction.py#L77), which measures extraction speed using the Python fixture.

The benchmark fixtures themselves include the Python web app in [`benchmarks/fixtures/python_web_app/app.py`](benchmarks/fixtures/python_web_app/app.py) and the TypeScript React app in [`benchmarks/fixtures/typescript_react/App.tsx`](benchmarks/fixtures/typescript_react/App.tsx).

### Go performance-adjacent tests

The Go suite also includes performance-adjacent checks, especially around large or repeated operations:

- [`TestParallelPerf`](tests/test_parallel_perf.py) on the Python side suggests throughput-related validation.
- [`TestRagPerf`](tests/test_rag_perf.py) and [`TestSqlitePerf`](tests/test_sqlite_perf.py) indicate performance-oriented checks for RAG and storage flows.
- In Go, tests like [`TestSnapshotterSHA256Stable`](go/internal/orchestrator/orchestrator_test.go#L97) and [`TestVectorStore_SearchTopK`](go/internal/rag/rag_test.go#L100) indirectly protect algorithmic cost and stability.
- Sharding-related assertions such as [`TestShardPlannerSplitsOnBudget`](go/internal/orchestrator/orchestrator_test.go#L157) help keep token-budget logic predictable.

### How to interpret these checks

These are best seen as **benchmark-adjacent regression guards**. They do not prove absolute performance numbers, but they protect against accidental slowdowns, unstable hashing, unexpectedly expensive traversal, and overly large search/shard outputs.

> **Sources:** `benchmarks/run_extraction.py` · [`run_extraction_benchmark`](benchmarks/run_extraction.py#L19) · [`run_performance_benchmark`](benchmarks/run_extraction.py#L77) · `benchmarks/fixtures/python_web_app/app.py` · `benchmarks/fixtures/typescript_react/App.tsx` · `tests/test_parallel_perf.py` · `tests/test_rag_perf.py` · `tests/test_sqlite_perf.py` · [`TestSnapshotterSHA256Stable`](go/internal/orchestrator/orchestrator_test.go#L97) · [`TestVectorStore_SearchTopK`](go/internal/rag/rag_test.go#L100)

## Command Matrix

The repository exposes a small set of major test commands. The analysis data explicitly includes `pytest` and `go test ./... -v -count=1 -timeout 120s`, which are the main entry points for local validation.

| Command | Scope | Typical use |
|---|---|---|
| `pytest` | Python tests under `tests/` | run the Python suite locally |
| `pytest tests/ -v --timeout=60 \` | Python tests with verbose output and timeout control | narrower local runs or scripted invocation |
| `go test ./... -v -count=1 -timeout 120s` | all Go packages under `go/` | full Go validation, avoiding cached results |
| `pip install pytest` | test dependency setup | prepare Python test environment |

A few practical observations follow from the repository shape:

- `pytest` is the default Python command and likely covers the broad suite in `tests/`.
- `go test ./...` is the canonical Go command and traverses command packages, internal packages, and package-local tests.
- The `-count=1` and `-timeout 120s` flags on Go imply a preference for deterministic, uncached, and bounded test runs.

> **Sources:** `test_commands` from analysis data · `tests/` · `go/`

## Summary

The test strategy is intentionally multi-layered:

1. **Unit tests** protect small logic blocks and parsing utilities.
2. **Integration tests** validate end-to-end behavior across storage, HTTP, LLM, and orchestration.
3. **Fixture-based tests** ensure the system handles realistic source layouts and language-specific structures.
4. **Benchmark-adjacent checks** watch for regressions in extraction speed and algorithmic stability.

The strongest pattern across both Python and Go is that tests are organized around real usage shapes: repositories, temporary files, HTTP servers, and synthetic fixtures. That makes the suite well suited to the project’s core problem domain—analyzing codebases and generating structured wiki output—while keeping most checks deterministic and locally runnable.

> **Sources:** `tests/` · `go/internal/**` · `go/cmd/rekipedia/**` · `benchmarks/run_extraction.py`