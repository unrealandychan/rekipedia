package exporter

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/unrealandychan/rekipedia/internal/models"
)

func makeJSONExporter(t *testing.T) (*JSONExporter, string) {
	dir := t.TempDir()
	return NewJSONExporter(dir), dir
}

func makeMarkdownExporter(t *testing.T) (*MarkdownExporter, string) {
	dir := t.TempDir()
	return NewMarkdownExporter(dir), dir
}

// ── JSONExporter tests ─────────────────────────────────────────────────────────

func TestJSONExporter_CreatesExportsDir(t *testing.T) {
	e, dir := makeJSONExporter(t)
	err := e.Export("run1", nil, models.AnalysisResult{}, nil, nil, models.WikiPlan{}, nil)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(dir, "exports")); err != nil {
		t.Fatal("exports dir not created")
	}
}

func TestJSONExporter_SymbolsJSON(t *testing.T) {
	e, dir := makeJSONExporter(t)
	combined := models.AnalysisResult{
		Symbols: []models.Symbol{{Name: "Foo", Kind: models.SymbolFunction, File: "a.go"}},
	}
	e.Export("r1", nil, combined, nil, nil, models.WikiPlan{}, nil)
	data, err := os.ReadFile(filepath.Join(dir, "exports", "symbols.json"))
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(data), "Foo") {
		t.Error("symbols.json missing Foo")
	}
}

func TestJSONExporter_RelationshipsJSON(t *testing.T) {
	e, dir := makeJSONExporter(t)
	combined := models.AnalysisResult{
		Relationships: []models.Relationship{{From: "A", To: "B", Kind: models.RelCall}},
	}
	e.Export("r1", nil, combined, nil, nil, models.WikiPlan{}, nil)
	data, _ := os.ReadFile(filepath.Join(dir, "exports", "relationships.json"))
	if !strings.Contains(string(data), `"A"`) {
		t.Error("relationships.json missing A")
	}
}

func TestJSONExporter_ManifestJSON(t *testing.T) {
	e, dir := makeJSONExporter(t)
	pages := map[string]string{"overview": "# Overview"}
	titles := map[string]string{"overview": "Overview"}
	plan := models.WikiPlan{NavOrder: []string{"overview"}, Pages: []models.WikiPageSpec{{Slug: "overview", Title: "Overview"}}}
	e.Export("run-abc", []models.FileManifest{{Path: "a.go"}}, models.AnalysisResult{}, pages, titles, plan, nil)
	data, err := os.ReadFile(filepath.Join(dir, "exports", "manifest.json"))
	if err != nil {
		t.Fatal(err)
	}
	var m map[string]any
	json.Unmarshal(data, &m)
	if m["run_id"] != "run-abc" {
		t.Errorf("run_id mismatch: %v", m["run_id"])
	}
	if m["file_count"].(float64) != 1 {
		t.Errorf("file_count mismatch")
	}
}

func TestJSONExporter_EmptySymbols(t *testing.T) {
	e, dir := makeJSONExporter(t)
	e.Export("r1", nil, models.AnalysisResult{}, nil, nil, models.WikiPlan{}, nil)
	data, _ := os.ReadFile(filepath.Join(dir, "exports", "symbols.json"))
	if string(data) != "[]" {
		t.Errorf("expected empty array, got %s", data)
	}
}

// ── MarkdownExporter tests ─────────────────────────────────────────────────────

func TestMarkdownExporter_WritesPages(t *testing.T) {
	e, dir := makeMarkdownExporter(t)
	pages := map[string]string{"index": "# Index\nHello"}
	err := e.Export(pages, nil, nil)
	if err != nil {
		t.Fatal(err)
	}
	data, err := os.ReadFile(filepath.Join(dir, "wiki", "index.md"))
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(data), "Hello") {
		t.Error("page content missing")
	}
}

func TestMarkdownExporter_SkipsPinnedPage(t *testing.T) {
	e, dir := makeMarkdownExporter(t)
	wikiDir := filepath.Join(dir, "wiki")
	os.MkdirAll(wikiDir, 0o755)
	// Write existing pinned file
	pinned := "---\npin: true\n---\n# Original"
	os.WriteFile(filepath.Join(wikiDir, "pinned.md"), []byte(pinned), 0o644)

	pages := map[string]string{"pinned": "# New Content"}
	e.Export(pages, nil, nil)

	data, _ := os.ReadFile(filepath.Join(wikiDir, "pinned.md"))
	if strings.Contains(string(data), "New Content") {
		t.Error("pinned page should not be overwritten")
	}
}

func TestMarkdownExporter_WritesDiagrams(t *testing.T) {
	e, dir := makeMarkdownExporter(t)
	diagrams := map[string][2]string{"arch": {"Architecture", "graph TD\n  A-->B"}}
	err := e.Export(nil, nil, diagrams)
	if err != nil {
		t.Fatal(err)
	}
	data, err := os.ReadFile(filepath.Join(dir, "diagrams", "arch.md"))
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(data), "```mermaid") {
		t.Error("diagram file missing mermaid fence")
	}
}

func TestIsPinned(t *testing.T) {
	cases := []struct {
		content string
		want    bool
	}{
		{"---\npin: true\n---\n# Hello", true},
		{"---\npin: false\n---\n# Hello", false},
		{"# No frontmatter", false},
		{"---\ntitle: Foo\n---", false},
	}
	for _, c := range cases {
		got := isPinned(c.content)
		if got != c.want {
			t.Errorf("isPinned(%q) = %v, want %v", c.content, got, c.want)
		}
	}
}
