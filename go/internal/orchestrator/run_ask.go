// Package orchestrator — RunAsk provides grounded Q&A against the wiki.
package orchestrator

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"github.com/unrealandychan/rekipedia/internal/llm"
	"github.com/unrealandychan/rekipedia/internal/models"
	"github.com/unrealandychan/rekipedia/internal/rag"
	"github.com/unrealandychan/rekipedia/internal/storage"
)

const (
	// contextCharBudget is the max character budget for context (~24K tokens at 4 chars/token)
	contextCharBudget = 96_000
	askSystemPrompt   = `You are an expert software engineer and technical writer with deep knowledge of the repository described in the context below.

Answer the user's question accurately and concisely. Your answer must be:
- Grounded in the provided context (wiki pages, symbols, code evidence)
- Specific: reference exact file paths, function names, and line numbers when available
- Formatted in Markdown with headers, code blocks, and bullet points where helpful
- Honest: if the context doesn't contain enough information to answer, say so clearly

Do NOT invent information not present in the context. Do NOT hallucinate file paths or function names.`
)

// AskOptions configures a Q&A session.
type AskOptions struct {
	LLMConfig models.LLMConfig
	Stream    bool
	History   []models.QAHistory
}

// AskResult contains the answer and metadata.
type AskResult struct {
	Answer    string
	RunID     string
	PageCount int
	SymCount  int
}

// RunAsk answers a question using the wiki and symbol index.
//
// Flow:
//  1. Locate latest successful scan run.
//  2. Load wiki pages from disk.
//  3. Load symbol index from store.
//  4. Try RAG: embed question, search vector store, prepend top chunks.
//  5. Assemble context within character budget.
//  6. Call LLM with grounding system prompt.
func RunAsk(ctx context.Context, question, repoRoot, outputDir string, opts AskOptions) (*AskResult, error) {
	dbPath := filepath.Join(outputDir, "store.db")
	if _, err := os.Stat(dbPath); err != nil {
		return nil, fmt.Errorf("no knowledge store found at %s — run `rekipedia scan .` first", dbPath)
	}

	store, err := storage.Open(dbPath)
	if err != nil {
		return nil, fmt.Errorf("open store: %w", err)
	}
	defer store.Close()

	// ── 1. Find latest run ───────────────────────────────────────────────
	runID, err := store.GetLatestRunID(repoRoot)
	if err != nil || runID == "" {
		return nil, fmt.Errorf("no successful scan found for this repository — run `rekipedia scan .` first")
	}

	// ── 2. Load wiki pages ───────────────────────────────────────────────
	wikiPages := loadWikiPages(outputDir)

	// ── 3. Load symbols ──────────────────────────────────────────────────
	symbols, _ := store.GetAllSymbols(runID)
	symLines := symbolLines(symbols)

	// ── 4. RAG: try vector store ─────────────────────────────────────────
	ragChunks := tryRAGSearch(ctx, question, outputDir, opts.LLMConfig)

	// ── 5. Assemble context within budget ────────────────────────────────
	contextParts := buildContext(ragChunks, wikiPages, symLines, opts.History, contextCharBudget)
	contextStr := strings.Join(contextParts, "\n\n---\n\n")

	prompt := fmt.Sprintf("## Context\n\n%s\n\n## Question\n\n%s", contextStr, question)

	// ── 6. Call LLM ──────────────────────────────────────────────────────
	client := llm.New(opts.LLMConfig)
	answer, err := client.Call(ctx, askSystemPrompt, prompt)
	if err != nil {
		return nil, fmt.Errorf("llm call: %w", err)
	}

	return &AskResult{
		Answer:    answer,
		RunID:     runID,
		PageCount: len(wikiPages),
		SymCount:  len(symbols),
	}, nil
}

// StreamAsk answers a question via streaming, calling onChunk for each token.
func StreamAsk(ctx context.Context, question, repoRoot, outputDir string, opts AskOptions, onChunk func(string)) error {
	dbPath := filepath.Join(outputDir, "store.db")
	store, err := storage.Open(dbPath)
	if err != nil {
		return fmt.Errorf("open store: %w", err)
	}
	defer store.Close()

	runID, err := store.GetLatestRunID(repoRoot)
	if err != nil || runID == "" {
		return fmt.Errorf("no successful scan found — run `rekipedia scan .` first")
	}

	wikiPages := loadWikiPages(outputDir)
	symbols, _ := store.GetAllSymbols(runID)
	symLines := symbolLines(symbols)

	ragChunks := tryRAGSearch(ctx, question, outputDir, opts.LLMConfig)

	contextParts := buildContext(ragChunks, wikiPages, symLines, opts.History, contextCharBudget)
	contextStr := strings.Join(contextParts, "\n\n---\n\n")
	prompt := fmt.Sprintf("## Context\n\n%s\n\n## Question\n\n%s", contextStr, question)

	client := llm.New(opts.LLMConfig)
	return client.StreamCall(ctx, askSystemPrompt, prompt, onChunk)
}

// tryRAGSearch embeds the question and searches the vector store.
// Returns a formatted "## Relevant Code Snippets" section, or nil on any failure.
func tryRAGSearch(ctx context.Context, question, outputDir string, cfg models.LLMConfig) []string {
	pipeline := rag.NewEmbedPipeline(outputDir, cfg)
	results, err := pipeline.Search(question, 5)
	if err != nil || len(results) == 0 {
		return nil
	}
	var sb strings.Builder
	sb.WriteString("## Relevant Code Snippets\n\n")
	for _, r := range results {
		sb.WriteString(fmt.Sprintf("### %s\n\n```\n%s\n```\n\n", r.Chunk.FilePath, r.Chunk.Text))
	}
	return []string{sb.String()}
}

// ── helpers ───────────────────────────────────────────────────────────────────

func loadWikiPages(outputDir string) []string {
	wikiDir := filepath.Join(outputDir, "wiki")
	entries, err := os.ReadDir(wikiDir)
	if err != nil {
		return nil
	}
	var pages []string
	for _, e := range entries {
		if e.IsDir() || !strings.HasSuffix(e.Name(), ".md") {
			continue
		}
		data, err := os.ReadFile(filepath.Join(wikiDir, e.Name()))
		if err != nil {
			continue
		}
		slug := strings.TrimSuffix(e.Name(), ".md")
		pages = append(pages, fmt.Sprintf("## [%s.md]\n\n%s", slug, string(data)))
	}
	return pages
}

func symbolLines(symbols []models.Symbol) []string {
	type symEntry struct {
		Name string `json:"name"`
		Kind string `json:"kind"`
		File string `json:"file"`
		Line int    `json:"line,omitempty"`
	}
	var entries []symEntry
	for _, s := range symbols {
		entries = append(entries, symEntry{
			Name: s.Name,
			Kind: string(s.Kind),
			File: s.File,
			Line: s.LineStart,
		})
	}
	// Sort by file for deterministic output
	sort.Slice(entries, func(i, j int) bool {
		if entries[i].File != entries[j].File {
			return entries[i].File < entries[j].File
		}
		return entries[i].Name < entries[j].Name
	})
	b, _ := json.MarshalIndent(entries, "", "  ")
	if len(b) == 0 {
		return nil
	}
	return []string{"## Symbol Index\n\n```json\n" + string(b) + "\n```"}
}

func buildContext(ragChunks, wikiPages, symLines []string, history []models.QAHistory, budget int) []string {
	var parts []string
	used := 0

	// RAG chunks first (highest priority)
	for _, chunk := range ragChunks {
		if used+len(chunk) > budget {
			break
		}
		parts = append(parts, chunk)
		used += len(chunk)
	}

	// Add previous Q&A history first (most recent last)
	if len(history) > 0 {
		var histLines []string
		for _, h := range history {
			histLines = append(histLines, fmt.Sprintf("**Q:** %s\n\n**A:** %s", h.Question, h.Answer))
		}
		histStr := "## Previous Q&A\n\n" + strings.Join(histLines, "\n\n---\n\n")
		if used+len(histStr) < budget {
			parts = append(parts, histStr)
			used += len(histStr)
		}
	}

	// Wiki pages
	for _, page := range wikiPages {
		if used+len(page) > budget {
			// Truncate last page if possible
			remaining := budget - used
			if remaining > 200 {
				parts = append(parts, page[:remaining]+"…")
			}
			break
		}
		parts = append(parts, page)
		used += len(page)
	}

	// Symbol index (lowest priority — often large)
	for _, line := range symLines {
		if used+len(line) > budget {
			break
		}
		parts = append(parts, line)
		used += len(line)
	}

	return parts
}
