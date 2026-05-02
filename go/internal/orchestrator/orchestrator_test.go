package orchestrator

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/unrealandychan/rekipedia/internal/models"
)

// ── Snapshotter tests ─────────────────────────────────────────────────────────

func TestSnapshotterBasic(t *testing.T) {
	dir := t.TempDir()
	// Create some files
	must(t, os.WriteFile(filepath.Join(dir, "main.go"), []byte("package main"), 0o644))
	must(t, os.WriteFile(filepath.Join(dir, "README.md"), []byte("# Hello"), 0o644))
	must(t, os.MkdirAll(filepath.Join(dir, "src"), 0o755))
	must(t, os.WriteFile(filepath.Join(dir, "src", "app.go"), []byte("package app"), 0o644))

	snapper := NewSnapshotter(dir, nil, nil)
	files, err := snapper.Snapshot()
	if err != nil {
		t.Fatalf("Snapshot error: %v", err)
	}
	if len(files) != 3 {
		t.Errorf("expected 3 files, got %d", len(files))
	}
}

func TestSnapshotterIgnoresGit(t *testing.T) {
	dir := t.TempDir()
	must(t, os.MkdirAll(filepath.Join(dir, ".git"), 0o755))
	must(t, os.WriteFile(filepath.Join(dir, ".git", "HEAD"), []byte("ref: refs/heads/main"), 0o644))
	must(t, os.WriteFile(filepath.Join(dir, "main.go"), []byte("package main"), 0o644))

	snapper := NewSnapshotter(dir, nil, nil)
	files, err := snapper.Snapshot()
	if err != nil {
		t.Fatalf("Snapshot error: %v", err)
	}
	for _, f := range files {
		if filepath.HasPrefix(f.Path, ".git") {
			t.Errorf("should not include .git files, got %q", f.Path)
		}
	}
	if len(files) != 1 {
		t.Errorf("expected 1 file (main.go), got %d: %v", len(files), files)
	}
}

func TestSnapshotterIgnoresNodeModules(t *testing.T) {
	dir := t.TempDir()
	must(t, os.MkdirAll(filepath.Join(dir, "node_modules", "pkg"), 0o755))
	must(t, os.WriteFile(filepath.Join(dir, "node_modules", "pkg", "index.js"), []byte("module.exports={}"), 0o644))
	must(t, os.WriteFile(filepath.Join(dir, "index.ts"), []byte("export {}"), 0o644))

	snapper := NewSnapshotter(dir, nil, nil)
	files, err := snapper.Snapshot()
	if err != nil {
		t.Fatalf("Snapshot error: %v", err)
	}
	if len(files) != 1 {
		t.Errorf("expected 1 file, got %d", len(files))
	}
}

func TestSnapshotterLanguageDetection(t *testing.T) {
	dir := t.TempDir()
	must(t, os.WriteFile(filepath.Join(dir, "app.py"), []byte("print('hi')"), 0o644))
	must(t, os.WriteFile(filepath.Join(dir, "main.go"), []byte("package main"), 0o644))
	must(t, os.WriteFile(filepath.Join(dir, "Dockerfile"), []byte("FROM alpine"), 0o644))
	must(t, os.WriteFile(filepath.Join(dir, "infra.tf"), []byte("resource {}"), 0o644))

	snapper := NewSnapshotter(dir, nil, nil)
	files, err := snapper.Snapshot()
	if err != nil {
		t.Fatalf("Snapshot error: %v", err)
	}
	langMap := make(map[string]string)
	for _, f := range files {
		langMap[f.Path] = f.Language
	}
	cases := map[string]string{
		"app.py":     "python",
		"main.go":    "go",
		"Dockerfile": "docker",
		"infra.tf":   "terraform",
	}
	for path, wantLang := range cases {
		if got := langMap[path]; got != wantLang {
			t.Errorf("language(%q) = %q, want %q", path, got, wantLang)
		}
	}
}

func TestSnapshotterSHA256Stable(t *testing.T) {
	dir := t.TempDir()
	content := []byte("hello world")
	must(t, os.WriteFile(filepath.Join(dir, "file.txt"), content, 0o644))

	snapper := NewSnapshotter(dir, nil, nil)
	files1, _ := snapper.Snapshot()
	files2, _ := snapper.Snapshot()
	if len(files1) == 0 || len(files2) == 0 {
		t.Fatal("expected at least 1 file")
	}
	if files1[0].SHA256 != files2[0].SHA256 {
		t.Error("SHA256 should be stable across two snapshots of the same file")
	}
}

func TestSnapshotterExtraIgnore(t *testing.T) {
	dir := t.TempDir()
	must(t, os.WriteFile(filepath.Join(dir, "main.go"), []byte("package main"), 0o644))
	must(t, os.WriteFile(filepath.Join(dir, "secret.key"), []byte("supersecret"), 0o644))

	snapper := NewSnapshotter(dir, []string{"*.key"}, nil)
	files, _ := snapper.Snapshot()
	for _, f := range files {
		if filepath.Ext(f.Path) == ".key" {
			t.Errorf("should have ignored *.key file, got %q", f.Path)
		}
	}
}

// ── ShardPlanner tests ────────────────────────────────────────────────────────

func makeManifests(paths []string) []models.FileManifest {
	mfs := make([]models.FileManifest, len(paths))
	for i, p := range paths {
		mfs[i] = models.FileManifest{Path: p, SizeBytes: 1000}
	}
	return mfs
}

func TestShardPlannerEmpty(t *testing.T) {
	sp := NewShardPlanner(0)
	shards := sp.Plan(nil)
	if len(shards) != 0 {
		t.Errorf("expected 0 shards for empty input, got %d", len(shards))
	}
}

func TestShardPlannerSingleDir(t *testing.T) {
	files := makeManifests([]string{"src/a.py", "src/b.py", "src/c.py"})
	sp := NewShardPlanner(100000) // large budget → 1 shard
	shards := sp.Plan(files)
	if len(shards) != 1 {
		t.Errorf("expected 1 shard, got %d", len(shards))
	}
	if shards[0].Root != "src" {
		t.Errorf("expected root='src', got %q", shards[0].Root)
	}
}

func TestShardPlannerSplitsOnBudget(t *testing.T) {
	// Each file is 1000 bytes = 250 tokens; budget = 400 → max 1 file per shard
	files := makeManifests([]string{"src/a.py", "src/b.py", "src/c.py"})
	sp := NewShardPlanner(400)
	shards := sp.Plan(files)
	if len(shards) < 2 {
		t.Errorf("expected multiple shards with tight budget, got %d", len(shards))
	}
}

func TestShardPlannerMultipleDirs(t *testing.T) {
	files := makeManifests([]string{
		"src/a.py", "src/b.py",
		"tests/test_a.py",
		"docs/readme.md",
	})
	sp := NewShardPlanner(100000)
	shards := sp.Plan(files)
	// Should have at least 3 shards (one per top-level dir)
	if len(shards) < 3 {
		t.Errorf("expected ≥3 shards for 3 dirs, got %d", len(shards))
	}
}

func TestShardPlannerRootFiles(t *testing.T) {
	files := makeManifests([]string{"Makefile", "README.md", "go.mod"})
	sp := NewShardPlanner(100000)
	shards := sp.Plan(files)
	if len(shards) != 1 {
		t.Errorf("expected 1 shard for root-only files, got %d", len(shards))
	}
	if shards[0].Root != "." {
		t.Errorf("expected root='.', got %q", shards[0].Root)
	}
}

func TestShardPlannerShardIDs(t *testing.T) {
	// Tiny budget forces many shards in same dir → IDs should be unique
	files := make([]models.FileManifest, 5)
	for i := range files {
		files[i] = models.FileManifest{Path: "src/file.py", SizeBytes: 10000}
	}
	sp := NewShardPlanner(100) // forces split at every file
	shards := sp.Plan(files)
	seen := make(map[string]bool)
	for _, s := range shards {
		if seen[s.ShardID] {
			t.Errorf("duplicate shard ID: %q", s.ShardID)
		}
		seen[s.ShardID] = true
	}
}

// ── helper ────────────────────────────────────────────────────────────────────

func must(t *testing.T, err error) {
	t.Helper()
	if err != nil {
		t.Fatal(err)
	}
}
