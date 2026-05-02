# Release Notes

## v0.9.1

### Bug Fixes
- **Recursive scanning** — Fixed `rekipedia scan .` reporting 0 files found (root directory was incorrectly skipped)
- **RAG search in `ask`** — `ask` command now uses vector store for semantic search when available; gracefully falls back to wiki-only if not embedded

### Improvements
- **Colour output** — All CLI commands now use colour: cyan headers, green success, yellow warnings, red errors
- **Progress bar** — Live progress bar during shard extraction
- **Command banners** — All commands show `rekipedia <cmd>  ▸  /path/to/repo` on startup

### Python/Go Parity
- Snapshotter ignore dirs now match Python (added `.mypy_cache`, `.pytest_cache`, `.tox`, `htmlcov`)
- `embed` command now supports `--api-key` and `--base-url` flags (matching Python)
- Context assembly order now matches Python: RAG chunks > wiki pages > symbols > history



### New Features
- **Go AST extractor** — Native Go source code analysis using `go/ast` stdlib (zero external dependencies)
- **`--languages` flag** — Filter scan/update by language (e.g. `--languages go,python,typescript`)
- **Flag parity** — All commands (`ask`, `serve`, `update`, `embed`) now have full flag parity with Python CLI
- **`--host` flag for `serve`** — Configure host:port instead of hardcoded `:7070`

### Improvements
- GoReleaser config with multi-platform builds (darwin/linux/windows × amd64/arm64)
- Homebrew tap auto-update on release

### Bug Fixes
- Fixed hardcoded host in `serve` command
- Added missing `--output-dir` and `--no-docker` flags across commands
