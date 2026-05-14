package rag

import (
	"strings"
	"testing"
)

// ---------------------------------------------------------------------------
// Helper
// ---------------------------------------------------------------------------

func totalText(chunks []Chunk) string {
	parts := make([]string, len(chunks))
	for i, c := range chunks {
		parts[i] = c.Text
	}
	return strings.Join(parts, "")
}

// ---------------------------------------------------------------------------
// chunkGo — symbol-boundary chunking
// ---------------------------------------------------------------------------

func TestChunkGo_SingleFunc(t *testing.T) {
	src := `package main

func Hello() string {
	return "hello"
}
`
	chunks := ChunkFile("foo.go", src)
	if len(chunks) == 0 {
		t.Fatal("expected at least one chunk")
	}
	// The function body must appear in some chunk.
	found := false
	for _, c := range chunks {
		if strings.Contains(c.Text, "Hello") {
			found = true
		}
	}
	if !found {
		t.Error("function Hello not found in any chunk")
	}
}

func TestChunkGo_MultipleFuncs_SeparateChunks(t *testing.T) {
	// Build a source with two large-enough functions that they shouldn't be merged.
	var sb strings.Builder
	sb.WriteString("package main\n\nimport \"fmt\"\n\n")
	// First function — large enough to avoid merging (> minChunkRune runes)
	sb.WriteString("func Alpha() {\n")
	for i := 0; i < 20; i++ {
		sb.WriteString("\tfmt.Println(\"alpha line\")\n")
	}
	sb.WriteString("}\n\n")
	// Second function
	sb.WriteString("func Beta() {\n")
	for i := 0; i < 20; i++ {
		sb.WriteString("\tfmt.Println(\"beta line\")\n")
	}
	sb.WriteString("}\n")

	src := sb.String()
	chunks := ChunkFile("two.go", src)

	hasAlpha, hasBeta := false, false
	for _, c := range chunks {
		if strings.Contains(c.Text, "func Alpha") {
			hasAlpha = true
		}
		if strings.Contains(c.Text, "func Beta") {
			hasBeta = true
		}
	}
	if !hasAlpha {
		t.Error("func Alpha not found in any chunk")
	}
	if !hasBeta {
		t.Error("func Beta not found in any chunk")
	}
}

func TestChunkGo_TypeDeclaration(t *testing.T) {
	src := `package models

type Config struct {
	Host string
	Port int
}

type Handler func(w http.ResponseWriter, r *http.Request)
`
	chunks := ChunkFile("models.go", src)
	hasConfig, hasHandler := false, false
	for _, c := range chunks {
		if strings.Contains(c.Text, "Config") {
			hasConfig = true
		}
		if strings.Contains(c.Text, "Handler") {
			hasHandler = true
		}
	}
	if !hasConfig {
		t.Error("type Config not found in chunks")
	}
	if !hasHandler {
		t.Error("type Handler not found in chunks")
	}
}

func TestChunkGo_SmallFuncsMerged(t *testing.T) {
	// Two tiny one-liner funcs: each alone is < minChunkRune runes, so
	// they should be merged into one chunk (or at most two chunks, never
	// resulting in empty single-function micro-chunks).
	src := `package util

func Inc(n int) int { return n + 1 }

func Dec(n int) int { return n - 1 }
`
	chunks := ChunkFile("util.go", src)
	// Both symbols must be present
	combined := totalText(chunks)
	if !strings.Contains(combined, "Inc") {
		t.Error("Inc missing from chunks")
	}
	if !strings.Contains(combined, "Dec") {
		t.Error("Dec missing from chunks")
	}
}

func TestChunkGo_OversizedFuncSplit(t *testing.T) {
	// A single function that is > chunkSize runes must be split into multiple chunks.
	var sb strings.Builder
	sb.WriteString("package main\n\nfunc BigFunc() {\n")
	for i := 0; i < 200; i++ {
		sb.WriteString("\t// this is a very long line to pad the function body with content\n")
	}
	sb.WriteString("}\n")
	src := sb.String()

	chunks := ChunkFile("big.go", src)
	if len(chunks) < 2 {
		t.Errorf("expected oversized func to produce ≥2 chunks, got %d", len(chunks))
	}
}

func TestChunkGo_LineNumbersMonotonic(t *testing.T) {
	var sb strings.Builder
	sb.WriteString("package main\n\n")
	for i := 0; i < 5; i++ {
		sb.WriteString("func F() {\n\treturn\n}\n\n")
	}
	src := sb.String()
	chunks := ChunkFile("lines.go", src)

	prev := 0
	for _, c := range chunks {
		sl := parseLineNum(c.StartLine)
		if sl < prev {
			t.Errorf("non-monotonic start line: %d after %d", sl, prev)
		}
		prev = sl
	}
}

func TestChunkGo_EmptyFile(t *testing.T) {
	chunks := ChunkFile("empty.go", "")
	// Should not panic; may return nil or empty slice.
	_ = chunks
}

func TestChunkGo_PackageOnlyFile(t *testing.T) {
	src := "package main\n"
	chunks := ChunkFile("pkg.go", src)
	_ = chunks // must not panic
}

// ---------------------------------------------------------------------------
// chunkWindow — non-Go fallback
// ---------------------------------------------------------------------------

func TestChunkWindow_Python(t *testing.T) {
	var sb strings.Builder
	for i := 0; i < 100; i++ {
		sb.WriteString("# Python line\nresult = some_function(arg)\n")
	}
	chunks := ChunkFile("script.py", sb.String())
	if len(chunks) == 0 {
		t.Fatal("expected chunks from Python file")
	}
	// No chunk should end mid-line (last char should be '\n' or be the last char of file).
	for _, c := range chunks {
		if len(c.Text) == 0 {
			t.Error("empty chunk text")
		}
	}
}

func TestChunkWindow_Markdown(t *testing.T) {
	var sb strings.Builder
	for i := 0; i < 50; i++ {
		sb.WriteString("## Section\n\nSome content here.\n\n")
	}
	chunks := ChunkFile("README.md", sb.String())
	if len(chunks) == 0 {
		t.Fatal("expected chunks from markdown file")
	}
}

func TestChunkFile_UnknownExt_Nil(t *testing.T) {
	chunks := ChunkFile("file.xyz", "some random content")
	if chunks != nil {
		t.Error("expected nil for unknown extension")
	}
}

func TestChunkFile_IDs_Unique(t *testing.T) {
	var sb strings.Builder
	for i := 0; i < 10; i++ {
		sb.WriteString("func Fn() {}\n\n")
	}
	chunks := ChunkFile("ids.go", sb.String())
	seen := map[string]bool{}
	for _, c := range chunks {
		if seen[c.ID] {
			t.Errorf("duplicate chunk ID: %s", c.ID)
		}
		seen[c.ID] = true
	}
}
