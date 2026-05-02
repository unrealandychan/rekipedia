// Package orchestrator — RunUpdate is the incremental update pipeline.
package orchestrator

import (
	"context"
	"fmt"
	"path/filepath"

	"github.com/google/uuid"

	"github.com/unrealandychan/rekipedia/internal/models"
	"github.com/unrealandychan/rekipedia/internal/storage"
)

// UpdateOptions configures an incremental update run.
type UpdateOptions struct {
	LLMConfig models.LLMConfig
	Progress  func(string)
	Languages []string // nil = all languages
}

// RunUpdate performs an incremental update:
//  1. Find the last successful scan for this repo.
//  2. If none → fall back to RunDigest (full scan).
//  3. Snapshot repo; diff against stored file hashes.
//  4. If nothing changed → report up-to-date and return early.
//  5. Re-extract only changed shards.
//  6. Carry forward symbols/relationships for unchanged files.
//  7. Re-synthesise all wiki pages (full context always needed).
func RunUpdate(ctx context.Context, repoRoot, outputDir string, opts UpdateOptions) error {
	log := newProgressLogger(opts.Progress, false)
	dbPath := filepath.Join(outputDir, "store.db")

	store, err := storage.Open(dbPath)
	if err != nil {
		// No DB — fall back to full scan
		log.logf("No knowledge store found — running full scan…")
		return RunDigest(ctx, repoRoot, outputDir, DigestOptions{
			LLMConfig: opts.LLMConfig,
			Progress:  opts.Progress,
			Languages: opts.Languages,
		})
	}
	defer store.Close()

	// ── 1. Find last successful run ────────────────────────────────────────
	lastRunID, err := store.GetLatestRunID(repoRoot)
	if err != nil || lastRunID == "" {
		log.logf("No previous scan found — running full scan…")
		store.Close()
		return RunDigest(ctx, repoRoot, outputDir, DigestOptions{
			LLMConfig: opts.LLMConfig,
			Progress:  opts.Progress,
			Languages: opts.Languages,
		})
	}
	log.logf("Last run: %s", lastRunID[:8])

	// ── 2. Snapshot current state ──────────────────────────────────────────
	log.logf("Snapshotting repository…")
	snapper := NewSnapshotter(repoRoot, nil, opts.Languages)
	currentFiles, err := snapper.Snapshot()
	if err != nil {
		return fmt.Errorf("snapshot: %w", err)
	}

	// ── 3. Diff against stored hashes ──────────────────────────────────────
	storedFiles, err := store.GetSnapshot(lastRunID)
	if err != nil {
		storedFiles = nil
	}
	storedHashes := make(map[string]string, len(storedFiles))
	for _, f := range storedFiles {
		storedHashes[f.Path] = f.SHA256
	}

	var changedFiles []models.FileManifest
	var unchangedFiles []models.FileManifest
	currentSet := make(map[string]bool)
	for _, f := range currentFiles {
		currentSet[f.Path] = true
		if storedHashes[f.Path] != f.SHA256 {
			changedFiles = append(changedFiles, f)
		} else {
			unchangedFiles = append(unchangedFiles, f)
		}
	}

	// Detect deleted files
	for _, f := range storedFiles {
		if !currentSet[f.Path] {
			changedFiles = append(changedFiles, f) // deleted — trigger re-synthesis
		}
	}

	if len(changedFiles) == 0 {
		log.logf("✅ Repository is up-to-date — nothing changed.")
		return nil
	}
	log.logf("  %d changed / %d unchanged files", len(changedFiles), len(unchangedFiles))

	// ── 4. Create new run ──────────────────────────────────────────────────
	newRunID := uuid.New().String()
	if err := store.UpsertRun(newRunID, repoRoot); err != nil {
		return fmt.Errorf("upsert run: %w", err)
	}
	if err := store.UpsertSnapshot(newRunID, currentFiles); err != nil {
		return fmt.Errorf("store snapshot: %w", err)
	}

	// ── 5. Carry forward unchanged symbols/relationships ───────────────────
	log.logf("Carrying forward unchanged results…")
	unchangedPaths := make(map[string]bool)
	for _, f := range unchangedFiles {
		unchangedPaths[f.Path] = true
	}

	oldSymbols, _ := store.GetAllSymbols(lastRunID)
	oldRels, _ := store.GetAllRelationships(lastRunID)

	var keptSymbols []models.Symbol
	var keptRels []models.Relationship
	for _, s := range oldSymbols {
		if unchangedPaths[s.File] {
			keptSymbols = append(keptSymbols, s)
		}
	}
	for _, r := range oldRels {
		if unchangedPaths[r.From] && unchangedPaths[r.To] {
			keptRels = append(keptRels, r)
		}
	}
	log.logf("  Kept %d symbols, %d relationships from unchanged files", len(keptSymbols), len(keptRels))

	// ── 6. Re-extract changed shards ──────────────────────────────────────
	log.logf("Re-extracting %d changed shards…", len(changedFiles))
	shardPlanner := NewShardPlanner(0)
	shards := shardPlanner.Plan(changedFiles)

	var newResults []models.AnalysisResult
	for _, shard := range shards {
		result, err := extractShard(ctx, repoRoot, shard, nil)
		if err != nil {
			log.logf("  ⚠ shard %s failed: %v", shard.ShardID, err)
			continue
		}
		newResults = append(newResults, result)
	}

	// ── 7. Build combined result ───────────────────────────────────────────
	allFiles := append(unchangedFiles, changedFiles...)
	combined := models.AnalysisResult{
		FilesSeen: func() []string {
			ss := make([]string, len(allFiles))
			for i, f := range allFiles {
				ss[i] = f.Path
			}
			return ss
		}(),
		Symbols:       keptSymbols,
		Relationships: keptRels,
		Evidence:      make(map[string]string),
	}
	for _, r := range newResults {
		combined = mergeInto(combined, r)
	}

	// Persist new symbols/rels
	if err := store.UpsertSymbols(newRunID, combined.Symbols); err != nil {
		return fmt.Errorf("store symbols: %w", err)
	}
	if err := store.UpsertRelationships(newRunID, combined.Relationships); err != nil {
		return fmt.Errorf("store rels: %w", err)
	}

	// ── 8. Re-synthesise (full context always needed) ─────────────────────
	log.logf("Re-synthesising wiki pages…")
	return finishDigest(ctx, store, newRunID, outputDir, combined, opts.LLMConfig, log)
}
