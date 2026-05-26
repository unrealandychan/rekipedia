# Changelog

All notable changes to rekipedia are documented here.

## [0.17.21] - 2026-05-26

### Added
- `reki hotspots` command — identifies hub nodes (most connected) and bridge nodes (cross-boundary connectors) in the symbol graph. Supports `--top N` and `--format table|json|md`. Closes #165.
- `reki scan --hotspots` — auto-generates `ARCHITECTURE.md` after scan completes and writes it to `.rekipedia/wiki/`.
