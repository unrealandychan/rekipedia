// Package synthesis — PageBuilder generates wiki page content via LLM.
package synthesis

import (
	"context"
	"encoding/json"
	"fmt"
	"sort"
	"strings"

	"golang.org/x/sync/errgroup"

	"github.com/unrealandychan/rekipedia/internal/llm"
	"github.com/unrealandychan/rekipedia/internal/models"
)

const pageSystemPrompt = `You are a senior technical writer creating documentation for a software repository. Write a single wiki page in clean Markdown.

Rules:
- Use ## for main sections, ### for subsections
- Include Mermaid diagrams where specified (fenced with ` + "```mermaid" + `)
- Use inline code for symbol names: ` + "`SymbolName`" + `
- Cite source files as [SymbolName](path/to/file.go#Lxx)
- Write for developers — assume Go/Python/JS familiarity
- Be precise and grounded in the provided data
- Do NOT add a title (H1) — that will be added by the renderer
- Do NOT include commentary about the task itself`

// pageExtraFocus holds additional per-slug focus instructions injected into the prompt.
var pageExtraFocus = map[string]string{
	"technical-debt": `Analyse and document all technical debt found in this codebase. Include:
## Summary
A 2–3 sentence executive summary of the overall technical health. Give an overall debt rating: Low / Medium / High / Critical.
## Debt Inventory
A prioritised table:
| # | Area | Severity | Description | Files Affected | Effort to Fix |
|---|------|----------|-------------|----------------|---------------|
Severity: 🔴 Critical / 🟠 High / 🟡 Medium / 🟢 Low. Effort: S (<1d) / M (1-3d) / L (1-2w) / XL (>2w).
## Critical Issues
For each Critical/High item: file references, the problematic pattern, why it matters, and a concrete fix suggestion.
## Code Smell Patterns
Recurring anti-patterns (God classes, deep nesting, duplicated logic, missing error handling, hardcoded values). Show a real example and recommended refactor.
## Missing Tests
Areas with insufficient coverage. List specific modules/functions lacking tests.
## Dependency & Security Concerns
Outdated or risky dependencies from go.mod / pyproject.toml / package.json.
## TODO / FIXME Tracker
Every TODO, FIXME, HACK, XXX comment found:
| File | Comment | Suggested Action |
|------|---------|-----------------|
## Refactoring Roadmap
| Priority | Action | Rationale | Estimated Effort |
|----------|--------|-----------|-----------------|
Do NOT fabricate issues — only report what is evidenced in the provided data.`,
}

const maxPageWorkers = 4

// PageBuilder builds wiki pages concurrently via the LLM.
type PageBuilder struct {
	client *llm.Client
}

// NewPageBuilder creates a PageBuilder backed by the given LLM client.
func NewPageBuilder(client *llm.Client) *PageBuilder {
	return &PageBuilder{client: client}
}

// BuildAll generates content for all pages in the plan concurrently.
// Returns map[slug]content.
func (b *PageBuilder) BuildAll(ctx context.Context, plan models.WikiPlan, result models.AnalysisResult, diagrams map[string][2]string) (map[string]string, error) {
	payload := buildPayload(result, diagrams)

	// Semaphore: max maxPageWorkers concurrent LLM calls
	type result_ struct {
		slug    string
		content string
	}
	resultCh := make(chan result_, len(plan.Pages))

	sem := make(chan struct{}, maxPageWorkers)
	eg, ctx := errgroup.WithContext(ctx)

	for _, spec := range plan.Pages {
		spec := spec // capture
		eg.Go(func() error {
			sem <- struct{}{}
			defer func() { <-sem }()

			content, err := b.BuildPage(ctx, spec, payload)
			if err != nil {
				// Don't fail the whole run — use a placeholder
				content = fmt.Sprintf("*Page generation failed: %v*\n", err)
			}
			resultCh <- result_{slug: spec.Slug, content: content}
			return nil
		})
	}

	if err := eg.Wait(); err != nil {
		return nil, err
	}
	close(resultCh)

	pages := make(map[string]string)
	for r := range resultCh {
		pages[r.slug] = r.content
	}
	return pages, nil
}

// BuildPage generates content for a single wiki page.
func (b *PageBuilder) BuildPage(ctx context.Context, spec models.WikiPageSpec, payload map[string]any) (string, error) {
	sliced := slicePayload(payload, spec.RequiredData)
	payloadJSON, _ := json.Marshal(sliced)

	focus := spec.Focus
	if extra, ok := pageExtraFocus[spec.Slug]; ok {
		focus = extra + "\n\n" + focus
	}

	prompt := fmt.Sprintf(
		"## Page to write\nSlug: %s\nTitle: %s\nSection: %s\nImportance: %d\n\nFocus instructions:\n%s\n\n## Repository data\n\n```json\n%s\n```",
		spec.Slug, spec.Title, spec.Section, spec.Importance, focus, string(payloadJSON),
	)

	content, err := b.client.Call(ctx, pageSystemPrompt, prompt)
	if err != nil {
		return "", fmt.Errorf("build page %q: %w", spec.Slug, err)
	}
	return strings.TrimSpace(content), nil
}

// ── payload construction ──────────────────────────────────────────────────────

// buildPayload creates the full repository data payload for page generation.
func buildPayload(result models.AnalysisResult, diagrams map[string][2]string) map[string]any {
	// Symbol table: group by kind
	symbolTable := make(map[string][]map[string]any)
	for _, sym := range result.Symbols {
		kind := string(sym.Kind)
		symbolTable[kind] = append(symbolTable[kind], map[string]any{
			"name":      sym.Name,
			"file":      sym.File,
			"line":      sym.LineStart,
			"signature": sym.Signature,
			"docstring": sym.Docstring,
		})
	}

	// Top symbols sample (max 100)
	topSymbols := make([]map[string]any, 0, 100)
	for _, sym := range result.Symbols {
		if len(topSymbols) >= 100 {
			break
		}
		topSymbols = append(topSymbols, map[string]any{
			"name": sym.Name,
			"kind": string(sym.Kind),
			"file": sym.File,
			"line": sym.LineStart,
		})
	}

	// Relationship summary
	relSummary := make([]map[string]any, 0, 200)
	for i, rel := range result.Relationships {
		if i >= 200 {
			break
		}
		relSummary = append(relSummary, map[string]any{
			"from": rel.From, "to": rel.To, "kind": string(rel.Kind),
		})
	}

	// File list (sorted)
	files := make([]string, len(result.FilesSeen))
	copy(files, result.FilesSeen)
	sort.Strings(files)

	// Diagrams
	diagramData := make(map[string]string)
	for name, d := range diagrams {
		diagramData[name] = fmt.Sprintf("```mermaid\n%s\n```", d[1])
	}

	return map[string]any{
		"files_seen":       files,
		"entry_points":     result.EntryPoints,
		"symbols":          topSymbols,
		"symbol_table":     symbolTable,
		"relationships":    relSummary,
		"build_commands":   result.BuildCommands,
		"test_commands":    result.TestCommands,
		"risks":            result.Risks,
		"evidence":         result.Evidence,
		"diagrams":         diagramData,
		"symbol_count":     len(result.Symbols),
		"file_count":       len(result.FilesSeen),
		"relationship_count": len(result.Relationships),
	}
}

// slicePayload returns only the keys listed in requiredData (plus always-included keys).
// If requiredData is empty, returns the full payload.
func slicePayload(full map[string]any, requiredData []string) map[string]any {
	alwaysInclude := map[string]bool{
		"file_count": true, "symbol_count": true,
		"relationship_count": true, "entry_points": true,
		"build_commands": true, "test_commands": true,
	}

	if len(requiredData) == 0 {
		return full
	}

	sliced := make(map[string]any)
	for _, key := range requiredData {
		if v, ok := full[key]; ok {
			sliced[key] = v
		}
	}
	for key := range alwaysInclude {
		if v, ok := full[key]; ok {
			sliced[key] = v
		}
	}
	return sliced
}
