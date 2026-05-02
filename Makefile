# rekipedia — developer Makefile
# All primary tasks go through make. Use `make help` to list targets.

PYTHON     ?= python3
UV         ?= uv
NPM        ?= npm

PYPI_TOKEN ?=
NPM_TOKEN  ?=

.DEFAULT_GOAL := help

# ─────────────────────────────────────────────
# Help
# ─────────────────────────────────────────────
.PHONY: help
help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ─────────────────────────────────────────────
# Environment
# ─────────────────────────────────────────────
.PHONY: install
install: ## Install runtime deps (uv sync)
	$(UV) sync

.PHONY: dev
dev: ## Install runtime + dev deps
	$(UV) sync --extra dev

# ─────────────────────────────────────────────
# Quality
# ─────────────────────────────────────────────
.PHONY: lint
lint: ## Run linters and write report
	./scripts/lint-and-report.sh

.PHONY: test
test: dev ## Run the test suite (pytest)
	$(UV) run pytest

.PHONY: test-cov
test-cov: dev ## Run tests with coverage report
	$(UV) run pytest --cov=src/rekipedia --cov-report=term-missing

# ─────────────────────────────────────────────
# Build
# ─────────────────────────────────────────────
.PHONY: build
build: ## Build Python wheel + sdist and npm tarball
	$(UV) build
	$(NPM) pack

.PHONY: docker-build
docker-build: ## Build the sandbox Docker image
	docker build -f Dockerfile.sandbox -t rekipedia-sandbox:local .

# ─────────────────────────────────────────────
# Release
# ─────────────────────────────────────────────
.PHONY: release-pypi
release-pypi: build ## Publish to PyPI (requires PYPI_TOKEN)
	@test -n "$(PYPI_TOKEN)" || (echo "PYPI_TOKEN is not set" && exit 1)
	UV_PUBLISH_TOKEN=$(PYPI_TOKEN) $(UV) publish

.PHONY: release-npm
release-npm: ## Publish to npm (requires NPM_TOKEN)
	@test -n "$(NPM_TOKEN)" || (echo "NPM_TOKEN is not set" && exit 1)
	$(NPM) config set //registry.npmjs.org/:_authToken $(NPM_TOKEN)
	$(NPM) publish --access public

.PHONY: release
release: release-pypi release-npm ## Release to both PyPI and npm

# ─────────────────────────────────────────────
# Full release pipeline
# ─────────────────────────────────────────────
# Usage:
#   make release-all PYPI_TOKEN=pypi-xxx NPM_TOKEN=npm_xxx
#   make release-all PYPI_TOKEN=pypi-xxx NPM_TOKEN=npm_xxx VERSION=0.2.0
VERSION ?=

.PHONY: release-all
release-all: ## Full release: build → git tag → push → PyPI → npm  (needs PYPI_TOKEN, NPM_TOKEN; optional VERSION=x.y.z)
	@test -n "$(PYPI_TOKEN)" || (echo "❌  PYPI_TOKEN not set. Usage: make release-all PYPI_TOKEN=pypi-xxx NPM_TOKEN=npm_xxx" && exit 1)
	@test -n "$(NPM_TOKEN)"  || (echo "❌  NPM_TOKEN not set.  Usage: make release-all PYPI_TOKEN=pypi-xxx NPM_TOKEN=npm_xxx" && exit 1)
	@echo "▶  1/5  version bump"
	@if [ -n "$(VERSION)" ]; then \
	  sed -i.bak 's/^version = ".*"/version = "$(VERSION)"/' pyproject.toml && rm -f pyproject.toml.bak; \
	  node -e "const fs=require('fs'),p=JSON.parse(fs.readFileSync('package.json'));p.version='$(VERSION)';fs.writeFileSync('package.json',JSON.stringify(p,null,2)+'\n')"; \
	  echo "     bumped to v$(VERSION)"; \
	else \
	  echo "     VERSION not set — keeping $$(grep '^version' pyproject.toml | head -1 | sed 's/version = //;s/\"//g')"; \
	fi
	@echo "▶  2/5  build"
	$(UV) build
	$(NPM) pack
	@echo "▶  3/5  git commit + tag + push"
	@RELEASE_VER=$$(grep '^version' pyproject.toml | head -1 | sed 's/version = "//;s/"//'); \
	git add pyproject.toml package.json uv.lock 2>/dev/null || true; \
	git diff --cached --quiet || git commit -m "chore: release v$$RELEASE_VER"; \
	git tag -f "v$$RELEASE_VER"; \
	git push origin main --tags; \
	echo "     pushed v$$RELEASE_VER"
	@echo "▶  4/5  publish to PyPI"
	UV_PUBLISH_TOKEN=$(PYPI_TOKEN) $(UV) publish
	@echo "▶  5/5  publish to npm"
	$(NPM) config set //registry.npmjs.org/:_authToken $(NPM_TOKEN)
	$(NPM) publish --access public
	@echo "✅  Done! rekipedia released."

# ─────────────────────────────────────────────
# Housekeeping
# ─────────────────────────────────────────────
.PHONY: clean
clean: ## Remove build artefacts
	rm -rf dist/ *.tgz .coverage htmlcov/ .pytest_cache/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
