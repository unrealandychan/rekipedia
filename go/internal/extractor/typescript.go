package extractor

import (
	"os"
	"regexp"
	"strings"

	"github.com/unrealandychan/rekipedia/internal/models"
)

// TypeScript/JavaScript extractor using regex — same patterns as Python's typescript_extractor.py.

var (
	reTSImport     = regexp.MustCompile(`(?:import\s+(?:.*?\s+from\s+)?|require\s*\()\s*['"]([^'"]+)['"]`)
	reTSExportFunc = regexp.MustCompile(`(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(([^)]*)\)`)
	reTSArrowFunc  = regexp.MustCompile(`(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\(([^)]*)\)\s*=>`)
	reTSClass      = regexp.MustCompile(`(?:export\s+)?(?:abstract\s+)?class\s+(\w+)(?:\s+extends\s+(\w+))?`)
	reTSInterface  = regexp.MustCompile(`(?:export\s+)?interface\s+(\w+)`)
	reTSType       = regexp.MustCompile(`(?:export\s+)?type\s+(\w+)\s*=`)
	reTSEnum       = regexp.MustCompile(`(?:export\s+)?(?:const\s+)?enum\s+(\w+)`)
	reTSLineComment = regexp.MustCompile(`//[^\n]*`)
)

// TypeScriptExtractor handles .ts, .tsx, .js, .jsx, .mjs, .cjs files.
type TypeScriptExtractor struct{}

// NewTypeScriptExtractor returns a new TypeScriptExtractor.
func NewTypeScriptExtractor() *TypeScriptExtractor { return &TypeScriptExtractor{} }

// CanHandle returns true for TypeScript/JavaScript extensions.
func (e *TypeScriptExtractor) CanHandle(ext string) bool {
	switch strings.ToLower(ext) {
	case ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs":
		return true
	}
	return false
}

// Extract parses a TypeScript/JavaScript file.
func (e *TypeScriptExtractor) Extract(absPath, relPath string) models.AnalysisResult {
	result := models.AnalysisResult{
		ShardID:   relPath,
		FilesSeen: []string{relPath},
		Evidence:  make(map[string]string),
	}

	data, err := os.ReadFile(absPath)
	if err != nil {
		result.Risks = append(result.Risks, "unreadable: "+relPath)
		return result
	}
	source := string(data)

	// Strip line comments to reduce false matches (preserve line count via newlines)
	clean := reTSLineComment.ReplaceAllString(source, "")

	// ── imports ──────────────────────────────────────────────────────────
	for _, m := range reTSImport.FindAllStringSubmatch(clean, -1) {
		result.Relationships = append(result.Relationships, models.Relationship{
			From: relPath, To: m[1], Kind: models.RelImport, File: relPath,
		})
	}

	// ── export function / async function ─────────────────────────────────
	for _, m := range reTSExportFunc.FindAllStringSubmatch(clean, -1) {
		result.Symbols = append(result.Symbols, models.Symbol{
			Name:      m[1],
			Kind:      models.SymbolFunction,
			File:      relPath,
			LineStart: lineOf(source, strings.Index(source, m[0])),
			Signature: m[1] + "(" + strings.TrimSpace(m[2]) + ")",
		})
	}

	// ── arrow functions ───────────────────────────────────────────────────
	for _, m := range reTSArrowFunc.FindAllStringSubmatch(clean, -1) {
		result.Symbols = append(result.Symbols, models.Symbol{
			Name:      m[1],
			Kind:      models.SymbolFunction,
			File:      relPath,
			LineStart: lineOf(source, strings.Index(source, m[0])),
			Signature: m[1] + "(" + strings.TrimSpace(m[2]) + ")",
		})
	}

	// ── classes ───────────────────────────────────────────────────────────
	for _, m := range reTSClass.FindAllStringSubmatch(clean, -1) {
		sym := models.Symbol{
			Name:      m[1],
			Kind:      models.SymbolClass,
			File:      relPath,
			LineStart: lineOf(source, strings.Index(source, m[0])),
		}
		if m[2] != "" {
			result.Relationships = append(result.Relationships, models.Relationship{
				From: m[1], To: m[2], Kind: models.RelInherits, File: relPath,
			})
		}
		result.Symbols = append(result.Symbols, sym)
	}

	// ── interfaces ────────────────────────────────────────────────────────
	for _, m := range reTSInterface.FindAllStringSubmatch(clean, -1) {
		result.Symbols = append(result.Symbols, models.Symbol{
			Name:      m[1],
			Kind:      models.SymbolInterface,
			File:      relPath,
			LineStart: lineOf(source, strings.Index(source, m[0])),
		})
	}

	// ── type aliases ─────────────────────────────────────────────────────
	for _, m := range reTSType.FindAllStringSubmatch(clean, -1) {
		result.Symbols = append(result.Symbols, models.Symbol{
			Name:      m[1],
			Kind:      models.SymbolType,
			File:      relPath,
			LineStart: lineOf(source, strings.Index(source, m[0])),
		})
	}

	// ── enums ─────────────────────────────────────────────────────────────
	for _, m := range reTSEnum.FindAllStringSubmatch(clean, -1) {
		result.Symbols = append(result.Symbols, models.Symbol{
			Name:      m[1],
			Kind:      models.SymbolEnum,
			File:      relPath,
			LineStart: lineOf(source, strings.Index(source, m[0])),
		})
	}

	// ── entry points ─────────────────────────────────────────────────────
	if strings.Contains(source, "ReactDOM.render") ||
		strings.Contains(source, "createRoot") ||
		strings.Contains(source, "app.listen") ||
		strings.Contains(source, "server.listen") {
		result.EntryPoints = append(result.EntryPoints, relPath)
	}

	return result
}

// lineOf returns the 1-based line number of byteOffset in source.
func lineOf(source string, byteOffset int) int {
	if byteOffset < 0 {
		return 0
	}
	return strings.Count(source[:byteOffset], "\n") + 1
}
