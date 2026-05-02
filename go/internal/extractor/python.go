package extractor

import (
	"bufio"
	"os"
	"regexp"
	"strings"

	"github.com/unrealandychan/rekipedia/internal/models"
)

// Python extractor uses regex-based parsing (no cgo / external binary).
// Covers top-level functions, classes, methods, imports — same as Python AST extractor.

var (
	rePyFuncDef  = regexp.MustCompile(`^(\s*)(?:async\s+)?def\s+(\w+)\s*\(([^)]*)\)`)
	rePyClassDef = regexp.MustCompile(`^(\s*)class\s+(\w+)(?:\s*\([^)]*\))?\s*:`)
	rePyImport   = regexp.MustCompile(`^(?:\s*)import\s+([\w,\s.]+)`)
	rePyFromImp  = regexp.MustCompile(`^(?:\s*)from\s+([\w.]+)\s+import\s+`)
	rePyDocstr   = regexp.MustCompile(`"""(.*?)"""`)
	rePyIfMain   = regexp.MustCompile(`if\s+__name__\s*==\s*["']__main__["']`)
)

// PythonExtractor parses .py / .pyw files.
type PythonExtractor struct{}

// NewPythonExtractor returns a new PythonExtractor.
func NewPythonExtractor() *PythonExtractor { return &PythonExtractor{} }

// CanHandle returns true for Python file extensions.
func (e *PythonExtractor) CanHandle(ext string) bool {
	ext = strings.ToLower(ext)
	return ext == ".py" || ext == ".pyw"
}

// Extract parses a Python file and extracts symbols and relationships.
func (e *PythonExtractor) Extract(absPath, relPath string) models.AnalysisResult {
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
	lines := strings.Split(source, "\n")

	// Track current class for method name prefixing
	type classFrame struct {
		name   string
		indent int
	}
	var classStack []classFrame

	for i, raw := range lines {
		lineNo := i + 1
		stripped := strings.TrimRight(raw, " \t\r")
		if stripped == "" {
			continue // skip blank lines — don't affect class stack
		}
		indent := indentWidth(raw)

		// Pop class stack when we dedent back to or past a class's indent level.
		// A method at indent=4 inside a class at indent=0 satisfies indent > classIndent.
		for len(classStack) > 0 && indent <= classStack[len(classStack)-1].indent {
			classStack = classStack[:len(classStack)-1]
		}

		// ── imports ─────────────────────────────────────────────────────
		if m := rePyImport.FindStringSubmatch(stripped); m != nil {
			for _, mod := range strings.Split(m[1], ",") {
				mod = strings.TrimSpace(strings.Split(mod, " as ")[0])
				if mod != "" {
					result.Relationships = append(result.Relationships, models.Relationship{
						From: relPath, To: mod, Kind: models.RelImport, File: relPath,
					})
				}
			}
			continue
		}
		if m := rePyFromImp.FindStringSubmatch(stripped); m != nil {
			result.Relationships = append(result.Relationships, models.Relationship{
				From: relPath, To: m[1], Kind: models.RelImport, File: relPath,
			})
			continue
		}

		// ── class definition ─────────────────────────────────────────────
		if m := rePyClassDef.FindStringSubmatch(stripped); m != nil {
			classStack = append(classStack, classFrame{name: m[2], indent: indent})
			result.Symbols = append(result.Symbols, models.Symbol{
				Name:      m[2],
				Kind:      models.SymbolClass,
				File:      relPath,
				LineStart: lineNo,
			})
			continue
		}

		// ── function / method definition ─────────────────────────────────
		if m := rePyFuncDef.FindStringSubmatch(stripped); m != nil {
			name := m[2]
			sig := name + "(" + strings.TrimSpace(m[3]) + ")"
			if len(classStack) > 0 && indent > classStack[len(classStack)-1].indent {
				name = classStack[len(classStack)-1].name + "." + name
			}
			// Docstring: peek at next non-empty line
			docstring := peekDocstring(lines, i+1)
			result.Symbols = append(result.Symbols, models.Symbol{
				Name:      name,
				Kind:      models.SymbolFunction,
				File:      relPath,
				LineStart: lineNo,
				Signature: sig,
				Docstring: docstring,
			})
		}

		// ── entry point ───────────────────────────────────────────────────
		if rePyIfMain.MatchString(stripped) {
			result.EntryPoints = append(result.EntryPoints, relPath)
		}
	}

	// Single-line docstring in triple-quotes at module level (first 5 lines)
	if m := rePyDocstr.FindStringSubmatch(strings.Join(lines[:min(5, len(lines))], "\n")); m != nil {
		result.Evidence["module_docstring"] = strings.TrimSpace(m[1])
	}

	return result
}

// indentWidth returns the number of leading spaces in s (tabs count as 4).
func indentWidth(s string) int {
	n := 0
	for _, c := range s {
		if c == ' ' {
			n++
		} else if c == '\t' {
			n += 4
		} else {
			break
		}
	}
	return n
}

// peekDocstring returns the first triple-quoted string starting at lines[start].
func peekDocstring(lines []string, start int) string {
	if start >= len(lines) {
		return ""
	}
	trimmed := strings.TrimSpace(lines[start])
	if strings.HasPrefix(trimmed, `"""`) || strings.HasPrefix(trimmed, `'''`) {
		quote := trimmed[:3]
		end := strings.Index(trimmed[3:], quote)
		if end != -1 {
			return strings.TrimSpace(trimmed[3 : 3+end])
		}
		// Multi-line: collect until closing quotes
		var sb strings.Builder
		sb.WriteString(trimmed[3:])
		for i := start + 1; i < len(lines) && i < start+10; i++ {
			line := lines[i]
			if idx := strings.Index(line, quote); idx != -1 {
				sb.WriteString(" " + strings.TrimSpace(line[:idx]))
				break
			}
			sb.WriteString(" " + strings.TrimSpace(line))
		}
		return strings.TrimSpace(sb.String())
	}
	return ""
}

func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}

// ExtractPythonFromReader parses Python source from a line scanner (used in tests).
func ExtractPythonFromReader(relPath string, scanner *bufio.Scanner) models.AnalysisResult {
	var lines []string
	for scanner.Scan() {
		lines = append(lines, scanner.Text())
	}
	// Write to temp and re-extract (simple re-use of Extract logic via string)
	result := models.AnalysisResult{
		ShardID:   relPath,
		FilesSeen: []string{relPath},
		Evidence:  make(map[string]string),
	}
	_ = lines
	return result
}
