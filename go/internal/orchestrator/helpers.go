// Package orchestrator — shared finish step for digest and update pipelines.
package orchestrator

import (
	"context"
	"fmt"
	"os"
	"path/filepath"

	"github.com/unrealandychan/rekipedia/internal/llm"
	"github.com/unrealandychan/rekipedia/internal/models"
	"github.com/unrealandychan/rekipedia/internal/storage"
	"github.com/unrealandychan/rekipedia/internal/synthesis"
)

// finishDigest runs phases 4–7 (diagrams → plan → pages → export).
// Used by both RunDigest and RunUpdate to avoid duplication.
func finishDigest(
	ctx context.Context,
	store *storage.Store,
	runID, outputDir string,
	combined models.AnalysisResult,
	llmCfg models.LLMConfig,
	log *progressLogger,
) error {
	// ── 4. Build diagrams ───────────────────────────────────────────────────
	log.logf("Building diagrams…")
	db := synthesis.NewDiagramBuilder()
	diagrams := db.Build(combined.Relationships, combined.EntryPoints)
	log.logf("  %d diagram(s) built", len(diagrams))

	if mg, ok := diagrams["module-graph"]; ok {
		combined.Evidence["pre_built_module_graph"] = mg[1]
	}
	if ch, ok := diagrams["class-hierarchy"]; ok {
		combined.Evidence["pre_built_dependency_graph"] = ch[1]
	}

	// ── 5. Plan wiki structure ──────────────────────────────────────────────
	log.logf("Planning wiki structure…")
	llmClient := llm.New(llmCfg)
	wikiPlanner := synthesis.NewPlannerAgent(llmClient)
	plan, err := wikiPlanner.Plan(ctx, combined)
	if err != nil {
		return fmt.Errorf("plan wiki: %w", err)
	}
	log.logf("  %d pages planned", len(plan.Pages))

	// ── 6. Generate wiki pages ──────────────────────────────────────────────
	log.logf("Generating wiki pages…")
	pageBuilder := synthesis.NewPageBuilder(llmClient)
	diagMap := make(map[string][2]string)
	for k, v := range diagrams {
		diagMap[k] = [2]string(v)
	}
	pages, err := pageBuilder.BuildAll(ctx, plan, combined, diagMap)
	if err != nil {
		return fmt.Errorf("build pages: %w", err)
	}
	log.logf("  %d pages generated", len(pages))

	// ── 7. Persist & export ─────────────────────────────────────────────────
	log.logf("Persisting pages…")
	titleFor := func(slug string) string {
		for _, spec := range plan.Pages {
			if spec.Slug == slug {
				return spec.Title
			}
		}
		return slug
	}
	for slug, content := range pages {
		if err := store.UpsertPage(runID, slug, titleFor(slug), content); err != nil {
			return fmt.Errorf("store page %q: %w", slug, err)
		}
	}

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

	log.logf("✅ Done — run %s | %d pages in %s", runID[:8], len(pages), outputDir)
	return nil
}
