// Package orchestrator — AgenticAsk provides a ReAct tool-calling loop for Q&A.
package orchestrator

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"

	"github.com/unrealandychan/close-wiki/internal/llm"
	"github.com/unrealandychan/close-wiki/internal/models"
	"github.com/unrealandychan/close-wiki/internal/storage"
)

// defaultMaxIter is the default maximum number of tool-call iterations.
var defaultMaxIter = func() int {
	if v := os.Getenv("REKIPEDIA_ASK_MAX_ITER"); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n > 0 {
			return n
		}
	}
	return 5
}()

// agenticTools defines the function schemas for the ReAct tool-calling loop.
var agenticTools = []map[string]any{
	{
		"type": "function",
		"function": map[string]any{
			"name":        "search_code",
			"description": "Search the codebase for source chunks relevant to a query. Use this when you need more specific code evidence.",
			"parameters": map[string]any{
				"type": "object",
				"properties": map[string]any{
					"query": map[string]any{"type": "string", "description": "Natural language or keyword search query."},
				},
				"required": []string{"query"},
			},
		},
	},
	{
		"type": "function",
		"function": map[string]any{
			"name":        "get_symbol",
			"description": "Look up a specific symbol by name. Returns file path, line number, kind, and signature.",
			"parameters": map[string]any{
				"type": "object",
				"properties": map[string]any{
					"name": map[string]any{"type": "string", "description": "Exact or partial symbol name."},
				},
				"required": []string{"name"},
			},
		},
	},
	{
		"type": "function",
		"function": map[string]any{
			"name":        "get_page",
			"description": "Fetch the full content of a specific wiki page by slug.",
			"parameters": map[string]any{
				"type": "object",
				"properties": map[string]any{
					"slug": map[string]any{"type": "string", "description": "Wiki page slug (filename without .md)."},
				},
				"required": []string{"slug"},
			},
		},
	},
	{
		"type": "function",
		"function": map[string]any{
			"name":        "get_relationships",
			"description": "Return dependency graph edges (imports, calls, inherits) for a given symbol.",
			"parameters": map[string]any{
				"type": "object",
				"properties": map[string]any{
					"symbol": map[string]any{"type": "string", "description": "Symbol name to look up relationships for."},
				},
				"required": []string{"symbol"},
			},
		},
	},
}

// AgenticAskOptions extends AskOptions with agentic-specific settings.
type AgenticAskOptions struct {
	AskOptions
	MaxIter int
}

// AgenticAsk answers a question via a ReAct tool-calling loop.
//
// The LLM may call search_code / get_symbol / get_page / get_relationships
// up to MaxIter times before producing its final answer.
//
// Falls back to RunAsk if the model doesn't support tool calling.
func AgenticAsk(ctx context.Context, question, repoRoot, outputDir string, opts AgenticAskOptions) (*AskResult, error) {
	if opts.MaxIter <= 0 {
		opts.MaxIter = defaultMaxIter
	}

	dbPath := filepath.Join(outputDir, "store.db")
	if _, err := os.Stat(dbPath); err != nil {
		return nil, fmt.Errorf("no knowledge store found at %s — run `reki scan .` first", dbPath)
	}

	store, err := storage.Open(dbPath)
	if err != nil {
		return nil, fmt.Errorf("open store: %w", err)
	}
	defer store.Close()

	runID, err := store.GetLatestRunID(repoRoot)
	if err != nil || runID == "" {
		return nil, fmt.Errorf("no successful scan found — run `reki scan .` first")
	}

	// Build initial context (same as single-shot)
	wikiPages := loadWikiPages(outputDir)
	symbols, _ := store.GetAllSymbols(runID)
	symLines := symbolLines(symbols)
	contextParts := buildContext(wikiPages, symLines, opts.History, contextCharBudget)
	contextStr := strings.Join(contextParts, "\n\n---\n\n")
	systemPrompt := askSystemPrompt + "\n\n## Context\n\n" + contextStr

	messages := []map[string]any{
		{"role": "system", "content": systemPrompt},
		{"role": "user", "content": question},
	}

	client := llm.New(opts.LLMConfig)

	for i := range opts.MaxIter {
		resp, err := client.CallWithTools(ctx, messages, agenticTools)
		if err != nil {
			// Fallback: model doesn't support tools
			return RunAsk(ctx, question, repoRoot, outputDir, opts.AskOptions)
		}

		// No tool calls → final answer
		if len(resp.ToolCalls) == 0 {
			return &AskResult{
				Answer:    resp.Content,
				RunID:     runID,
				PageCount: len(wikiPages),
				SymCount:  len(symbols),
			}, nil
		}

		// Append assistant message
		messages = append(messages, map[string]any{
			"role":       "assistant",
			"content":    resp.Content,
			"tool_calls": resp.ToolCalls,
		})

		// Execute tool calls
		for _, tc := range resp.ToolCalls {
			result := executeTool(ctx, tc, outputDir, dbPath, runID, opts.LLMConfig)
			messages = append(messages, map[string]any{
				"role":         "tool",
				"tool_call_id": tc["id"],
				"content":      result,
			})
		}

		_ = i // suppress unused warning
	}

	// Max iter reached — request final answer without tools
	messages = append(messages, map[string]any{
		"role":    "user",
		"content": "Please provide your final answer now based on all the information gathered.",
	})
	resp, err := client.CallWithTools(ctx, messages, nil)
	if err != nil {
		return nil, fmt.Errorf("final answer call: %w", err)
	}
	return &AskResult{
		Answer:    resp.Content,
		RunID:     runID,
		PageCount: len(wikiPages),
		SymCount:  len(symbols),
	}, nil
}

// executeTool dispatches a single tool call and returns its result as a string.
func executeTool(ctx context.Context, tc map[string]any, outputDir, dbPath, runID string, cfg models.LLMConfig) string {
	fn, _ := tc["function"].(map[string]any)
	name, _ := fn["name"].(string)
	argsRaw, _ := fn["arguments"].(string)

	var args map[string]string
	_ = json.Unmarshal([]byte(argsRaw), &args)

	switch name {
	case "search_code":
		return toolSearchCode(ctx, args["query"], outputDir, cfg)
	case "get_symbol":
		return toolGetSymbol(dbPath, runID, args["name"])
	case "get_page":
		return toolGetPage(outputDir, args["slug"])
	case "get_relationships":
		return toolGetRelationships(dbPath, runID, args["symbol"])
	default:
		return fmt.Sprintf("Unknown tool: %s", name)
	}
}

func toolSearchCode(_ context.Context, query, outputDir string, _ models.LLMConfig) string {
	// Delegate to existing BM25/FAISS search via wiki content scan
	// Simple fallback: search wiki pages for relevant content
	wikiDir := filepath.Join(outputDir, "wiki")
	entries, err := os.ReadDir(wikiDir)
	if err != nil {
		return "No code index available."
	}
	query = strings.ToLower(query)
	var results []string
	for _, e := range entries {
		if e.IsDir() || !strings.HasSuffix(e.Name(), ".md") {
			continue
		}
		data, _ := os.ReadFile(filepath.Join(wikiDir, e.Name()))
		if strings.Contains(strings.ToLower(string(data)), query) {
			results = append(results, fmt.Sprintf("### %s\n%s", e.Name(), string(data)[:min(500, len(data))]))
		}
		if len(results) >= 3 {
			break
		}
	}
	if len(results) == 0 {
		return fmt.Sprintf("No results found for query: %q", query)
	}
	return strings.Join(results, "\n\n---\n\n")
}

func toolGetSymbol(dbPath, runID, name string) string {
	store, err := storage.Open(dbPath)
	if err != nil {
		return fmt.Sprintf("Store error: %v", err)
	}
	defer store.Close()
	syms, err := store.SearchSymbols(runID, name, 10)
	if err != nil || len(syms) == 0 {
		return fmt.Sprintf("No symbol found matching %q", name)
	}
	var lines []string
	for _, s := range syms {
		line := fmt.Sprintf("**%s** (%s) — `%s` line %d", s.Name, s.Kind, s.File, s.LineStart)
		if s.Signature != "" {
			line += fmt.Sprintf("\n  Signature: `%s`", s.Signature)
		}
		lines = append(lines, line)
	}
	return strings.Join(lines, "\n")
}

func toolGetPage(outputDir, slug string) string {
	wikiDir := filepath.Join(outputDir, "wiki")
	for _, candidate := range []string{slug + ".md", strings.ToLower(slug) + ".md"} {
		data, err := os.ReadFile(filepath.Join(wikiDir, candidate))
		if err == nil {
			return string(data)
		}
	}
	// Fuzzy
	entries, _ := os.ReadDir(wikiDir)
	for _, e := range entries {
		if strings.Contains(strings.ToLower(e.Name()), strings.ToLower(slug)) {
			data, _ := os.ReadFile(filepath.Join(wikiDir, e.Name()))
			return string(data)
		}
	}
	return fmt.Sprintf("No wiki page found for slug %q", slug)
}

func toolGetRelationships(dbPath, runID, symbol string) string {
	store, err := storage.Open(dbPath)
	if err != nil {
		return fmt.Sprintf("Store error: %v", err)
	}
	defer store.Close()
	edges, err := store.GetRelationshipsBySymbol(runID, symbol)
	if err != nil || len(edges) == 0 {
		return fmt.Sprintf("No relationships found for %q", symbol)
	}
	var lines []string
	for _, e := range edges {
		lines = append(lines, fmt.Sprintf("- **%s** → **%s** (%s)", e.From, e.To, e.Kind))
	}
	return strings.Join(lines, "\n")
}

func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}
