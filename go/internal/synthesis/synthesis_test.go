package synthesis

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	openai "github.com/sashabaranov/go-openai"

	"github.com/unrealandychan/rekipedia/internal/llm"
	"github.com/unrealandychan/rekipedia/internal/models"
)

// ── mock LLM server ───────────────────────────────────────────────────────────

func mockLLMServer(t *testing.T, responseBody string) (*httptest.Server, *llm.Client) {
	t.Helper()
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		resp := openai.ChatCompletionResponse{
			Choices: []openai.ChatCompletionChoice{
				{Message: openai.ChatCompletionMessage{Content: responseBody}},
			},
		}
		_ = json.NewEncoder(w).Encode(resp)
	}))
	cfg := models.LLMConfig{
		Model:   "gpt-4o",
		APIKey:  "test",
		BaseURL: srv.URL + "/v1",
	}
	client := llm.New(cfg)
	return srv, client
}

// ── sample analysis result ─────────────────────────────────────────────────────

func sampleAnalysisResult() models.AnalysisResult {
	return models.AnalysisResult{
		ShardID: "test",
		FilesSeen: []string{
			"src/app.py", "src/utils.py", "src/models.py",
			"tests/test_app.py", "tests/test_utils.py", "tests/test_models.py",
			"config.yaml", "pyproject.toml", "Makefile", "README.md",
			"src/cli.py", "src/server.py",
		},
		EntryPoints:   []string{"src/cli.py", "src/app.py"},
		BuildCommands: []string{"make build", "pip install -e ."},
		TestCommands:  []string{"pytest", "make test"},
		Symbols: []models.Symbol{
			{Name: "App", Kind: models.SymbolClass, File: "src/app.py", LineStart: 5},
			{Name: "App.run", Kind: models.SymbolFunction, File: "src/app.py", LineStart: 10},
			{Name: "utils.helper", Kind: models.SymbolFunction, File: "src/utils.py"},
			{Name: "UserModel", Kind: models.SymbolClass, File: "src/models.py"},
			{Name: "Config", Kind: models.SymbolClass, File: "config.yaml"},
		},
		Relationships: []models.Relationship{
			{From: "src/app.py", To: "src/utils.py", Kind: models.RelImport},
			{From: "src/app.py", To: "src/models.py", Kind: models.RelImport},
			{From: "src/cli.py", To: "src/app.py", Kind: models.RelImport},
			{From: "UserModel", To: "App", Kind: models.RelInherits},
		},
		Evidence: map[string]string{"package_name": "myapp"},
	}
}

// ── PlannerAgent tests ─────────────────────────────────────────────────────────

var validPlanJSON = `{
  "sections": [
    {"id": "getting-started", "title": "Getting Started", "pages": ["index"]},
    {"id": "architecture", "title": "Architecture", "pages": ["architecture-overview", "core-modules"]}
  ],
  "pages": [
    {"slug": "index", "title": "Overview", "section": "getting-started", "priority": 1, "importance": 100, "focus": "Project overview.", "required_data": ["files_seen"], "tags": ["overview"]},
    {"slug": "architecture-overview", "title": "Architecture", "section": "architecture", "priority": 2, "importance": 90, "focus": "Architecture.", "required_data": ["symbols"], "tags": ["arch"]},
    {"slug": "core-modules", "title": "Core Modules", "section": "architecture", "priority": 3, "importance": 80, "focus": "Modules.", "required_data": ["symbols", "files_seen"], "tags": ["modules"]}
  ],
  "nav_order": ["index", "architecture-overview", "core-modules"],
  "index_slug": "index"
}`

func TestPlannerParsesValidJSON(t *testing.T) {
	srv, client := mockLLMServer(t, validPlanJSON)
	defer srv.Close()

	planner := NewPlannerAgent(client)
	plan, err := planner.Plan(context.Background(), sampleAnalysisResult())
	if err != nil {
		t.Fatalf("Plan error: %v", err)
	}
	if len(plan.Pages) != 3 {
		t.Errorf("expected 3 pages, got %d", len(plan.Pages))
	}
	if plan.IndexSlug != "index" {
		t.Errorf("expected index_slug='index', got %q", plan.IndexSlug)
	}
	if len(plan.Sections) != 2 {
		t.Errorf("expected 2 sections, got %d", len(plan.Sections))
	}
}

func TestPlannerStripsFences(t *testing.T) {
	fenced := "```json\n" + validPlanJSON + "\n```"
	srv, client := mockLLMServer(t, fenced)
	defer srv.Close()

	planner := NewPlannerAgent(client)
	plan, err := planner.Plan(context.Background(), sampleAnalysisResult())
	if err != nil {
		t.Fatalf("Plan error: %v", err)
	}
	if len(plan.Pages) == 0 {
		t.Error("expected pages after stripping fences")
	}
}

func TestPlannerFallbackOnLLMError(t *testing.T) {
	// Server that returns 500
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
	}))
	defer srv.Close()

	cfg := models.LLMConfig{Model: "gpt-4o", APIKey: "test", BaseURL: srv.URL + "/v1"}
	client := llm.New(cfg)
	planner := NewPlannerAgent(client)
	plan, err := planner.Plan(context.Background(), sampleAnalysisResult())
	if err != nil {
		t.Fatalf("expected graceful fallback, got error: %v", err)
	}
	if len(plan.Pages) == 0 {
		t.Error("fallback plan should have at least 1 page")
	}
}

func TestPlannerFallbackOnInvalidJSON(t *testing.T) {
	srv, client := mockLLMServer(t, "This is not JSON at all, sorry!")
	defer srv.Close()

	planner := NewPlannerAgent(client)
	plan, err := planner.Plan(context.Background(), sampleAnalysisResult())
	if err != nil {
		t.Fatalf("expected graceful fallback, got error: %v", err)
	}
	if len(plan.Pages) == 0 {
		t.Error("fallback plan should have pages")
	}
}

func TestPlannerNavOrderByImportance(t *testing.T) {
	// JSON with pages NOT in importance order — planner should sort nav_order
	planJSON := `{
  "sections": [],
  "pages": [
    {"slug": "testing", "title": "Testing", "section": "dev", "priority": 3, "importance": 60, "focus": ".", "required_data": [], "tags": []},
    {"slug": "index", "title": "Index", "section": "start", "priority": 1, "importance": 100, "focus": ".", "required_data": [], "tags": []},
    {"slug": "arch", "title": "Architecture", "section": "arch", "priority": 2, "importance": 90, "focus": ".", "required_data": [], "tags": []}
  ],
  "nav_order": ["testing", "index", "arch"],
  "index_slug": "index"
}`
	srv, client := mockLLMServer(t, planJSON)
	defer srv.Close()

	planner := NewPlannerAgent(client)
	plan, _ := planner.Plan(context.Background(), sampleAnalysisResult())

	if len(plan.NavOrder) < 3 {
		t.Fatalf("expected 3 items in nav_order, got %d", len(plan.NavOrder))
	}
	if plan.NavOrder[0] != "index" {
		t.Errorf("expected 'index' first (importance 100), got %q", plan.NavOrder[0])
	}
}

func TestBuildPlanningSummary(t *testing.T) {
	result := sampleAnalysisResult()
	summary := buildPlanningSummary(result)

	if summary.FileCount != len(result.FilesSeen) {
		t.Errorf("file_count mismatch: expected %d, got %d", len(result.FilesSeen), summary.FileCount)
	}
	if summary.SymbolCount != len(result.Symbols) {
		t.Errorf("symbol_count mismatch: expected %d, got %d", len(result.Symbols), summary.SymbolCount)
	}
	if !summary.HasTests {
		t.Error("expected HasTests=true (3 test files)")
	}
	if summary.TestFileCount != 3 {
		t.Errorf("expected 3 test files, got %d", summary.TestFileCount)
	}
}

func TestFallbackPlanSmallRepo(t *testing.T) {
	small := models.AnalysisResult{
		FilesSeen: []string{"main.py", "utils.py"},
		Symbols:   []models.Symbol{{Name: "main", Kind: models.SymbolFunction}},
	}
	plan := fallbackPlan(small)
	if len(plan.Pages) == 0 {
		t.Error("expected at least 1 page for small repo")
	}
	if plan.IndexSlug != "index" {
		t.Error("expected index_slug='index'")
	}
}

func TestFallbackPlanLargeRepo(t *testing.T) {
	// Add enough symbols to trigger core-modules page (>10 symbols)
	var syms []models.Symbol
	for i := 0; i < 15; i++ {
		syms = append(syms, models.Symbol{Name: "Sym", Kind: models.SymbolFunction})
	}
	result := sampleAnalysisResult()
	result.Symbols = syms
	plan := fallbackPlan(result)

	slugs := make(map[string]bool)
	for _, pg := range plan.Pages {
		slugs[pg.Slug] = true
	}
	if !slugs["core-modules"] {
		t.Error("expected core-modules page for repo with >10 symbols")
	}
}

func TestParsePlanJSONWrapped(t *testing.T) {
	wrapped := "Here is the plan:\n```json\n" + validPlanJSON + "\n```\nDone."
	plan, err := parsePlanJSON(wrapped)
	if err != nil {
		t.Fatalf("parsePlanJSON error: %v", err)
	}
	if len(plan.Pages) != 3 {
		t.Errorf("expected 3 pages, got %d", len(plan.Pages))
	}
}

func TestParsePlanJSONEmpty(t *testing.T) {
	_, err := parsePlanJSON("No JSON here")
	if err == nil {
		t.Error("expected error for non-JSON input")
	}
}

func TestParsePlanJSONZeroPages(t *testing.T) {
	empty := `{"sections":[],"pages":[],"nav_order":[],"index_slug":""}`
	_, err := parsePlanJSON(empty)
	if err == nil {
		t.Error("expected error for zero pages")
	}
}

// ── PageBuilder tests ──────────────────────────────────────────────────────────

func TestPageBuilderBuildPage(t *testing.T) {
	srv, client := mockLLMServer(t, "## Overview\nThis project does X.\n")
	defer srv.Close()

	builder := NewPageBuilder(client)
	spec := models.WikiPageSpec{
		Slug: "index", Title: "Overview", Section: "getting-started",
		Priority: 1, Importance: 100,
		Focus:        "Write the project overview.",
		RequiredData: []string{"files_seen"},
	}
	payload := buildPayload(sampleAnalysisResult(), nil)
	content, err := builder.BuildPage(context.Background(), spec, payload)
	if err != nil {
		t.Fatalf("BuildPage error: %v", err)
	}
	if !strings.Contains(content, "Overview") {
		t.Errorf("expected 'Overview' in content, got: %q", content[:min(100, len(content))])
	}
}

func TestPageBuilderBuildAll(t *testing.T) {
	srv, client := mockLLMServer(t, "## Page\nContent here.\n")
	defer srv.Close()

	builder := NewPageBuilder(client)
	plan := models.WikiPlan{
		Pages: []models.WikiPageSpec{
			{Slug: "index", Title: "Index", RequiredData: []string{"files_seen"}},
			{Slug: "arch", Title: "Architecture", RequiredData: []string{"symbols"}},
		},
	}
	pages, err := builder.BuildAll(context.Background(), plan, sampleAnalysisResult(), nil)
	if err != nil {
		t.Fatalf("BuildAll error: %v", err)
	}
	if len(pages) != 2 {
		t.Errorf("expected 2 pages, got %d", len(pages))
	}
	if _, ok := pages["index"]; !ok {
		t.Error("expected 'index' page")
	}
	if _, ok := pages["arch"]; !ok {
		t.Error("expected 'arch' page")
	}
}

func TestBuildPayload(t *testing.T) {
	result := sampleAnalysisResult()
	payload := buildPayload(result, nil)

	if _, ok := payload["files_seen"]; !ok {
		t.Error("expected 'files_seen' in payload")
	}
	if _, ok := payload["symbols"]; !ok {
		t.Error("expected 'symbols' in payload")
	}
	if _, ok := payload["file_count"]; !ok {
		t.Error("expected 'file_count' in payload")
	}
}

func TestSlicePayload(t *testing.T) {
	payload := map[string]any{
		"files_seen":   []string{"a.py", "b.py"},
		"symbols":      []string{"App"},
		"evidence":     map[string]string{"k": "v"},
		"file_count":   5,
		"entry_points": []string{"main.py"},
	}
	sliced := slicePayload(payload, []string{"symbols"})
	if _, ok := sliced["symbols"]; !ok {
		t.Error("expected 'symbols' in sliced payload")
	}
	if _, ok := sliced["file_count"]; !ok {
		t.Error("expected always-included 'file_count'")
	}
	if _, ok := sliced["evidence"]; ok {
		t.Error("'evidence' should not be in sliced payload")
	}
}

func TestSlicePayloadEmpty(t *testing.T) {
	payload := map[string]any{"a": 1, "b": 2}
	sliced := slicePayload(payload, nil)
	if len(sliced) != len(payload) {
		t.Error("empty requiredData should return full payload")
	}
}

// ── DiagramBuilder tests ───────────────────────────────────────────────────────

func TestDiagramBuilderEmpty(t *testing.T) {
	db := NewDiagramBuilder()
	out := db.Build(nil, nil)
	if len(out) != 0 {
		t.Error("expected empty diagrams for no relationships")
	}
}

func TestDiagramBuilderModuleGraph(t *testing.T) {
	rels := []models.Relationship{
		{From: "src/app.py", To: "src/utils.py", Kind: models.RelImport},
		{From: "src/cli.py", To: "src/app.py", Kind: models.RelImport},
	}
	db := NewDiagramBuilder()
	out := db.Build(rels, []string{"src/cli.py"})

	if _, ok := out["module-graph"]; !ok {
		t.Error("expected 'module-graph' diagram")
	}
	diagram := out["module-graph"]
	if diagram[0] != "flowchart" {
		t.Errorf("expected type 'flowchart', got %q", diagram[0])
	}
	if !strings.Contains(diagram[1], "flowchart LR") {
		t.Errorf("expected 'flowchart LR' in diagram: %q", diagram[1][:min(200, len(diagram[1]))])
	}
}

func TestDiagramBuilderClassHierarchy(t *testing.T) {
	rels := []models.Relationship{
		{From: "Dog", To: "Animal", Kind: models.RelInherits},
		{From: "Cat", To: "Animal", Kind: models.RelInherits},
	}
	db := NewDiagramBuilder()
	out := db.Build(rels, nil)

	if _, ok := out["class-hierarchy"]; !ok {
		t.Error("expected 'class-hierarchy' diagram for inherits relationships")
	}
	ch := out["class-hierarchy"]
	if !strings.Contains(ch[1], "classDiagram") {
		t.Errorf("expected 'classDiagram' in output: %q", ch[1])
	}
	if !strings.Contains(ch[1], "Animal") {
		t.Errorf("expected 'Animal' in class diagram: %q", ch[1])
	}
}

func TestDiagramBuilderNoClassHierarchy(t *testing.T) {
	// Only import relationships — no class hierarchy expected
	rels := []models.Relationship{
		{From: "a.py", To: "b.py", Kind: models.RelImport},
	}
	db := NewDiagramBuilder()
	out := db.Build(rels, nil)
	if _, ok := out["class-hierarchy"]; ok {
		t.Error("should not produce class-hierarchy for import-only relationships")
	}
}

func TestNodeID(t *testing.T) {
	cases := []struct {
		input    string
		expected string
	}{
		{"src/app.py", "src_app_py"},
		{"MyClass.method", "MyClass_method"},
		{"simple", "simple"},
	}
	for _, tc := range cases {
		got := nodeID(tc.input)
		if got != tc.expected {
			t.Errorf("nodeID(%q) = %q, want %q", tc.input, got, tc.expected)
		}
	}
}

func TestNodeLabel(t *testing.T) {
	cases := []struct {
		input    string
		expected string
	}{
		{"src/app.py", "app"},
		{"MyClass", "MyClass"},
		{"src/utils", "utils"},
	}
	for _, tc := range cases {
		got := nodeLabel(tc.input)
		if got != tc.expected {
			t.Errorf("nodeLabel(%q) = %q, want %q", tc.input, got, tc.expected)
		}
	}
}

func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}
