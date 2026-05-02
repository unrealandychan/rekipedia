// Package orchestrator — RunDigest is the full scan pipeline.
package orchestrator

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"time"

	"github.com/google/uuid"
	"github.com/pterm/pterm"
	"golang.org/x/sync/errgroup"

	"github.com/unrealandychan/rekipedia/internal/extractor"
	"github.com/unrealandychan/rekipedia/internal/llm"
	"github.com/unrealandychan/rekipedia/internal/models"
	"github.com/unrealandychan/rekipedia/internal/storage"
	"github.com/unrealandychan/rekipedia/internal/synthesis"
)

const maxShardWorkers = 4

// DigestOptions configures a full scan run.
type DigestOptions struct {
	LLMConfig models.LLMConfig
	Verbose   bool
	Progress  func(string) // optional progress callback (for non-terminal consumers, e.g. web SSE)
	Languages []string     // nil = all languages
}

// RunDigest executes the full scan → plan → generate → export pipeline.
//
// Flow:
//  1. Snapshot repo
//  2. Shard files
//  3. Extract shards in parallel
//  4. Build diagrams
//  5. Plan wiki structure (LLM)
//  6. Generate wiki pages (LLM, concurrent)
//  7. Persist & export
func RunDigest(ctx context.Context, repoRoot, outputDir string, opts DigestOptions) error {
	start := time.Now()
	cb := opts.Progress // optional non-terminal callback

	// ── Header ─────────────────────────────────────────────────────────────
	pterm.DefaultSection.WithLevel(1).Printf("rekipedia scan ▸ %s", repoRoot)
	if cb != nil {
		cb(fmt.Sprintf("rekipedia scan ▸ %s", repoRoot))
	}

	runID := uuid.New().String()
	dbPath := filepath.Join(outputDir, "store.db")

	store, err := storage.Open(dbPath)
	if err != nil {
		return fmt.Errorf("open store: %w", err)
	}
	defer store.Close()

	if err := store.UpsertRun(runID, repoRoot); err != nil {
		return fmt.Errorf("upsert run: %w", err)
	}

	// ── 1. Snapshot ────────────────────────────────────────────────────────
	snapSpinner, _ := pterm.DefaultSpinner.WithText("Snapshotting repository…").Start()
	if cb != nil {
		cb("Snapshotting repository…")
	}
	snapper := NewSnapshotter(repoRoot, nil, opts.Languages)
	files, err := snapper.Snapshot()
	if err != nil {
		snapSpinner.Fail("Snapshot failed")
		return fmt.Errorf("snapshot: %w", err)
	}

	// Count unique languages
	langSet := map[string]struct{}{}
	for _, f := range files {
		if f.Language != "" {
			langSet[f.Language] = struct{}{}
		}
	}
	snapMsg := fmt.Sprintf("%d files found (%d languages)", len(files), len(langSet))
	snapSpinner.Success(snapMsg)
	if cb != nil {
		cb(snapMsg)
	}

	if err := store.UpsertSnapshot(runID, files); err != nil {
		return fmt.Errorf("store snapshot: %w", err)
	}

	// ── 2. Shard ───────────────────────────────────────────────────────────
	shardSpinner, _ := pterm.DefaultSpinner.WithText("Planning shards…").Start()
	if cb != nil {
		cb("Planning shards…")
	}
	planner := NewShardPlanner(0)
	shards := planner.Plan(files)
	shardMsg := fmt.Sprintf("%d shards planned", len(shards))
	shardSpinner.Success(shardMsg)
	if cb != nil {
		cb(shardMsg)
	}

	// ── 3. Extract shards in parallel ──────────────────────────────────────
	if cb != nil {
		cb(fmt.Sprintf("Extracting shards (up to %d parallel)…", maxShardWorkers))
	}
	mergedResults := make([]models.AnalysisResult, len(shards))
	var resultsMu sync.Mutex

	sem := make(chan struct{}, maxShardWorkers)
	eg, egCtx := errgroup.WithContext(ctx)

	reg := extractor.NewRegistry()
	bar, _ := newShardBar(len(shards))

	for i, shard := range shards {
		i, shard := i, shard
		eg.Go(func() error {
			sem <- struct{}{}
			defer func() { <-sem }()

			result, err := extractShard(egCtx, repoRoot, shard, reg)
			resultsMu.Lock()
			defer resultsMu.Unlock()
			bar.Increment()
			if err != nil {
				warnMsg := fmt.Sprintf("shard %s failed: %v", shard.ShardID, err)
				pterm.Warning.Println(warnMsg)
				if cb != nil {
					cb("⚠ " + warnMsg)
				}
				mergedResults[i] = models.AnalysisResult{
					ShardID:     shard.ShardID,
					FilesSeen:   []string{},
					EntryPoints: []string{},
					Risks:       []string{fmt.Sprintf("extraction failed: %v", err)},
				}
				return nil // graceful — don't abort the whole run
			}
			mergedResults[i] = result
			if opts.Verbose {
				pterm.Success.Printf("%s: %d symbols, %d rels\n", shard.ShardID, len(result.Symbols), len(result.Relationships))
			}
			if cb != nil {
				cb(fmt.Sprintf("✓ %s: %d symbols, %d rels", shard.ShardID, len(result.Symbols), len(result.Relationships)))
			}
			return nil
		})
	}
	if err := eg.Wait(); err != nil {
		return err
	}
	bar.Stop()

	// Persist results (SQLite writes must be serial)
	for _, result := range mergedResults {
		if err := store.UpsertSymbols(runID, result.Symbols); err != nil {
			return fmt.Errorf("store symbols: %w", err)
		}
		if err := store.UpsertRelationships(runID, result.Relationships); err != nil {
			return fmt.Errorf("store rels: %w", err)
		}
	}

	// ── 4. Combine + build diagrams ────────────────────────────────────────
	diagSpinner, _ := pterm.DefaultSpinner.WithText("Building diagrams…").Start()
	if cb != nil {
		cb("Building diagrams…")
	}
	combined := combineResults(mergedResults)
	db := synthesis.NewDiagramBuilder()
	diagrams := db.Build(combined.Relationships, combined.EntryPoints)
	diagMsg := fmt.Sprintf("%d diagram(s) built", len(diagrams))
	diagSpinner.Success(diagMsg)
	if cb != nil {
		cb(diagMsg)
	}

	if mg, ok := diagrams["module-graph"]; ok {
		combined.Evidence["pre_built_module_graph"] = mg[1]
	}
	if ch, ok := diagrams["class-hierarchy"]; ok {
		combined.Evidence["pre_built_dependency_graph"] = ch[1]
	}

	// ── 5. Plan wiki structure ─────────────────────────────────────────────
	planSpinner, _ := pterm.DefaultSpinner.WithText("Planning wiki structure (LLM)…").Start()
	if cb != nil {
		cb("Planning wiki structure (LLM)…")
	}
	llmClient := llm.New(opts.LLMConfig)
	wikiPlanner := synthesis.NewPlannerAgent(llmClient)
	plan, err := wikiPlanner.Plan(ctx, combined)
	if err != nil {
		planSpinner.Fail("Wiki planning failed")
		return fmt.Errorf("plan wiki: %w", err)
	}
	planMsg := fmt.Sprintf("%d pages planned", len(plan.Pages))
	planSpinner.Success(planMsg)
	if cb != nil {
		cb(planMsg)
	}

	// ── 6. Generate wiki pages ─────────────────────────────────────────────
	genSpinner, _ := pterm.DefaultSpinner.WithText(fmt.Sprintf("Generating %d wiki pages…", len(plan.Pages))).Start()
	if cb != nil {
		cb(fmt.Sprintf("Generating %d wiki pages…", len(plan.Pages)))
	}
	pageBuilder := synthesis.NewPageBuilder(llmClient)
	diagMap := make(map[string][2]string)
	for k, v := range diagrams {
		diagMap[k] = [2]string(v)
	}
	pages, err := pageBuilder.BuildAll(ctx, plan, combined, diagMap)
	if err != nil {
		genSpinner.Fail("Page generation failed")
		return fmt.Errorf("build pages: %w", err)
	}
	genMsg := fmt.Sprintf("%d pages generated", len(pages))
	genSpinner.Success(genMsg)
	if cb != nil {
		cb(genMsg)
	}

	// ── 7. Persist pages & export ──────────────────────────────────────────
	persistSpinner, _ := pterm.DefaultSpinner.WithText("Persisting pages…").Start()
	if cb != nil {
		cb("Persisting pages…")
	}
	for slug, content := range pages {
		title := slug
		for _, spec := range plan.Pages {
			if spec.Slug == slug {
				title = spec.Title
				break
			}
		}
		if err := store.UpsertPage(runID, slug, title, content); err != nil {
			persistSpinner.Fail("Failed to persist pages")
			return fmt.Errorf("store page %q: %w", slug, err)
		}
	}

	// Export to disk
	wikiDir := filepath.Join(outputDir, "wiki")
	if err := os.MkdirAll(wikiDir, 0o755); err != nil {
		return fmt.Errorf("mkdir wiki: %w", err)
	}
	for slug, content := range pages {
		path := filepath.Join(wikiDir, slug+".md")
		if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
			return fmt.Errorf("write page %q: %w", slug, err)
		}
	}
	persistSpinner.Success("Pages persisted")

	// ── Summary box ────────────────────────────────────────────────────────
	elapsed := time.Since(start).Round(time.Millisecond)
	totalSymbols := 0
	for _, r := range mergedResults {
		totalSymbols += len(r.Symbols)
	}
	summary := fmt.Sprintf(
		"Run ID  : %s\nPages   : %d\nSymbols : %d\nElapsed : %s\nOutput  : %s",
		runID[:8], len(pages), totalSymbols, elapsed, outputDir,
	)
	pterm.DefaultBox.WithTitle("✅ Scan Complete").Println(summary)
	if cb != nil {
		cb(fmt.Sprintf("✅ Done — run %s | %d pages in %s", runID[:8], len(pages), outputDir))
	}

	return nil
}

// ── helpers ───────────────────────────────────────────────────────────────────

func extractShard(_ context.Context, repoRoot string, shard models.Shard, reg *extractor.Registry) (models.AnalysisResult, error) {
	if reg == nil {
		reg = extractor.NewRegistry()
	}
	result := models.AnalysisResult{
		ShardID:   shard.ShardID,
		FilesSeen: make([]string, 0, len(shard.Files)),
		Evidence:  make(map[string]string),
	}

	for _, fm := range shard.Files {
		fullPath := filepath.Join(repoRoot, fm.Path)
		ext := filepath.Ext(fm.Path)
		ar := reg.ExtractFile(fullPath, fm.Path, ext)
		result.FilesSeen = append(result.FilesSeen, fm.Path)
		result = mergeInto(result, ar)
	}
	return result, nil
}

func mergeInto(base, extra models.AnalysisResult) models.AnalysisResult {
	base.Symbols = append(base.Symbols, extra.Symbols...)
	base.Relationships = append(base.Relationships, extra.Relationships...)
	base.EntryPoints = append(base.EntryPoints, extra.EntryPoints...)
	base.BuildCommands = append(base.BuildCommands, extra.BuildCommands...)
	base.TestCommands = append(base.TestCommands, extra.TestCommands...)
	base.Risks = append(base.Risks, extra.Risks...)
	for k, v := range extra.Evidence {
		base.Evidence[k] = v
	}
	return base
}

func combineResults(results []models.AnalysisResult) models.AnalysisResult {
	combined := models.AnalysisResult{Evidence: make(map[string]string)}
	for _, r := range results {
		combined.FilesSeen = append(combined.FilesSeen, r.FilesSeen...)
		combined.Symbols = append(combined.Symbols, r.Symbols...)
		combined.Relationships = append(combined.Relationships, r.Relationships...)
		combined.EntryPoints = append(combined.EntryPoints, r.EntryPoints...)
		combined.BuildCommands = append(combined.BuildCommands, r.BuildCommands...)
		combined.TestCommands = append(combined.TestCommands, r.TestCommands...)
		combined.Risks = append(combined.Risks, r.Risks...)
		for k, v := range r.Evidence {
			combined.Evidence[k] = v
		}
	}
	return combined
}

// progressLogger is kept for compatibility with the web server (SSE streaming).
// Terminal output is handled directly by pterm in RunDigest.
type progressLogger struct {
	cb      func(string)
	verbose bool
}

func newProgressLogger(cb func(string), verbose bool) *progressLogger {
	return &progressLogger{cb: cb, verbose: verbose}
}

func (l *progressLogger) logf(format string, args ...any) {
	if l.cb != nil {
		l.cb(fmt.Sprintf(format, args...))
	}
}

// newShardBar creates a pterm progress bar for shard processing.
func newShardBar(total int) (*pterm.ProgressbarPrinter, error) {
	return pterm.DefaultProgressbar.
		WithTotal(total).
		WithTitle("Extracting shards").
		WithRemoveWhenDone(true).
		Start()
}
