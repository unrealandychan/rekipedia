// Package synthesis — DiagramBuilder generates Mermaid diagrams from relationships.
package synthesis

import (
	"fmt"
	"regexp"
	"sort"
	"strings"

	"github.com/unrealandychan/rekipedia/internal/models"
)

var reNodeSafe = regexp.MustCompile(`[^A-Za-z0-9_]`)

// DiagramBuilder generates Mermaid diagrams from relationship data.
type DiagramBuilder struct{}

// NewDiagramBuilder returns a new DiagramBuilder.
func NewDiagramBuilder() *DiagramBuilder { return &DiagramBuilder{} }

// Build generates diagrams from relationships and entry points.
// Returns map[name][2]string where [0]=type, [1]=mermaid content.
func (d *DiagramBuilder) Build(relationships []models.Relationship, entryPoints []string) map[string][2]string {
	out := make(map[string][2]string)
	if len(relationships) == 0 {
		return out
	}

	out["module-graph"] = [2]string{"flowchart", buildModuleGraph(relationships, entryPoints)}

	if ch := buildClassHierarchy(relationships); ch != "" {
		out["class-hierarchy"] = [2]string{"classDiagram", ch}
	}

	return out
}

// ── module graph ──────────────────────────────────────────────────────────────

func buildModuleGraph(rels []models.Relationship, entryPoints []string) string {
	entrySet := make(map[string]bool)
	for _, ep := range entryPoints {
		entrySet[ep] = true
	}

	type edge struct{ from, to, kind string }
	var importEdges, callEdges, inheritEdges []edge
	seenNodes := make(map[string]bool)

	for _, r := range rels {
		from := r.From
		to := r.To
		if from == "" || to == "" {
			continue
		}
		switch r.Kind {
		case models.RelImport:
			// Only include if the target looks like an internal module
			if strings.Contains(to, "/") || strings.Contains(to, ".") || isInternalLookingModule(to) {
				importEdges = append(importEdges, edge{from, to, "import"})
				seenNodes[from] = true
				seenNodes[to] = true
			}
		case models.RelCall:
			callEdges = append(callEdges, edge{from, to, "call"})
			seenNodes[from] = true
			seenNodes[to] = true
		case models.RelInherits:
			inheritEdges = append(inheritEdges, edge{from, to, "inherits"})
			seenNodes[from] = true
			seenNodes[to] = true
		}
	}

	if len(seenNodes) == 0 {
		return "flowchart LR\n  A[No internal relationships detected]"
	}

	var lines []string
	lines = append(lines, "flowchart LR")

	// Node definitions with display labels
	defined := make(map[string]bool)
	sortedNodes := sortedKeys(seenNodes)
	for _, name := range sortedNodes {
		nid := nodeID(name)
		if defined[nid] {
			continue
		}
		defined[nid] = true
		label := nodeLabel(name)
		if entrySet[name] {
			lines = append(lines, fmt.Sprintf("  %s([%q])", nid, label))
		} else {
			lines = append(lines, fmt.Sprintf("  %s[%q]", nid, label))
		}
	}

	// Limit edges per type to keep diagram readable (max 30 each)
	const maxEdges = 30

	for i, e := range importEdges {
		if i >= maxEdges {
			break
		}
		lines = append(lines, fmt.Sprintf("  %s -->|import| %s", nodeID(e.from), nodeID(e.to)))
	}
	for i, e := range callEdges {
		if i >= maxEdges {
			break
		}
		lines = append(lines, fmt.Sprintf("  %s -.->|call| %s", nodeID(e.from), nodeID(e.to)))
	}
	for _, e := range inheritEdges {
		lines = append(lines, fmt.Sprintf("  %s -->|extends| %s", nodeID(e.from), nodeID(e.to)))
	}

	return strings.Join(lines, "\n")
}

// ── class hierarchy ───────────────────────────────────────────────────────────

func buildClassHierarchy(rels []models.Relationship) string {
	var inherits []models.Relationship
	for _, r := range rels {
		if r.Kind == models.RelInherits {
			inherits = append(inherits, r)
		}
	}
	if len(inherits) == 0 {
		return ""
	}

	var lines []string
	lines = append(lines, "classDiagram")
	seen := make(map[string]bool)
	for _, r := range inherits {
		key := r.From + "->" + r.To
		if seen[key] {
			continue
		}
		seen[key] = true
		lines = append(lines, fmt.Sprintf("  %s <|-- %s", safeClassName(r.To), safeClassName(r.From)))
	}

	if len(lines) == 1 {
		return "" // only header, no actual relationships
	}
	return strings.Join(lines, "\n")
}

// ── helpers ───────────────────────────────────────────────────────────────────

func nodeID(name string) string {
	return reNodeSafe.ReplaceAllString(name, "_")
}

func nodeLabel(name string) string {
	parts := strings.Split(name, "/")
	last := parts[len(parts)-1]
	dotParts := strings.Split(last, ".")
	return dotParts[0]
}

func safeClassName(name string) string {
	s := reNodeSafe.ReplaceAllString(name, "_")
	if s == "" {
		return "Unknown"
	}
	return s
}

// isInternalLookingModule heuristically detects internal imports.
// Keeps anything that isn't a known stdlib / popular third-party package.
func isInternalLookingModule(name string) bool {
	external := map[string]bool{
		// Go stdlib
		"os": true, "sys": true, "re": true, "json": true, "math": true,
		"io": true, "fmt": true, "log": true, "time": true, "net": true,
		"http": true, "strings": true, "strconv": true, "errors": true,
		"context": true, "sync": true, "path": true, "sort": true,
		"bytes": true, "bufio": true, "crypto": true, "reflect": true,
		"runtime": true, "testing": true, "flag": true, "encoding": true,
		// Python stdlib
		"typing": true, "pathlib": true, "collections": true, "itertools": true,
		"functools": true, "dataclasses": true, "enum": true, "abc": true,
		"logging": true, "threading": true, "subprocess": true, "asyncio": true,
		"contextlib": true, "copy": true, "hashlib": true, "base64": true,
		"uuid": true, "random": true, "datetime": true, "struct": true,
		// Popular third-party
		"fastapi": true, "pydantic": true, "sqlalchemy": true, "django": true,
		"flask": true, "requests": true, "httpx": true, "aiohttp": true,
		"numpy": true, "pandas": true, "torch": true, "sklearn": true,
		"openai": true, "boto3": true, "celery": true, "redis": true,
		"pytest": true, "click": true, "typer": true, "rich": true,
		"starlette": true, "uvicorn": true, "gunicorn": true, "alembic": true,
		"litellm": true, "faiss": true,
	}
	return !external[name]
}

func sortedKeys(m map[string]bool) []string {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	return keys
}
