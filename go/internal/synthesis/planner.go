// Package synthesis provides the PlannerAgent, PageBuilder, and DiagramBuilder
// for rekipedia's wiki generation pipeline.
package synthesis

import (
	"context"
	"encoding/json"
	"fmt"
	"regexp"
	"sort"
	"strings"

	"github.com/unrealandychan/rekipedia/internal/llm"
	"github.com/unrealandychan/rekipedia/internal/models"
	"github.com/unrealandychan/rekipedia/pkg/fsutil"
)

const plannerSystemPrompt = `You are a technical documentation architect for software repositories. Your task: analyse a repo's static-analysis data and design the OPTIMAL wiki structure — like DeepWiki does for open-source projects.

Output a single JSON object — no markdown fences, no commentary:

{
  "sections": [
    {"id": "getting-started", "title": "Getting Started", "pages": ["index", "installation"]}
  ],
  "pages": [
    {
      "slug": "lowercase-hyphenated",
      "title": "Human Readable Title",
      "section": "section-id",
      "priority": 1,
      "importance": 90,
      "focus": "Very detailed instruction: exact sections to write, what tables/diagrams to include, which symbols to document.",
      "required_data": ["files_seen"],
      "tags": ["overview"]
    }
  ],
  "nav_order": ["slug1", "slug2"],
  "index_slug": "index"
}

## importance field (0–100):
- 95–100: index, architecture-overview (always-read pages)
- 80–94: core-module pages, data-flow, repository-structure
- 60–79: api-reference, configuration, testing
- 40–59: internals, algorithms, contributing
- 20–39: ecosystem, deployment, third-party integrations

## Section design:
Group pages into logical sections. Only create sections that have ≥2 pages.

Common sections: getting-started, architecture, core-components, api-reference, internals, development, ecosystem.

## Always include (if data supports):
- ` + "`index`" + `: Project overview, key features, quick-start, repo structure tree
|- ` + "`repository-structure`" + `: Full repo layout with annotations (REQUIRED if file_count >= 10)
- ` + "`architecture-overview`" + `: System diagram (Mermaid flowchart LR), component responsibilities, design decisions, data flow
- ` + "`technical-debt`" + `: ALWAYS include this page. Analyse TODO/FIXME comments, code smells, missing tests, risky dependencies, anti-patterns. Importance: 70. Section: development. required_data: ["symbols", "files_seen", "relationships"]

## Page splitting rules:
- ≥5 major top-level modules → one page PER module
- Each page: 400–1200 words. Too long = split. Too short = merge.
- Large repos → 10–15 pages; medium → 6–10 pages; small tools → 3–5 pages
- Use ` + "`impl_file_count`" + ` for complexity: high = more core-component pages
- Skip ` + "`testing`" + ` page if test_file_count < 3
- Skip ` + "`configuration`" + ` page if config_file_count < 2

## Focus instructions:
For each page, write a detailed focus (3–6 sentences) specifying:
1. Exact headings to include
2. Tables to build
3. Mermaid diagrams
4. Symbols to document with source citations [ClassName](file#Lxx)
5. What NOT to include`

// PlannerAgent decides the wiki structure from analysis data.
type PlannerAgent struct {
	client *llm.Client
}

// NewPlannerAgent creates a PlannerAgent backed by the given LLM client.
func NewPlannerAgent(client *llm.Client) *PlannerAgent {
	return &PlannerAgent{client: client}
}

// Plan analyses the AnalysisResult and returns a WikiPlan.
// Falls back to a heuristic plan if the LLM fails or returns invalid JSON.
func (p *PlannerAgent) Plan(ctx context.Context, result models.AnalysisResult) (models.WikiPlan, error) {
	summary := buildPlanningSummary(result)

	prompt := fmt.Sprintf(
		"Repository analysis data:\n\n%s\n\nDesign the wiki structure for this repository.",
		marshalSummary(summary),
	)

	raw, err := p.client.Call(ctx, plannerSystemPrompt, prompt)
	if err != nil {
		return fallbackPlan(result), nil // graceful degradation
	}

	plan, err := parsePlanJSON(raw)
	if err != nil {
		return fallbackPlan(result), nil
	}

	// Sort nav_order by importance desc
	pageImportance := make(map[string]int)
	for _, pg := range plan.Pages {
		pageImportance[pg.Slug] = pg.Importance
	}
	sort.SliceStable(plan.NavOrder, func(i, j int) bool {
		return pageImportance[plan.NavOrder[i]] > pageImportance[plan.NavOrder[j]]
	})

	return plan, nil
}

// ── planning summary ─────────────────────────────────────────────────────────

type planningSummary struct {
	FileCount       int               `json:"file_count"`
	ImplFileCount   int               `json:"impl_file_count"`
	TestFileCount   int               `json:"test_file_count"`
	ConfigFileCount int               `json:"config_file_count"`
	SymbolCount     int               `json:"symbol_count"`
	SymbolKinds     map[string]int    `json:"symbol_kinds"`
	SymbolSample    []string          `json:"symbol_sample"`
	TopLevelDirs    []string          `json:"top_level_dirs"`
	EntryPoints     []string          `json:"entry_points"`
	HasTests        bool              `json:"has_tests"`
	HasCLI          bool              `json:"has_cli"`
	HasConfig       bool              `json:"has_config"`
	RelationshipCount int             `json:"relationship_count"`
	BuildCommands   []string          `json:"build_commands"`
	TestCommands    []string          `json:"test_commands"`
	Evidence        map[string]string `json:"evidence,omitempty"`
}

func buildPlanningSummary(result models.AnalysisResult) planningSummary {
	cats := fsutil.CategoriseFiles(result.FilesSeen)

	// Symbol kinds histogram
	kindCounts := make(map[string]int)
	var sampleNames []string
	for _, sym := range result.Symbols {
		kindCounts[string(sym.Kind)]++
		if len(sampleNames) < 80 {
			sampleNames = append(sampleNames, sym.Name)
		}
	}

	// Top-level dirs
	dirSet := make(map[string]bool)
	for _, f := range result.FilesSeen {
		parts := strings.SplitN(f, "/", 2)
		if len(parts) > 1 {
			dirSet[parts[0]] = true
		}
	}
	var topDirs []string
	for d := range dirSet {
		topDirs = append(topDirs, d)
	}
	sort.Strings(topDirs)

	// Heuristics
	hasCLI := false
	for _, ep := range result.EntryPoints {
		if strings.Contains(ep, "cli") || strings.Contains(ep, "main") || strings.Contains(ep, "cmd") {
			hasCLI = true
			break
		}
	}
	hasConfig := len(result.BuildCommands) > 0 || cats.Config >= 2

	return planningSummary{
		FileCount:       len(result.FilesSeen),
		ImplFileCount:   cats.Impl,
		TestFileCount:   cats.Test,
		ConfigFileCount: cats.Config,
		SymbolCount:     len(result.Symbols),
		SymbolKinds:     kindCounts,
		SymbolSample:    sampleNames,
		TopLevelDirs:    topDirs,
		EntryPoints:     dedup(result.EntryPoints),
		HasTests:        cats.Test >= 3,
		HasCLI:          hasCLI,
		HasConfig:       hasConfig,
		RelationshipCount: len(result.Relationships),
		BuildCommands:   dedup(result.BuildCommands),
		TestCommands:    dedup(result.TestCommands),
		Evidence:        result.Evidence,
	}
}

// ── JSON parsing ─────────────────────────────────────────────────────────────

var reFenceStrip = regexp.MustCompile("(?s)```(?:json)?\\s*(.*?)```")

func parsePlanJSON(raw string) (models.WikiPlan, error) {
	// Strip markdown code fences if present
	if m := reFenceStrip.FindStringSubmatch(raw); m != nil {
		raw = m[1]
	}
	// Find JSON object boundaries
	start := strings.Index(raw, "{")
	end := strings.LastIndex(raw, "}")
	if start == -1 || end == -1 || end <= start {
		return models.WikiPlan{}, fmt.Errorf("no JSON object found in planner response")
	}
	raw = raw[start : end+1]

	var plan models.WikiPlan
	if err := json.Unmarshal([]byte(raw), &plan); err != nil {
		return models.WikiPlan{}, fmt.Errorf("parse plan JSON: %w", err)
	}
	if len(plan.Pages) == 0 {
		return models.WikiPlan{}, fmt.Errorf("planner returned zero pages")
	}
	return plan, nil
}

// ── fallback plan ────────────────────────────────────────────────────────────

// fallbackPlan generates a minimal 3–5 page plan without LLM.
func fallbackPlan(result models.AnalysisResult) models.WikiPlan {
	cats := fsutil.CategoriseFiles(result.FilesSeen)

	pages := []models.WikiPageSpec{
		{
			Slug: "index", Title: "Overview", Section: "getting-started",
			Priority: 1, Importance: 100,
			Focus:        "Project overview, key features, quick start, and repository structure.",
			RequiredData: []string{"files_seen", "entry_points", "build_commands"},
			Tags:         []string{"overview"},
		},
		{
			Slug: "architecture-overview", Title: "Architecture Overview", Section: "architecture",
			Priority: 2, Importance: 90,
			Focus:        "System architecture diagram, component responsibilities, data flow.",
			RequiredData: []string{"symbols", "relationships", "entry_points"},
			Tags:         []string{"architecture"},
		},
	}

	if len(result.Symbols) > 10 {
		pages = append(pages, models.WikiPageSpec{
			Slug: "core-modules", Title: "Core Modules", Section: "architecture",
			Priority: 3, Importance: 80,
			Focus:        "Document each major module: purpose, public API, key symbols.",
			RequiredData: []string{"symbols", "files_seen"},
			Tags:         []string{"modules"},
		})
	}

	if cats.Test >= 3 {
		pages = append(pages, models.WikiPageSpec{
			Slug: "testing", Title: "Testing", Section: "development",
			Priority: 4, Importance: 60,
			Focus:        "Test structure, how to run tests, coverage.",
			RequiredData: []string{"test_commands"},
			Tags:         []string{"testing"},
		})
	}

	// Always add technical-debt page
	pages = append(pages, models.WikiPageSpec{
		Slug: "technical-debt", Title: "Technical Debt", Section: "development",
		Priority: 5, Importance: 70,
		Focus:        "Analyse TODO/FIXME comments, code smells, missing tests, risky dependencies, anti-patterns. Produce a prioritised debt inventory table with severity + effort estimates. Include a refactoring roadmap.",
		RequiredData: []string{"symbols", "files_seen", "relationships"},
		Tags:         []string{"internals", "contributing"},
	})

	sections := []models.WikiSection{
		{ID: "getting-started", Title: "Getting Started", Pages: []string{"index"}},
		{ID: "architecture", Title: "Architecture", Pages: []string{"architecture-overview", "core-modules"}},
	}

	navOrder := make([]string, len(pages))
	for i, pg := range pages {
		navOrder[i] = pg.Slug
	}

	return models.WikiPlan{
		Sections:  sections,
		Pages:     pages,
		NavOrder:  navOrder,
		IndexSlug: "index",
	}
}

// ── helpers ───────────────────────────────────────────────────────────────────

func marshalSummary(s planningSummary) string {
	b, err := json.MarshalIndent(s, "", "  ")
	if err != nil {
		return fmt.Sprintf("%+v", s)
	}
	return string(b)
}

func dedup(ss []string) []string {
	seen := make(map[string]bool)
	var out []string
	for _, s := range ss {
		if !seen[s] {
			seen[s] = true
			out = append(out, s)
		}
	}
	return out
}
