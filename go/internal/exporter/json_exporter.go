// Package exporter writes wiki, diagram, and JSON export files.
package exporter

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"time"

	"github.com/unrealandychan/rekipedia/internal/models"
)

// JSONExporter writes structured JSON exports.
type JSONExporter struct {
	outputDir string
}

// NewJSONExporter creates a JSONExporter.
func NewJSONExporter(outputDir string) *JSONExporter {
	return &JSONExporter{outputDir: outputDir}
}

type pageEntry struct {
	Slug       string `json:"slug"`
	Title      string `json:"title"`
	Importance int    `json:"importance,omitempty"`
	Section    string `json:"section,omitempty"`
}

type sectionEntry struct {
	ID    string   `json:"id"`
	Title string   `json:"title"`
	Pages []string `json:"pages"`
}

type manifest struct {
	RunID       string         `json:"run_id"`
	GeneratedAt string         `json:"generated_at"`
	FileCount   int            `json:"file_count"`
	PageCount   int            `json:"page_count"`
	NavOrder    []string       `json:"nav_order"`
	Sections    []sectionEntry `json:"sections,omitempty"`
	Pages       []pageEntry    `json:"pages"`
}

// Export writes exports/symbols.json, exports/relationships.json, exports/manifest.json.
func (e *JSONExporter) Export(
	runID string,
	files []models.FileManifest,
	combined models.AnalysisResult,
	pages map[string]string,
	pageTitles map[string]string,
	plan models.WikiPlan,
	diagrams map[string][2]string,
) error {
	exportsDir := filepath.Join(e.outputDir, "exports")
	if err := os.MkdirAll(exportsDir, 0o755); err != nil {
		return err
	}

	// symbols.json
	symbols := combined.Symbols
	if symbols == nil {
		symbols = []models.Symbol{}
	}
	if err := writeJSON(filepath.Join(exportsDir, "symbols.json"), symbols); err != nil {
		return fmt.Errorf("write symbols: %w", err)
	}

	// relationships.json
	rels := combined.Relationships
	if rels == nil {
		rels = []models.Relationship{}
	}
	if err := writeJSON(filepath.Join(exportsDir, "relationships.json"), rels); err != nil {
		return fmt.Errorf("write relationships: %w", err)
	}

	// Build page entries from plan
	pageMap := make(map[string]pageEntry)
	for _, spec := range plan.Pages {
		pageMap[spec.Slug] = pageEntry{
			Slug:       spec.Slug,
			Title:      spec.Title,
			Importance: spec.Importance,
			Section:    spec.Section,
		}
	}
	// Also include pages not in plan
	for slug := range pages {
		if _, ok := pageMap[slug]; !ok {
			title := pageTitles[slug]
			if title == "" {
				title = slug
			}
			pageMap[slug] = pageEntry{Slug: slug, Title: title}
		}
	}

	// Collect sorted page entries
	var pageEntries []pageEntry
	for _, pe := range pageMap {
		pageEntries = append(pageEntries, pe)
	}
	sort.Slice(pageEntries, func(i, j int) bool {
		return pageEntries[i].Slug < pageEntries[j].Slug
	})

	navOrder := plan.NavOrder
	if navOrder == nil {
		navOrder = []string{}
	}

	// Build sections from plan
	var sections []sectionEntry
	for _, s := range plan.Sections {
		sections = append(sections, sectionEntry{
			ID:    s.ID,
			Title: s.Title,
			Pages: s.Pages,
		})
	}

	m := manifest{
		RunID:       runID,
		GeneratedAt: time.Now().UTC().Format(time.RFC3339),
		FileCount:   len(files),
		PageCount:   len(pages),
		NavOrder:    navOrder,
		Sections:    sections,
		Pages:       pageEntries,
	}
	if err := writeJSON(filepath.Join(exportsDir, "manifest.json"), m); err != nil {
		return fmt.Errorf("write manifest: %w", err)
	}

	return nil
}

func writeJSON(path string, v any) error {
	data, err := json.MarshalIndent(v, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(path, data, 0o644)
}
