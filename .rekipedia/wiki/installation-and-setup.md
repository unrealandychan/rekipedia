---
slug: installation-and-setup
title: "Getting Started: Build and Run"
section: getting-started
tags: [getting-started, configuration]
pin: false
importance: 68
created_at: 2026-05-26T09:13:14Z
rekipedia_version: 0.17.25
---

# Getting Started: Build and Run

This page summarizes how to build and run the project across its supported runtimes, with practical setup notes for Python, Go, and the optional web/tooling paths that are visible in the repository. It focuses on the developer-facing commands and environment assumptions that can be inferred from the manifests and entry points, rather than repeating the product architecture.

## Overview

The repository is clearly multi-runtime:

- **Python** is the primary application surface under [`src/rekipedia`](src/rekipedia/__init__.py), with a console entry point at [`src/rekipedia/__main__.py`](src/rekipedia/__main__.py).
- **Go** provides a parallel implementation and CLI under [`go/cmd/rekipedia/main.go`](go/cmd/rekipedia/main.go), with a full command tree rooted in [`go/cmd/rekipedia/cmd/root.go`](go/cmd/rekipedia/cmd/root.go).
- **Web/server tooling** is available in both runtimes, with the Python server in [`src/rekipedia/server/app.py`](src/rekipedia/server/app.py) and the Go server in [`go/internal/server/server.go`](go/internal/server/server.go).
- **Frontend/tooling** is supported through Node-based build tasks, as indicated by [`package.json`](package.json) and the documented build command `npm run build  # tsc`.

The repository also includes packaging metadata for Python (`pyproject.toml`, `uv.lock`), Go (`go/go.mod`, `go/go.sum`), and containerization (`Dockerfile.sandbox`, `go/Dockerfile`), which suggests that the project is intended to be runnable either from source or via packaged/containerized workflows.

> **Sources:** `src/rekipedia/__main__.py` · `src/rekipedia/__init__.py` · `go/cmd/rekipedia/main.go` · `go/cmd/rekipedia/cmd/root.go` · `src/rekipedia/server/app.py` · `go/internal/server/server.go` · `package.json` · `pyproject.toml` · `uv.lock` · `go/go.mod` · `go/go.sum`

## Supported Runtime Paths

### Python runtime

The Python application appears to be structured as an installable package in `src/rekipedia`, with a module entry point via [`src/rekipedia/__main__.py`](src/rekipedia/__main__.py). In practice, that means the project can be run as a Python package after dependency installation, and the repo’s use of `pyproject.toml` plus `uv.lock` indicates the expected packaging workflow is lockfile-driven.

The Python runtime likely assumes:

- a modern Python interpreter compatible with the package metadata in `pyproject.toml`
- local dependency resolution via `uv` or another PEP 517 frontend
- any runtime environment variables specified in `.env.sample`
- a repository checkout rooted at the project directory so relative file paths, templates, and storage locations resolve correctly

The presence of server, CLI, orchestrator, and storage modules under `src/rekipedia` suggests the Python package can support both CLI-style and web-style execution depending on the invoked command or module entry point.

### Go runtime

The Go runtime is anchored at [`go/cmd/rekipedia/main.go`](go/cmd/rekipedia/main.go), which delegates to the Cobra-style command tree assembled in [`go/cmd/rekipedia/cmd/root.go`](go/cmd/rekipedia/cmd/root.go). That command tree includes operational subcommands such as `scan`, `serve`, `ask`, `update`, and `watch`, which indicates a fully functional CLI/server runtime.

The Go build is constrained by the module definition in `go/go.mod` and is intended to be reproducible with standard Go tooling. The provided build command explicitly disables CGO:

```bash
CGO_ENABLED=0 go build -ldflags "-s -w" -o /tmp/reki ./cmd/rekipedia
```

That signals a statically linked binary target and a preference for portable builds in CI or release pipelines.

### Web/tooling runtime

There are two web-facing entry points in the repository:

- Python server code under [`src/rekipedia/server/app.py`](src/rekipedia/server/app.py)
- Go server code under [`go/internal/server/server.go`](go/internal/server/server.go)

On the tooling side, the root `package.json` and build command `npm run build  # tsc` imply a TypeScript compilation step, most likely for editor, integration, or web assets that accompany the main app. The repo also contains linting and formatting configuration files (`.eslintrc.json`, `.prettierrc.json`, `.golangci.yml`, `.ruff_cache/` artifacts), which reinforces that web/tooling setup is optional but supported.

> **Sources:** `pyproject.toml` · `uv.lock` · `src/rekipedia/__main__.py` · `src/rekipedia/server/app.py` · `go/cmd/rekipedia/main.go` · `go/cmd/rekipedia/cmd/root.go` · `go/go.mod` · `package.json` · `.env.sample`

## Build and Test Commands

The table below consolidates the commands explicitly provided in the analysis data, along with the setup implications that can be inferred from them.

| Purpose | Command | Notes |
|---|---|---|
| Build Python package | `uv build` | Uses the `pyproject.toml`/`uv.lock` packaging flow; appropriate when publishing wheels/sdists or validating package metadata. |
| Build Go binary | `CGO_ENABLED=0 go build -ldflags "-s -w" -o /tmp/reki ./cmd/rekipedia` | Produces a stripped, static-ish binary; run from the `go/` directory or adjust the module path accordingly. |
| Build Python package with Hatch | `hatch build` | Alternate Python packaging path; appears twice in the provided build list, suggesting it is used in more than one pipeline or environment. |
| Build container image | `docker build .` | Assumes a Dockerfile at the repository root or build context sufficient to resolve the correct Dockerfile; useful for sandboxed or reproducible runs. |
| Build TypeScript tooling | `npm run build  # tsc` | Compiles TypeScript via the `package.json` scripts; requires Node.js and the repo’s JS dependencies to be installed. |
| Run test suite for the active runtime | `pytest` / `go test ./...` / `npm test` | Not provided verbatim in `build_commands`, but test files and CI workflows indicate the project is validated through Python, Go, and Node-compatible pipelines. Use the runtime-specific test command from the relevant directory. |

A few practical points from the command list:

- `uv build` and `hatch build` are both Python packaging commands, so the repo supports at least two packaging frontends.
- The Go build command is intentionally optimized for distributable binaries.
- The Docker build is likely intended to validate sandbox or release packaging rather than local developer loops.
- The TypeScript build is optional unless you are working on tooling or a frontend-adjacent feature.

> **Sources:** `Makefile` · `pyproject.toml` · `uv.lock` · `go/go.mod` · `package.json` · `Dockerfile.sandbox` · `go/Dockerfile`

## Python Setup

### Install dependencies

The repository’s Python packaging is driven by `pyproject.toml` and `uv.lock`, so the most direct setup is:

```bash
uv sync
```

If you prefer Hatch-based workflows, the presence of `hatch build` in the build commands indicates Hatch is also supported for packaging tasks, although the exact project-specific environment setup is not visible from the static analysis.

### Build the package

To validate the Python package and build artifacts:

```bash
uv build
```

or:

```bash
hatch build
```

These commands should be run from the repository root, where `pyproject.toml` and `uv.lock` are located.

### Run the package

The most direct runtime entry point is the module launcher:

```bash
python -m rekipedia
```

This maps to [`src/rekipedia/__main__.py`](src/rekipedia/__main__.py), which is the canonical Python execution target inferred from the repository layout. If the project exposes CLI behavior through `src/rekipedia/cli`, then the module runner is likely the simplest way to invoke it locally.

### Python environment assumptions

Based on the repository structure, expect the following:

- Python virtual environment activation is recommended
- dependencies are resolved from the lockfile
- runtime configuration may depend on `.env.sample`
- local paths for storage/templates are likely relative to the project checkout

If you are running the server or any command that touches LLM, storage, or indexing features, be prepared to set environment variables before launch.

> **Sources:** `pyproject.toml` · `uv.lock` · `src/rekipedia/__main__.py` · `.env.sample`

## Go Setup

### Install prerequisites

The Go runtime is defined by [`go/go.mod`](go/go.mod), so you need a compatible Go toolchain before building or running the binary. The repository structure suggests the Go app is self-contained inside the `go/` subdirectory.

### Build the CLI binary

From the `go/` directory:

```bash
CGO_ENABLED=0 go build -ldflags "-s -w" -o /tmp/reki ./cmd/rekipedia
```

This matches the provided build command exactly and produces a release-style binary. If you want an iterative local build, you can omit the stripping flags, but that would go beyond what is evidenced in the repository.

### Run the CLI

The main entry point is [`go/cmd/rekipedia/main.go`](go/cmd/rekipedia/main.go), which calls into [`go/cmd/rekipedia/cmd/root.go`](go/cmd/rekipedia/cmd/root.go). Typical usage is therefore:

```bash
go run ./cmd/rekipedia --help
```

or after building:

```bash
./reki --help
```

The command tree includes operational commands for scanning, serving, diffing, asking, updating, embedding, and watching. That means Go is not just a build target—it is also a usable end-user CLI runtime.

### Go environment assumptions

Inferred prerequisites include:

- a working Go toolchain
- execution from within `go/`
- optional environment variables for LLM/server/storage behavior
- filesystem access for local repositories and generated output

> **Sources:** `go/go.mod` · `go/cmd/rekipedia/main.go` · `go/cmd/rekipedia/cmd/root.go`

## Optional Web and Tooling Setup

### Server runtime

The repo supports server-style usage in both runtimes. The Go server lives in [`go/internal/server/server.go`](go/internal/server/server.go), while the Python server implementation is in [`src/rekipedia/server/app.py`](src/rekipedia/server/app.py). The exact launch command depends on the chosen runtime, but the codebase clearly expects a local HTTP service capable of rendering wiki pages and handling API requests.

A practical local workflow is:

1. build or install the chosen runtime
2. configure environment variables from `.env.sample`
3. start the server entry point for that runtime
4. open the local web UI in a browser

### TypeScript / Node tooling

The root `package.json` indicates Node-based tooling support. The documented build step is:

```bash
npm run build
```

with the analysis note indicating this runs TypeScript compilation (`tsc`). This is likely optional for application runtime, but relevant if you are working on editor tooling, client assets, or any package scripts defined in `package.json`.

### Containerized setup

The repository includes both [`Dockerfile.sandbox`](Dockerfile.sandbox) and [`go/Dockerfile`](go/Dockerfile). This implies containerized development or deployment is supported, especially for environments where local Python/Go setup is undesirable. The direct command supplied in the analysis is:

```bash
docker build .
```

If you are using the sandbox image, expect the build context and Dockerfile selection to matter; the static analysis does not expose exact runtime arguments, so treat container setup as environment-specific.

> **Sources:** `src/rekipedia/server/app.py` · `go/internal/server/server.go` · `package.json` · `Dockerfile.sandbox` · `go/Dockerfile`

## Recommended Local Workflow

A sensible order of operations for a fresh checkout is:

1. Choose a runtime: Python or Go.
2. Install dependencies for that runtime.
3. Run the relevant build command.
4. Execute the runtime entry point.
5. Optionally enable the web server or Node tooling if your task needs it.

For most contributors:

- **Python-first** if you are working in `src/rekipedia`
- **Go-first** if you are validating the CLI under `go/cmd/rekipedia`
- **Node/tooling** only when editing TypeScript or JS-related support files

This repository is set up to support all three without forcing them into a single monolithic build path.

> **Sources:** `src/rekipedia/__main__.py` · `go/cmd/rekipedia/main.go` · `package.json` · `.env.sample`