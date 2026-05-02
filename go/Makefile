# rekipedia Go rewrite — Makefile
# Usage: make [target]

BINARY     := rekipedia
MODULE     := github.com/unrealandychan/rekipedia
CMD        := ./cmd/rekipedia
BUILD_DIR  := ../dist/go
VERSION    ?= $(shell git describe --tags --always --dirty 2>/dev/null || echo "dev")
COMMIT     ?= $(shell git rev-parse --short HEAD 2>/dev/null || echo "none")
DATE       ?= $(shell date -u +%Y-%m-%dT%H:%M:%SZ)
LDFLAGS    := -s -w \
              -X $(MODULE)/cmd/rekipedia/cmd.version=$(VERSION) \
              -X $(MODULE)/cmd/rekipedia/cmd.commit=$(COMMIT) \
              -X $(MODULE)/cmd/rekipedia/cmd.date=$(DATE)

.PHONY: all build test lint clean check smoke release-dry

## all: build + test
all: build test

## build: compile binary for current platform
build:
	@echo "→ Building $(BINARY) $(VERSION)..."
	@mkdir -p $(BUILD_DIR)
	CGO_ENABLED=1 go build -ldflags "$(LDFLAGS)" -o $(BUILD_DIR)/$(BINARY) $(CMD)
	@echo "✓ Binary: $(BUILD_DIR)/$(BINARY)"

## test: run all unit tests
test:
	@echo "→ Running tests..."
	go test ./... -v -count=1 -timeout 120s

## test-short: skip tests requiring network/CGO
test-short:
	go test ./... -short -count=1

## lint: run staticcheck + go vet
lint:
	@echo "→ Linting..."
	go vet ./...
	@which staticcheck > /dev/null 2>&1 && staticcheck ./... || echo "(staticcheck not installed — skipped)"

## smoke: build + quick CLI smoke test
smoke: build
	@echo "→ Smoke test..."
	$(BUILD_DIR)/$(BINARY) --version
	$(BUILD_DIR)/$(BINARY) --help
	$(BUILD_DIR)/$(BINARY) scan --help
	$(BUILD_DIR)/$(BINARY) ask --help
	$(BUILD_DIR)/$(BINARY) serve --help
	@echo "✓ Smoke tests passed"

## check: vet + test + smoke (pre-push verification)
check: lint test smoke
	@echo "✓ All checks passed"

## release-dry: goreleaser dry run (requires goreleaser installed)
release-dry:
	goreleaser release --snapshot --clean

## release-dry-run: alias for release-dry
release-dry-run: release-dry

## clean: remove build artifacts
clean:
	rm -rf $(BUILD_DIR)
	go clean ./...
