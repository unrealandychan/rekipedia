package storage

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/unrealandychan/rekipedia/internal/models"
)

func openTestStore(t *testing.T) *Store {
	t.Helper()
	tmp := t.TempDir()
	s, err := Open(filepath.Join(tmp, "test.db"))
	if err != nil {
		t.Fatalf("Open failed: %v", err)
	}
	t.Cleanup(func() { _ = s.Close() })
	return s
}

func TestOpenAndClose(t *testing.T) {
	s := openTestStore(t)
	if s == nil {
		t.Fatal("store is nil")
	}
}

func TestDefaultPath(t *testing.T) {
	path := DefaultPath("/repos/myapp")
	expected := filepath.Join("/repos/myapp", ".rekipedia", "store.db")
	if path != expected {
		t.Errorf("expected %s, got %s", expected, path)
	}
}

func TestRunLifecycle(t *testing.T) {
	s := openTestStore(t)

	if err := s.CreateRun("run-1", "/repo", "gpt-4o"); err != nil {
		t.Fatalf("CreateRun: %v", err)
	}
	if err := s.FinishRun("run-1", 5); err != nil {
		t.Fatalf("FinishRun: %v", err)
	}
	id, err := s.LatestRunID("/repo")
	if err != nil {
		t.Fatalf("LatestRunID: %v", err)
	}
	if id != "run-1" {
		t.Errorf("expected run-1, got %s", id)
	}
}

func TestLatestRunIDMissing(t *testing.T) {
	s := openTestStore(t)
	id, err := s.LatestRunID("/nowhere")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if id != "" {
		t.Errorf("expected empty ID for missing repo, got %s", id)
	}
}

func TestSaveAndListSymbols(t *testing.T) {
	s := openTestStore(t)
	_ = s.CreateRun("r1", "/repo", "llama4")

	syms := []models.Symbol{
		{Name: "main", Kind: models.SymbolFunction, File: "main.go", LineStart: 1, LineEnd: 10},
		{Name: "App", Kind: models.SymbolClass, File: "app.go"},
	}
	if err := s.SaveSymbols("r1", syms); err != nil {
		t.Fatalf("SaveSymbols: %v", err)
	}
	got, err := s.ListSymbols("r1")
	if err != nil {
		t.Fatalf("ListSymbols: %v", err)
	}
	if len(got) != 2 {
		t.Errorf("expected 2 symbols, got %d", len(got))
	}
}

func TestSaveRelationships(t *testing.T) {
	s := openTestStore(t)
	_ = s.CreateRun("r2", "/repo", "llama4")

	rels := []models.Relationship{
		{From: "main", To: "app.App", Kind: models.RelCall, File: "main.go"},
	}
	if err := s.SaveRelationships("r2", rels); err != nil {
		t.Fatalf("SaveRelationships: %v", err)
	}
}

func TestUpsertAndGetWikiPage(t *testing.T) {
	s := openTestStore(t)
	_ = s.CreateRun("r3", "/repo", "llama4")

	if err := s.UpsertWikiPage("r3", "index", "Index", "Overview", "# Hello", 100, 90); err != nil {
		t.Fatalf("UpsertWikiPage: %v", err)
	}
	title, section, content, err := s.GetWikiPage("r3", "index")
	if err != nil {
		t.Fatalf("GetWikiPage: %v", err)
	}
	if title != "Index" || section != "Overview" || content != "# Hello" {
		t.Errorf("unexpected page data: %q %q %q", title, section, content)
	}
}

func TestUpsertWikiPageIdempotent(t *testing.T) {
	s := openTestStore(t)
	_ = s.CreateRun("r4", "/repo", "llama4")

	_ = s.UpsertWikiPage("r4", "index", "Index v1", "Sec", "v1 content", 50, 50)
	_ = s.UpsertWikiPage("r4", "index", "Index v2", "Sec", "v2 content", 80, 80)

	title, _, content, _ := s.GetWikiPage("r4", "index")
	if title != "Index v2" {
		t.Errorf("expected upsert to update, got %q", title)
	}
	if content != "v2 content" {
		t.Errorf("expected v2 content, got %q", content)
	}
}

func TestListWikiPages(t *testing.T) {
	s := openTestStore(t)
	_ = s.CreateRun("r5", "/repo", "llama4")

	_ = s.UpsertWikiPage("r5", "arch", "Architecture", "Core", "...", 80, 90)
	_ = s.UpsertWikiPage("r5", "index", "Index", "Overview", "...", 100, 100)

	pages, err := s.ListWikiPages("r5")
	if err != nil {
		t.Fatalf("ListWikiPages: %v", err)
	}
	if len(pages) != 2 {
		t.Errorf("expected 2 pages, got %d", len(pages))
	}
	// Should be ordered by importance desc
	if pages[0].Slug != "index" {
		t.Errorf("expected index first (importance 100), got %s", pages[0].Slug)
	}
}

func TestSaveQA(t *testing.T) {
	s := openTestStore(t)
	_ = s.CreateRun("r6", "/repo", "llama4")
	if err := s.SaveQA("r6", "What does main do?", "It initializes the app."); err != nil {
		t.Fatalf("SaveQA: %v", err)
	}
}

func TestUpsertManifest(t *testing.T) {
	s := openTestStore(t)

	if err := s.UpsertManifest("src/app.py", "abc123", "python", 1024); err != nil {
		t.Fatalf("UpsertManifest: %v", err)
	}
	sha, lang, size, err := s.GetManifest("src/app.py")
	if err != nil {
		t.Fatalf("GetManifest: %v", err)
	}
	if sha != "abc123" || lang != "python" || size != 1024 {
		t.Errorf("unexpected manifest: %s %s %d", sha, lang, size)
	}
}

func TestGetManifestMissing(t *testing.T) {
	s := openTestStore(t)
	sha, lang, size, err := s.GetManifest("nonexistent.py")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if sha != "" || lang != "" || size != 0 {
		t.Error("expected zero values for missing file")
	}
}

func TestMultipleRunsIsolated(t *testing.T) {
	s := openTestStore(t)
	_ = s.CreateRun("run-a", "/repo", "llama4")
	_ = s.CreateRun("run-b", "/repo", "gpt-4o")

	_ = s.SaveSymbols("run-a", []models.Symbol{{Name: "funcA", Kind: models.SymbolFunction, File: "a.py"}})
	_ = s.SaveSymbols("run-b", []models.Symbol{
		{Name: "funcB1", Kind: models.SymbolFunction, File: "b.py"},
		{Name: "funcB2", Kind: models.SymbolClass, File: "b.py"},
	})

	symsA, _ := s.ListSymbols("run-a")
	symsB, _ := s.ListSymbols("run-b")
	if len(symsA) != 1 {
		t.Errorf("run-a: expected 1 symbol, got %d", len(symsA))
	}
	if len(symsB) != 2 {
		t.Errorf("run-b: expected 2 symbols, got %d", len(symsB))
	}
}

// TestOpenInvalidPath verifies that opening a non-existent directory fails gracefully.
func TestOpenInvalidPath(t *testing.T) {
	_, err := Open("/nonexistent/path/store.db")
	if err == nil {
		t.Error("expected error for invalid path, got nil")
	}
	_ = os.Remove("/nonexistent/path/store.db")
}
