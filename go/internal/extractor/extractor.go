// Package extractor provides source code analysis for Python, TypeScript, and config files.
// All extractors use regex-based parsing (no external AST binary dependencies)
// so the final binary remains self-contained.
package extractor

import (
	"github.com/unrealandychan/rekipedia/internal/models"
)

// Extractor analyses a single file and returns an AnalysisResult.
type Extractor interface {
	// CanHandle returns true if this extractor can process the given file extension.
	CanHandle(ext string) bool
	// Extract parses the file at absPath (relative path relPath) and returns symbols/relationships.
	Extract(absPath, relPath string) models.AnalysisResult
}

// Registry holds all registered extractors.
type Registry struct {
	extractors []Extractor
}

// NewRegistry returns a Registry pre-loaded with all built-in extractors.
func NewRegistry() *Registry {
	return &Registry{
		extractors: []Extractor{
			NewGoExtractor(),
			NewPythonExtractor(),
			NewTypeScriptExtractor(),
			NewConfigExtractor(),
		},
	}
}

// ExtractFile finds the right extractor for ext and runs it.
// Falls back to an empty AnalysisResult if no extractor matches.
func (r *Registry) ExtractFile(absPath, relPath, ext string) models.AnalysisResult {
	for _, e := range r.extractors {
		if e.CanHandle(ext) {
			return e.Extract(absPath, relPath)
		}
	}
	return models.AnalysisResult{
		ShardID:   relPath,
		FilesSeen: []string{relPath},
	}
}

// MergeResults combines multiple AnalysisResults into one.
func MergeResults(results []models.AnalysisResult) models.AnalysisResult {
	merged := models.AnalysisResult{
		Evidence: make(map[string]string),
	}
	for _, r := range results {
		merged.FilesSeen = append(merged.FilesSeen, r.FilesSeen...)
		merged.EntryPoints = append(merged.EntryPoints, r.EntryPoints...)
		merged.Symbols = append(merged.Symbols, r.Symbols...)
		merged.Relationships = append(merged.Relationships, r.Relationships...)
		merged.BuildCommands = append(merged.BuildCommands, r.BuildCommands...)
		merged.TestCommands = append(merged.TestCommands, r.TestCommands...)
		merged.Risks = append(merged.Risks, r.Risks...)
		merged.Unknowns = append(merged.Unknowns, r.Unknowns...)
		for k, v := range r.Evidence {
			merged.Evidence[k] = v
		}
	}
	return merged
}
