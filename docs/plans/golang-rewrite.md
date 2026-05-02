# rekipedia Go Rewrite — Implementation Plan

> **Branch:** `feat/golang-rewrite`
> **Go module:** `github.com/unrealandychan/rekipedia`
> **Root:** `go/` directory inside the repo

**Goal:** Full Go rewrite of rekipedia producing a single statically-linked binary, feature-parity with Python v0.7.3, with goreleaser-based distribution.

**Architecture:**
```
go/
├── cmd/rekipedia/        # main.go — cobra root command
├── internal/
│   ├── models/            # Data contracts (Go structs = Python pydantic models)
│   ├── config/            # Config YAML loading + env var overrides
│   ├── storage/           # SQLite store (mattn/go-sqlite3)
│   ├── extractor/         # Python + TypeScript + config file extractors
│   ├── llm/               # LLM client (OpenAI-compatible REST via go-openai)
│   ├── synthesis/         # PlannerAgent + PageBuilder + DiagramBuilder
│   ├── orchestrator/      # run_digest, run_update, run_ask, sharding, snapshotter
│   ├── rag/               # Embedder + FAISS-lite (pure-Go cosine similarity)
│   ├── exporter/          # JSON + Markdown + ZIP exporters
│   ├── server/            # HTTP server (chi router, SSE streaming)
│   └── sandbox/           # In-process runner (no Docker required by default)
├── pkg/fsutil/            # File walking, SHA256, ignore patterns
├── .goreleaser.yaml       # Multi-platform release config
└── Makefile               # build, test, release targets
```

**Tech Stack:**
- CLI: `github.com/spf13/cobra`
- SQLite: `github.com/mattn/go-sqlite3` (CGO, statically linked via `-tags sqlite_omit_load_extension`)
- LLM: `github.com/sashabaranov/go-openai` (any OpenAI-compatible endpoint)
- HTTP server: `github.com/go-chi/chi/v5`
- YAML: `gopkg.in/yaml.v3`
- Progress: `github.com/schollz/progressbar/v3`
- Color output: `github.com/fatih/color`
- UUID: `github.com/google/uuid`
- Concurrency: `golang.org/x/sync/errgroup`
- Distribution: goreleaser + GitHub Actions

**Key design decisions vs Python:**
- No FAISS (CGO complexity, platform issues) → pure-Go vector store with cosine similarity
- No litellm → use go-openai with custom BaseURL for any OpenAI-compatible provider
- No Docker sandbox → in-process extractors only (simpler, faster, distributable binary)
- No FastAPI → chi HTTP server with SSE for streaming Q&A

---

## Phase 1 — Foundation (Tasks 1–5)

### Task 1: models/contracts.go — Data structs

**Objective:** Define all shared data types that mirror Python's pydantic models.

**Files:**
- Create: `go/internal/models/contracts.go`
- Create: `go/internal/models/contracts_test.go`

**Implementation:**

```go
// go/internal/models/contracts.go
package models

// LLMConfig mirrors Python LLMConfig pydantic model.
type LLMConfig struct {
    Model         string  `yaml:"model"`
    APIKey        string  `yaml:"api_key"`
    BaseURL       string  `yaml:"base_url"`
    Temperature   float64 `yaml:"temperature"`
    EmbedModel    string  `yaml:"embed_model"`
    EmbedProvider string  `yaml:"embed_provider"`
}

func DefaultLLMConfig() LLMConfig {
    return LLMConfig{
        Model:       "ollama/llama4",
        Temperature: 0.2,
    }
}

type SymbolKind string
const (
    SymbolFunction  SymbolKind = "function"
    SymbolClass     SymbolKind = "class"
    SymbolType      SymbolKind = "type"
    SymbolVariable  SymbolKind = "variable"
    SymbolInterface SymbolKind = "interface"
    SymbolEnum      SymbolKind = "enum"
    SymbolModule    SymbolKind = "module"
    SymbolOther     SymbolKind = "other"
)

type RelKind string
const (
    RelImport    RelKind = "import"
    RelCall      RelKind = "call"
    RelInherits  RelKind = "inherits"
    RelUses      RelKind = "uses"
    RelReExports RelKind = "re-exports"
)

type Symbol struct {
    Name      string     `json:"name"`
    Kind      SymbolKind `json:"kind"`
    File      string     `json:"file"`
    LineStart int        `json:"line_start,omitempty"`
    LineEnd   int        `json:"line_end,omitempty"`
    Signature string     `json:"signature,omitempty"`
    Docstring string     `json:"docstring,omitempty"`
}

type Relationship struct {
    From string  `json:"from"`
    To   string  `json:"to"`
    Kind RelKind `json:"kind"`
    File string  `json:"file,omitempty"`
}

type AnalysisResult struct {
    ShardID       string         `json:"shard_id"`
    FilesSeen     []string       `json:"files_seen"`
    EntryPoints   []string       `json:"entry_points"`
    Symbols       []Symbol       `json:"symbols"`
    Relationships []Relationship `json:"relationships"`
    BuildCommands []string       `json:"build_commands"`
    TestCommands  []string       `json:"test_commands"`
    Risks         []string       `json:"risks"`
    Unknowns      []string       `json:"unknowns"`
    Evidence      map[string]string `json:"evidence"`
}

type Shard struct {
    ShardID string   `json:"shard_id"`
    Files   []string `json:"files"`
}

type FileManifest struct {
    Path      string `json:"path"`
    SHA256    string `json:"sha256"`
    SizeBytes int64  `json:"size_bytes"`
    Language  string `json:"language,omitempty"`
}

// WikiPage spec from PlannerAgent
type WikiPageSpec struct {
    Slug         string   `json:"slug"`
    Title        string   `json:"title"`
    Section      string   `json:"section"`
    Priority     int      `json:"priority"`
    Importance   int      `json:"importance"`
    Focus        string   `json:"focus"`
    RequiredData []string `json:"required_data"`
    Tags         []string `json:"tags"`
}

type WikiSection struct {
    ID    string   `json:"id"`
    Title string   `json:"title"`
    Pages []string `json:"pages"`
}

type WikiPlan struct {
    Sections  []WikiSection  `json:"sections"`
    Pages     []WikiPageSpec `json:"pages"`
    NavOrder  []string       `json:"nav_order"`
    IndexSlug string         `json:"index_slug"`
}
```

**Test:**
```go
// go/internal/models/contracts_test.go
package models

import "testing"

func TestDefaultLLMConfig(t *testing.T) {
    cfg := DefaultLLMConfig()
    if cfg.Model != "ollama/llama4" {
        t.Errorf("expected model ollama/llama4, got %s", cfg.Model)
    }
    if cfg.Temperature != 0.2 {
        t.Errorf("expected temperature 0.2, got %f", cfg.Temperature)
    }
}

func TestAnalysisResultDefaults(t *testing.T) {
    r := AnalysisResult{ShardID: "test"}
    if r.Symbols != nil {
        t.Error("expected nil Symbols slice")
    }
}
```

**Verify:** `cd go && go test ./internal/models/... -v`

---

### Task 2: config/loader.go — YAML config + env overrides

**Objective:** Load `.rekipedia/config.yml`, apply env var overrides, same logic as Python `_load_config`.

**Files:**
- Create: `go/internal/config/loader.go`
- Create: `go/internal/config/loader_test.go`

**Implementation:**

```go
// go/internal/config/loader.go
package config

import (
    "os"
    "path/filepath"

    "gopkg.in/yaml.v3"
    "github.com/unrealandychan/rekipedia/internal/models"
)

type Config struct {
    Version  int              `yaml:"version"`
    Ignore   []string         `yaml:"ignore"`
    Languages []string        `yaml:"languages"`
    LLM      models.LLMConfig `yaml:"llm"`
}

func DefaultConfig() Config {
    return Config{
        Version:   1,
        Ignore:    []string{".git", "node_modules", "__pycache__", ".rekipedia"},
        Languages: []string{"python", "typescript"},
        LLM:       models.DefaultLLMConfig(),
    }
}

// Load reads config from repoRoot/.rekipedia/config.yml,
// falls back to defaults, then applies env var overrides.
func Load(repoRoot string) (Config, error) {
    cfg := DefaultConfig()
    path := filepath.Join(repoRoot, ".rekipedia", "config.yml")
    data, err := os.ReadFile(path)
    if err == nil {
        _ = yaml.Unmarshal(data, &cfg)
    }
    // Env var overrides (same as Python)
    if v := os.Getenv("REKIPEDIA_MODEL"); v != "" {
        cfg.LLM.Model = v
    }
    if v := os.Getenv("REKIPEDIA_API_KEY"); v != "" {
        cfg.LLM.APIKey = v
    }
    if v := os.Getenv("REKIPEDIA_BASE_URL"); v != "" {
        cfg.LLM.BaseURL = v
    }
    if v := os.Getenv("REKIPEDIA_EMBED_MODEL"); v != "" {
        cfg.LLM.EmbedModel = v
    }
    if v := os.Getenv("REKIPEDIA_EMBED_PROVIDER"); v != "" {
        cfg.LLM.EmbedProvider = v
    }
    return cfg, nil
}

// InitDir creates .rekipedia/ with a default config.yml.
func InitDir(repoRoot string) error {
    dir := filepath.Join(repoRoot, ".rekipedia")
    if err := os.MkdirAll(dir, 0755); err != nil {
        return err
    }
    cfgPath := filepath.Join(dir, "config.yml")
    if _, err := os.Stat(cfgPath); err == nil {
        return nil // already exists
    }
    cfg := DefaultConfig()
    data, err := yaml.Marshal(cfg)
    if err != nil {
        return err
    }
    return os.WriteFile(cfgPath, data, 0644)
}
```

**Verify:** `cd go && go test ./internal/config/... -v`

---

### Task 3: storage/store.go — SQLite persistence

**Objective:** Replicate SqliteStore in Go — runs, symbols, relationships, wiki pages, Q&A history.

**Files:**
- Create: `go/internal/storage/store.go`
- Create: `go/internal/storage/store_test.go`
- Create: `go/internal/storage/migrations.go`

**Key tables (same schema as Python):**
```sql
CREATE TABLE runs (
    run_id TEXT PRIMARY KEY, repo_path TEXT, started_at TEXT, finished_at TEXT,
    status TEXT, model TEXT, page_count INT
);
CREATE TABLE symbols (
    id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, name TEXT, kind TEXT,
    file TEXT, line_start INT, line_end INT, signature TEXT, docstring TEXT
);
CREATE TABLE relationships (
    id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT,
    from_sym TEXT, to_sym TEXT, kind TEXT, file TEXT
);
CREATE TABLE wiki_pages (
    id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, slug TEXT UNIQUE,
    title TEXT, section TEXT, content TEXT, priority INT, importance INT,
    generated_at TEXT
);
CREATE TABLE qa_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, question TEXT,
    answer TEXT, asked_at TEXT
);
CREATE TABLE file_manifest (
    path TEXT PRIMARY KEY, sha256 TEXT, size_bytes INT, language TEXT,
    last_seen TEXT
);
```

**Verify:** `cd go && go test ./internal/storage/... -v`

---

### Task 4: pkg/fsutil/walk.go — File walking + SHA256

**Objective:** Walk repo, skip ignored dirs, compute SHA256, detect language.

**Files:**
- Create: `go/pkg/fsutil/walk.go`
- Create: `go/pkg/fsutil/walk_test.go`

**Implementation:**
```go
// go/pkg/fsutil/walk.go
package fsutil

import (
    "crypto/sha256"
    "encoding/hex"
    "io"
    "os"
    "path/filepath"
    "strings"
)

var DefaultIgnore = []string{
    ".git", "node_modules", "__pycache__", ".rekipedia",
    "dist", "build", ".venv", "venv", ".tox",
}

var CodeExts = map[string]string{
    ".py": "python", ".ts": "typescript", ".tsx": "typescript",
    ".js": "javascript", ".jsx": "javascript", ".go": "go",
    ".rs": "rust", ".java": "java", ".rb": "ruby", ".php": "php",
    ".c": "c", ".cpp": "c++", ".h": "c",
}

var DocExts = map[string]string{
    ".md": "markdown", ".txt": "text", ".rst": "rst",
    ".yaml": "yaml", ".yml": "yaml", ".toml": "toml", ".json": "json",
}

type FileInfo struct {
    Path     string
    SHA256   string
    Size     int64
    Language string
    IsCode   bool
    IsDoc    bool
}

func WalkRepo(root string, ignore []string) ([]FileInfo, error) {
    skipDirs := make(map[string]bool)
    for _, d := range append(DefaultIgnore, ignore...) {
        skipDirs[d] = true
    }
    var files []FileInfo
    err := filepath.WalkDir(root, func(path string, d os.DirEntry, err error) error {
        if err != nil { return nil }
        rel, _ := filepath.Rel(root, path)
        parts := strings.Split(rel, string(os.PathSeparator))
        for _, p := range parts {
            if skipDirs[p] { return filepath.SkipDir }
        }
        if d.IsDir() { return nil }
        ext := strings.ToLower(filepath.Ext(path))
        lang, isCode := CodeExts[ext]
        _, isDoc := DocExts[ext]
        if !isCode && !isDoc { return nil }
        info, _ := d.Info()
        hash, _ := SHA256File(path)
        files = append(files, FileInfo{
            Path: rel, SHA256: hash,
            Size: info.Size(), Language: lang,
            IsCode: isCode, IsDoc: isDoc,
        })
        return nil
    })
    return files, err
}

func SHA256File(path string) (string, error) {
    f, err := os.Open(path)
    if err != nil { return "", err }
    defer f.Close()
    h := sha256.New()
    if _, err := io.Copy(h, f); err != nil { return "", err }
    return hex.EncodeToString(h.Sum(nil)), nil
}
```

**Verify:** `cd go && go test ./pkg/fsutil/... -v`

---

### Task 5: cmd/rekipedia/main.go — Cobra root

**Objective:** Wire up the cobra root command with all subcommands registered.

**Files:**
- Create: `go/cmd/rekipedia/main.go`
- Create: `go/cmd/rekipedia/root.go`

```go
// go/cmd/rekipedia/main.go
package main

import "github.com/unrealandychan/rekipedia/cmd/rekipedia/cmd"

func main() { cmd.Execute() }
```

```go
// go/cmd/rekipedia/cmd/root.go
package cmd

import (
    "github.com/spf13/cobra"
    "os"
)

var rootCmd = &cobra.Command{
    Use:   "rekipedia",
    Short: "Your AI tech lead — always available, always up to date.",
}

func Execute() {
    if err := rootCmd.Execute(); err != nil {
        os.Exit(1)
    }
}

func init() {
    rootCmd.AddCommand(initCmd, scanCmd, updateCmd, askCmd, serveCmd, embedCmd, exportCmd)
}
```

**Verify:** `cd go && go build ./cmd/rekipedia && ./rekipedia --help`

---

## Phase 2 — Extractors (Tasks 6–8)

### Task 6: extractor/python.go — Python AST extraction

**Objective:** Parse Python files for symbols (functions, classes, imports) without Docker.

**Strategy:** Regex-based extraction (covers 90% of cases without needing a full AST parser in Go). Same output as Python's `python_extractor.py`.

**Files:**
- Create: `go/internal/extractor/python.go`
- Create: `go/internal/extractor/python_test.go`

**Key patterns to extract:**
```
def func_name(   → Symbol{kind: function}
async def        → Symbol{kind: function}
class ClassName( → Symbol{kind: class}
import X         → Relationship{kind: import}
from X import Y  → Relationship{kind: import}
```

**Verify:** `cd go && go test ./internal/extractor/... -v`

---

### Task 7: extractor/typescript.go — TypeScript/JS extraction

**Objective:** Parse TS/JS files for symbols and imports. Same patterns as Python's `typescript_extractor.py`.

**Key patterns:**
```
export function / export const / export class
export default
import ... from '...'
require('...')
```

**Verify:** `cd go && go test ./internal/extractor/... -v`

---

### Task 8: extractor/config.go — Config/build file extraction

**Objective:** Extract build commands, test commands, entry points, dependencies from config files (package.json, pyproject.toml, go.mod, Makefile, Dockerfile).

**Verify:** `cd go && go test ./internal/extractor/... -v`

---

## Phase 3 — LLM Client (Task 9)

### Task 9: llm/client.go — OpenAI-compatible LLM client

**Objective:** Wrap go-openai to work with any OpenAI-compatible endpoint (Ollama, Anthropic via proxy, Azure, etc.), with retry on timeout/5xx.

**Files:**
- Create: `go/internal/llm/client.go`
- Create: `go/internal/llm/client_test.go`

```go
// go/internal/llm/client.go
package llm

import (
    "context"
    "strings"
    "time"
    openai "github.com/sashabaranov/go-openai"
    "github.com/unrealandychan/rekipedia/internal/models"
)

type Client struct {
    client *openai.Client
    model  string
    temp   float32
}

func New(cfg models.LLMConfig) *Client {
    model := cfg.Model
    // Strip provider prefix for go-openai (e.g. "ollama/llama4" → "llama4")
    if idx := strings.Index(model, "/"); idx != -1 {
        model = model[idx+1:]
    }
    ocfg := openai.DefaultConfig(cfg.APIKey)
    if cfg.BaseURL != "" {
        ocfg.BaseURL = cfg.BaseURL
    } else if strings.HasPrefix(cfg.Model, "ollama/") {
        ocfg.BaseURL = "http://localhost:11434/v1"
    }
    return &Client{
        client: openai.NewClientWithConfig(ocfg),
        model:  model,
        temp:   float32(cfg.Temperature),
    }
}

func (c *Client) Call(ctx context.Context, system, prompt string) (string, error) {
    msgs := []openai.ChatCompletionMessage{}
    if system != "" {
        msgs = append(msgs, openai.ChatCompletionMessage{Role: "system", Content: system})
    }
    msgs = append(msgs, openai.ChatCompletionMessage{Role: "user", Content: prompt})

    var resp openai.ChatCompletionResponse
    var err error
    for attempt := 0; attempt < 3; attempt++ {
        resp, err = c.client.CreateChatCompletion(ctx, openai.ChatCompletionRequest{
            Model:       c.model,
            Messages:    msgs,
            Temperature: c.temp,
        })
        if err == nil { break }
        time.Sleep(time.Duration(5*(attempt+1)) * time.Second)
    }
    if err != nil { return "", err }
    return resp.Choices[0].Message.Content, nil
}

// StreamCall streams tokens via callback
func (c *Client) StreamCall(ctx context.Context, system, prompt string, cb func(string)) error {
    msgs := []openai.ChatCompletionMessage{}
    if system != "" {
        msgs = append(msgs, openai.ChatCompletionMessage{Role: "system", Content: system})
    }
    msgs = append(msgs, openai.ChatCompletionMessage{Role: "user", Content: prompt})
    stream, err := c.client.CreateChatCompletionStream(ctx, openai.ChatCompletionRequest{
        Model: c.model, Messages: msgs, Temperature: c.temp, Stream: true,
    })
    if err != nil { return err }
    defer stream.Close()
    for {
        resp, err := stream.Recv()
        if err != nil { break }
        if len(resp.Choices) > 0 {
            cb(resp.Choices[0].Delta.Content)
        }
    }
    return nil
}
```

**Verify:** `cd go && go test ./internal/llm/... -v` (mock HTTP server)

---

## Phase 4 — Synthesis (Tasks 10–12)

### Task 10: synthesis/planner.go — PlannerAgent

**Objective:** Send planning summary to LLM, parse WikiPlan JSON response. Same logic as Python `PlannerAgent`.

**Planning summary must include:**
- `file_count`, `impl_file_count`, `test_file_count`, `config_file_count`
- `symbol_count`, `symbol_kinds`, `symbol_sample` (top 80)
- `top_level_dirs`, `entry_points`, `has_tests`, `has_cli`, `has_config`
- `relationship_count`, `build_commands`, `test_commands`

**Default plan fallback:** If LLM fails, generate 3–6 pages heuristically.

**Verify:** `cd go && go test ./internal/synthesis/... -v`

---

### Task 11: synthesis/page_builder.go — PageBuilder

**Objective:** Build full payload from AnalysisResult, slice per page spec, call LLM for each page concurrently (max 4 goroutines via errgroup semaphore).

**Key functions:**
- `BuildPayload(result AnalysisResult, diagrams map[string]string) map[string]any`
- `SlicePayload(full map[string]any, requiredData []string) map[string]any`
- `BuildPage(ctx context.Context, spec WikiPageSpec, payload map[string]any, client *llm.Client) (string, error)`

**Verify:** `cd go && go test ./internal/synthesis/... -v`

---

### Task 12: synthesis/diagram_builder.go — Mermaid diagram

**Objective:** Build Mermaid `flowchart LR` from relationships. Same as Python's DiagramBuilder.

**Output:** `map[string][2]string` — name → (type, mermaid_content)

**Verify:** `cd go && go test ./internal/synthesis/... -v`

---

## Phase 5 — Orchestrator (Tasks 13–15)

### Task 13: orchestrator/run_digest.go — Full scan

**Objective:** Orchestrate full scan:
1. Walk repo → FileManifest
2. Shard files (4 shards)
3. Extract each shard concurrently
4. Combine AnalysisResult
5. Build diagrams
6. Run PlannerAgent
7. Build wiki pages (max 4 concurrent)
8. Save to SQLite + write .rekipedia/wiki/*.md
9. Export JSON manifest
10. Write scan_meta.json
11. Auto-embed if REKIPEDIA_EMBED_MODEL set

**Verify:** `cd go && go test ./internal/orchestrator/... -v`

---

### Task 14: orchestrator/run_update.go — Incremental update

**Objective:** Detect changed files via SHA256 diff, re-extract only changed shards, merge with previous AnalysisResult, regenerate affected pages.

**Verify:** `cd go && go test ./internal/orchestrator/... -v`

---

### Task 15: orchestrator/run_ask.go — Q&A

**Objective:** Load wiki pages + RAG chunks, build system prompt, stream answer via LLM.

**Hybrid retrieval:**
1. If FAISS index exists → cosine similarity top-8 chunks
2. Load all wiki pages from `.rekipedia/wiki/*.md`
3. Combine into system prompt, stream answer

**Verify:** `cd go && go test ./internal/orchestrator/... -v`

---

## Phase 6 — RAG (Task 16)

### Task 16: rag/embedder.go — Pure-Go vector store

**Objective:** Replace Python's FAISS with a pure-Go cosine similarity vector store. No CGO for vectors.

**Design:**
```go
type Chunk struct {
    File           string    `json:"file"`
    ChunkIdx       int       `json:"chunk_idx"`
    Text           string    `json:"text"`
    IsCode         bool      `json:"is_code"`
    IsImplementation bool    `json:"is_implementation"`
    Vector         []float32 `json:"vector"`
}

type VectorStore struct {
    Chunks []Chunk `json:"chunks"`
}
```

**Functions:**
- `Build(repo string, cfg models.LLMConfig, outDir string, cb func(string)) (int, error)` — chunk files, call embedding API, save `chunks.json`
- `Search(query string, topK int, store VectorStore) []Chunk` — cosine similarity ranking
- `CosineSimilarity(a, b []float32) float32`

**Embedding API:** Use go-openai `CreateEmbeddings()` with custom BaseURL (same provider routing logic as LLM client).

**Max sizes:** Env vars `REKIPEDIA_MAX_CODE_CHARS` (default 320000), `REKIPEDIA_MAX_DOC_CHARS` (default 32000).

**Verify:** `cd go && go test ./internal/rag/... -v`

---

## Phase 7 — Exporters + Server (Tasks 17–18)

### Task 17: exporter/ — Markdown, ZIP, JSON exporters

**Objective:** Implement `rekipedia export` — read wiki pages, bundle to md/zip/json.

**Files:**
- `go/internal/exporter/markdown.go`
- `go/internal/exporter/zip.go`
- `go/internal/exporter/json.go`

**Verify:** `cd go && go test ./internal/exporter/... -v`

---

### Task 18: server/server.go — HTTP server

**Objective:** Serve wiki pages as HTML, proxy Q&A via SSE (server-sent events for streaming).

**Endpoints:**
```
GET  /              → wiki index page (HTML)
GET  /wiki/:slug    → single wiki page (HTML, renders markdown)
GET  /api/pages     → list pages (JSON)
GET  /api/pages/:slug → page content (JSON)
POST /api/ask       → Q&A (SSE stream)
GET  /api/status    → scan status (JSON)
```

**Templates:** Embedded via `embed.FS` — single dark-themed HTML template.

**Verify:** `cd go && go test ./internal/server/... -v`

---

## Phase 8 — CLI Commands (Task 19)

### Task 19: All cobra subcommands

**Objective:** Wire up all 7 commands to their orchestrators.

**Files:**
- `go/cmd/rekipedia/cmd/init.go`
- `go/cmd/rekipedia/cmd/scan.go`
- `go/cmd/rekipedia/cmd/update.go`
- `go/cmd/rekipedia/cmd/ask.go`
- `go/cmd/rekipedia/cmd/serve.go`
- `go/cmd/rekipedia/cmd/embed.go`
- `go/cmd/rekipedia/cmd/export.go`

**Flag parity with Python:**
```
scan:   --model, --api-key, --base-url, --no-docker, --output-dir, --verbose, --embed-model, --embed-provider
update: --model, --no-docker, --verbose
ask:    --repo, --model, -q (single-shot)
serve:  --port, --no-browser
embed:  --model, --provider
export: --format (md|zip|json), --output
init:   (no flags)
```

**Verify:** `cd go && go build ./cmd/rekipedia && ./rekipedia --help`

---

## Phase 9 — Tests + Binary Verification (Task 20)

### Task 20: Integration tests + binary smoke test

**Objective:** Verify all packages compile, tests pass, binary runs correctly.

```bash
cd go
# Unit tests
go test ./... -v -count=1

# Build binary (CGO for sqlite3)
CGO_ENABLED=1 go build -ldflags "-s -w" -o rekipedia-bin ./cmd/rekipedia

# Smoke test
./rekipedia-bin --version
./rekipedia-bin --help
./rekipedia-bin scan --help
./rekipedia-bin ask --help

# Cross-compile check (macOS)
GOOS=darwin GOARCH=arm64 CGO_ENABLED=0 go build -o /dev/null ./cmd/rekipedia 2>&1 || true
```

**Verify:** All tests green, binary executes, help text matches Python CLI.

---

## Phase 10 — Distribution (Task 21)

### Task 21: goreleaser + GitHub Actions

**Objective:** Set up automated multi-platform release pipeline.

**Files:**
- Create: `go/.goreleaser.yaml`
- Create: `.github/workflows/go-release.yml`

**goreleaser config:**
```yaml
# go/.goreleaser.yaml
version: 2
project_name: rekipedia

builds:
  - id: rekipedia
    main: ./cmd/rekipedia
    dir: go
    binary: reki
    env:
      - CGO_ENABLED=1
    ldflags:
      - -s -w
      - -X main.version={{.Version}}
      - -X main.commit={{.Commit}}
      - -X main.date={{.Date}}
    goos: [linux, darwin]
    goarch: [amd64, arm64]
    # Windows: CGO sqlite3 needs MinGW — separate job
    ignore:
      - goos: darwin
        goarch: amd64  # remove if CI has amd64 Mac runner

archives:
  - format: tar.gz
    name_template: "{{ .ProjectName }}_{{ .Version }}_{{ .Os }}_{{ .Arch }}"
    files:
      - README.md
      - LICENSE
      - RELEASE-NOTES.md
    format_overrides:
      - goos: windows
        format: zip

checksum:
  name_template: "checksums.txt"

changelog:
  sort: asc
  filters:
    exclude: ['^docs:', '^test:', '^ci:']

brews:
  - name: rekipedia
    repository:
      owner: unrealandychan
      name: homebrew-tap
      token: "{{ .Env.HOMEBREW_TAP_TOKEN }}"
    description: "Your AI tech lead — scan any repo into a knowledge store"
    homepage: "https://github.com/unrealandychan/rekipedia"
    install: |
      bin.install "rekipedia"
    test: |
      system "#{bin}/rekipedia --version"

nfpms:
  - package_name: rekipedia
    homepage: https://github.com/unrealandychan/rekipedia
    description: "Your AI tech lead — scan any repo into a knowledge store"
    formats: [deb, rpm, apk]
    bindir: /usr/local/bin
```

**GitHub Actions:**
```yaml
# .github/workflows/go-release.yml
name: Go Release
on:
  push:
    tags: ['v*']

jobs:
  release:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: { fetch-depth: 0 }
      - uses: actions/setup-go@v5
        with: { go-version: '1.22' }
      - name: Install CGO deps
        run: sudo apt-get install -y gcc-multilib gcc-aarch64-linux-gnu
      - uses: goreleaser/goreleaser-action@v5
        with:
          version: latest
          args: release --clean
          workdir: go
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          HOMEBREW_TAP_TOKEN: ${{ secrets.HOMEBREW_TAP_TOKEN }}
```

**Distribution channels:**
| Channel | How | Notes |
|---|---|---|
| GitHub Releases | goreleaser auto | tar.gz + checksums per platform |
| Homebrew | goreleaser `brews:` | Needs `homebrew-tap` repo |
| apt/deb | goreleaser `nfpms:` | Linux users |
| Docker | `FROM scratch` + static binary | `docker pull ghcr.io/unrealandychan/rekipedia` |
| Script install | `curl -fsSL .../install.sh \| sh` | Universal fallback |

**install.sh pattern:**
```bash
#!/bin/sh
VERSION=$(curl -s https://api.github.com/repos/unrealandychan/rekipedia/releases/latest | grep '"tag_name"' | cut -d'"' -f4)
OS=$(uname -s | tr '[:upper:]' '[:lower:]')
ARCH=$(uname -m); [ "$ARCH" = "x86_64" ] && ARCH="amd64"; [ "$ARCH" = "aarch64" ] && ARCH="arm64"
curl -fsSL "https://github.com/unrealandychan/rekipedia/releases/download/${VERSION}/rekipedia_${VERSION}_${OS}_${ARCH}.tar.gz" | tar xz
sudo mv rekipedia /usr/local/bin/
echo "rekipedia ${VERSION} installed!"
```

**Verify:** `cd go && goreleaser check` (dry-run)

---

## Summary

| Phase | Tasks | Key deliverable |
|---|---|---|
| 1 | 1–5 | Foundation: models, config, storage, fsutil, cobra root |
| 2 | 6–8 | Extractors: Python, TypeScript, config files |
| 3 | 9 | LLM client with streaming + retry |
| 4 | 10–12 | Synthesis: PlannerAgent, PageBuilder, DiagramBuilder |
| 5 | 13–15 | Orchestrator: scan, update, ask |
| 6 | 16 | RAG: pure-Go vector store + embedding |
| 7 | 17–18 | Exporters + HTTP server |
| 8 | 19 | All 7 CLI commands wired up |
| 9 | 20 | Tests + binary verification |
| 10 | 21 | goreleaser + GitHub Actions distribution |

**Total: 21 tasks** — estimated 4–6 weeks solo dev.
