// Package server provides the rekipedia HTTP server.
package server

import (
	"bytes"
	"context"
	"embed"
	"encoding/json"
	"fmt"
	"html/template"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"

	"github.com/go-chi/chi/v5"
	"github.com/go-chi/chi/v5/middleware"
	"github.com/yuin/goldmark"

	"github.com/unrealandychan/rekipedia/internal/models"
	"github.com/unrealandychan/rekipedia/internal/orchestrator"
	"github.com/unrealandychan/rekipedia/internal/storage"
)

//go:embed templates/*.html
var templateFS embed.FS

// Server serves the rekipedia web UI.
type Server struct {
	repoRoot  string
	outputDir string
	llmCfg    models.LLMConfig
	addr      string

	mu      sync.Mutex
	history []models.QAHistory
}

// New creates a new Server.
func New(repoRoot, outputDir, addr string, llmCfg models.LLMConfig) *Server {
	return &Server{repoRoot: repoRoot, outputDir: outputDir, llmCfg: llmCfg, addr: addr}
}

func newRouter(s *Server) *chi.Mux {
	r := chi.NewRouter()
	r.Use(middleware.Recoverer)
	r.Get("/", s.handleIndex)
	r.Get("/wiki/{slug}", s.handleWikiPage)
	r.Get("/ask", s.handleAskPage)
	r.Post("/ask/stream", s.handleAskStream)
	r.Get("/diagrams/{filename}", s.handleDiagram)
	r.Get("/api/pages", s.handleAPIPages)
	r.Get("/api/page/{slug}", s.handleAPIPage)
	r.Post("/api/ask", s.handleAPIAsk)
	r.Get("/api/ask/stream", s.handleAPIAskStream)
	r.Get("/api/history", s.handleAPIHistory)
	r.Get("/api/health", s.handleHealth)
	return r
}

// Start binds, serves requests, and blocks until ctx is cancelled.
func (s *Server) Start(ctx context.Context) error {
	r := newRouter(s)

	ln, err := net.Listen("tcp", s.addr)
	if err != nil {
		return fmt.Errorf("listen %s: %w", s.addr, err)
	}

	srv := &http.Server{Handler: r}
	go func() {
		<-ctx.Done()
		srv.Close()
	}()

	fmt.Printf("rekipedia server listening on http://%s\n", ln.Addr())
	err = srv.Serve(ln)
	if err == http.ErrServerClosed {
		return nil
	}
	return err
}

// ── template helpers ──────────────────────────────────────────────────────────

// renderTemplate loads base.html + the named page template per-request,
// avoiding the Go template inheritance bug where the last parsed
// {{define "content"}} block wins for all pages.
func (s *Server) renderTemplate(w http.ResponseWriter, name string, data any) {
	t, err := template.New("").Funcs(template.FuncMap{
		"inc": func(i int) int { return i + 1 },
	}).ParseFS(templateFS, "templates/base.html", "templates/"+name)
	if err != nil {
		http.Error(w, "template error: "+err.Error(), 500)
		return
	}
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	if err := t.ExecuteTemplate(w, "base.html", data); err != nil {
		http.Error(w, "render error: "+err.Error(), 500)
	}
}

// baseData returns common fields for all templates.
func (s *Server) baseData(activePage, activeSlug string) map[string]any {
	repoName := filepath.Base(s.repoRoot)
	pages, sections := s.listPagesAndSections()
	return map[string]any{
		"RepoName":   repoName,
		"RepoPath":   s.repoRoot,
		"ActivePage": activePage,
		"ActiveSlug": activeSlug,
		"Pages":      pages,
		"Sections":   sections,
	}
}

// ── handlers ──────────────────────────────────────────────────────────────────

func (s *Server) handleIndex(w http.ResponseWriter, r *http.Request) {
	diagrams := s.listDiagrams()
	stats := s.gatherStats()

	data := s.baseData("home", "")
	data["Stats"] = stats
	data["Diagrams"] = diagrams

	s.renderTemplate(w, "index.html", data)
}

func (s *Server) handleWikiPage(w http.ResponseWriter, r *http.Request) {
	slug := chi.URLParam(r, "slug")
	mdPath := filepath.Join(s.outputDir, "wiki", slug+".md")
	mdData, err := os.ReadFile(mdPath)
	if err != nil {
		http.NotFound(w, r)
		return
	}

	var buf bytes.Buffer
	if err := goldmark.Convert(mdData, &buf); err != nil {
		http.Error(w, "render error", 500)
		return
	}

	pages, _ := s.listPagesAndSections()
	title := slug
	for _, p := range pages {
		if p.Slug == slug {
			title = p.Title
			break
		}
	}

	data := s.baseData("wiki", slug)
	data["Title"] = title
	data["Content"] = template.HTML(buf.String())
	s.renderTemplate(w, "wiki.html", data)
}

func (s *Server) handleAskPage(w http.ResponseWriter, r *http.Request) {
	data := s.baseData("ask", "")
	s.renderTemplate(w, "ask.html", data)
}

func (s *Server) handleAskStream(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Question string `json:"question"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.Question == "" {
		http.Error(w, "missing question", 400)
		return
	}

	// Set SSE headers
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("X-Accel-Buffering", "no")
	w.WriteHeader(http.StatusOK)

	flusher, ok := w.(http.Flusher)
	if !ok {
		http.Error(w, "streaming not supported", 500)
		return
	}

	s.mu.Lock()
	histCopy := make([]models.QAHistory, len(s.history))
	copy(histCopy, s.history)
	s.mu.Unlock()

	var accumulated strings.Builder
	err := orchestrator.StreamAsk(r.Context(), req.Question, s.repoRoot, s.outputDir,
		orchestrator.AskOptions{LLMConfig: s.llmCfg, History: histCopy},
		func(chunk string) {
			accumulated.WriteString(chunk)
			safe := strings.ReplaceAll(chunk, "\n", `\n`)
			fmt.Fprintf(w, "data: %s\n\n", safe)
			flusher.Flush()
		},
	)
	if err != nil {
		fmt.Fprintf(w, "data: [ERROR] %s\n\n", err.Error())
	} else {
		fmt.Fprint(w, "data: [DONE]\n\n")
		answer := accumulated.String()
		s.persistQA(req.Question, answer)
	}
	flusher.Flush()
}

func (s *Server) handleAPIAskStream(w http.ResponseWriter, r *http.Request) {
	question := r.URL.Query().Get("question")
	if question == "" {
		http.Error(w, "missing question", 400)
		return
	}

	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("X-Accel-Buffering", "no")
	w.WriteHeader(http.StatusOK)

	flusher, ok := w.(http.Flusher)
	if !ok {
		http.Error(w, "streaming not supported", 500)
		return
	}

	s.mu.Lock()
	histCopy := make([]models.QAHistory, len(s.history))
	copy(histCopy, s.history)
	s.mu.Unlock()

	var accumulated strings.Builder
	err := orchestrator.StreamAsk(r.Context(), question, s.repoRoot, s.outputDir,
		orchestrator.AskOptions{LLMConfig: s.llmCfg, History: histCopy},
		func(chunk string) {
			accumulated.WriteString(chunk)
			safe := strings.ReplaceAll(chunk, "\n", `\n`)
			fmt.Fprintf(w, "data: %s\n\n", safe)
			flusher.Flush()
		},
	)
	if err != nil {
		fmt.Fprintf(w, "data: [ERROR] %s\n\n", err.Error())
	} else {
		fmt.Fprint(w, "data: [DONE]\n\n")
		s.persistQA(question, accumulated.String())
	}
	flusher.Flush()
}

func (s *Server) handleAPIAsk(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Question string `json:"question"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, "bad request", 400)
		return
	}

	s.mu.Lock()
	histCopy := make([]models.QAHistory, len(s.history))
	copy(histCopy, s.history)
	s.mu.Unlock()

	result, err := orchestrator.RunAsk(r.Context(), req.Question, s.repoRoot, s.outputDir, orchestrator.AskOptions{
		LLMConfig: s.llmCfg,
		History:   histCopy,
	})
	if err != nil {
		http.Error(w, err.Error(), 500)
		return
	}
	s.persistQA(req.Question, result.Answer)
	writeJSON(w, map[string]string{"answer": result.Answer})
}

func (s *Server) handleAPIHistory(w http.ResponseWriter, r *http.Request) {
	dbPath := filepath.Join(s.outputDir, "store.db")
	store, err := storage.Open(dbPath)
	if err != nil {
		writeJSON(w, []models.QAHistory{})
		return
	}
	defer store.Close()

	hist, err := store.GetQAHistory(s.repoRoot)
	if err != nil || hist == nil {
		writeJSON(w, []models.QAHistory{})
		return
	}
	writeJSON(w, hist)
}

func (s *Server) handleDiagram(w http.ResponseWriter, r *http.Request) {
	filename := chi.URLParam(r, "filename")
	// Prevent path traversal
	filename = filepath.Base(filename)
	fpath := filepath.Join(s.outputDir, "diagrams", filename)
	if _, err := os.Stat(fpath); err != nil {
		http.NotFound(w, r)
		return
	}
	http.ServeFile(w, r, fpath)
}

func (s *Server) handleAPIPages(w http.ResponseWriter, r *http.Request) {
	pages, _ := s.listPagesAndSections()
	writeJSON(w, pages)
}

func (s *Server) handleAPIPage(w http.ResponseWriter, r *http.Request) {
	slug := chi.URLParam(r, "slug")
	mdPath := filepath.Join(s.outputDir, "wiki", slug+".md")
	data, err := os.ReadFile(mdPath)
	if err != nil {
		http.NotFound(w, r)
		return
	}
	title := slug
	pages, _ := s.listPagesAndSections()
	for _, p := range pages {
		if p.Slug == slug {
			title = p.Title
			break
		}
	}
	writeJSON(w, map[string]any{"slug": slug, "title": title, "content": string(data)})
}

func (s *Server) handleHealth(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, map[string]string{"status": "ok"})
}

// ── helpers ───────────────────────────────────────────────────────────────────

// persistQA saves Q&A to in-memory history and SQLite.
func (s *Server) persistQA(question, answer string) {
	entry := models.QAHistory{Question: question, Answer: answer}

	s.mu.Lock()
	s.history = append(s.history, entry)
	s.mu.Unlock()

	// Persist to SQLite (best effort)
	dbPath := filepath.Join(s.outputDir, "store.db")
	if store, err := storage.Open(dbPath); err == nil {
		defer store.Close()
		_ = store.SaveQAHistory(s.repoRoot, question, answer)
	}
}

type pageInfo struct {
	Slug    string `json:"slug"`
	Title   string `json:"title"`
	Section string `json:"section"`
}

type sectionGroup struct {
	ID    string
	Title string
	Pages []pageInfo
}

type statsInfo struct {
	PageCount   int    `json:"page_count"`
	SymbolCount int    `json:"symbol_count"`
	LastScan    string `json:"last_scan"`
	RunID       string `json:"run_id"`
}

func (s *Server) gatherStats() statsInfo {
	pages, _ := s.listPagesAndSections()
	info := statsInfo{
		PageCount: len(pages),
		LastScan:  "—",
		RunID:     "—",
	}

	dbPath := filepath.Join(s.outputDir, "store.db")
	store, err := storage.Open(dbPath)
	if err != nil {
		return info
	}
	defer store.Close()

	runID, err := store.GetLatestRunID(s.repoRoot)
	if err != nil || runID == "" {
		return info
	}
	info.RunID = runID

	syms, _ := store.GetAllSymbols(runID)
	info.SymbolCount = len(syms)

	// Try to get last scan time from run record
	var finishedAt string
	_ = store.QueryRunTime(runID, &finishedAt)
	if finishedAt != "" {
		if len(finishedAt) >= 16 {
			info.LastScan = strings.Replace(finishedAt[:16], "T", " ", 1)
		} else {
			info.LastScan = finishedAt
		}
	}
	return info
}

func (s *Server) listDiagrams() []string {
	diagDir := filepath.Join(s.outputDir, "diagrams")
	entries, err := os.ReadDir(diagDir)
	if err != nil {
		return nil
	}
	var files []string
	for _, e := range entries {
		if !e.IsDir() {
			files = append(files, e.Name())
		}
	}
	return files
}

func (s *Server) listPagesAndSections() ([]pageInfo, []sectionGroup) {
	wikiDir := filepath.Join(s.outputDir, "wiki")
	entries, err := os.ReadDir(wikiDir)
	if err != nil {
		return nil, nil
	}

	available := make(map[string]bool)
	for _, e := range entries {
		if e.IsDir() || !strings.HasSuffix(e.Name(), ".md") {
			continue
		}
		slug := strings.TrimSuffix(e.Name(), ".md")
		available[slug] = true
	}

	var navOrder []string
	slugTitle := make(map[string]string)
	slugSection := make(map[string]string)
	var manifestSections []struct {
		ID    string   `json:"id"`
		Title string   `json:"title"`
		Pages []string `json:"pages"`
	}

	manifestPath := filepath.Join(s.outputDir, "exports", "manifest.json")
	if data, err := os.ReadFile(manifestPath); err == nil {
		var m struct {
			NavOrder []string `json:"nav_order"`
			Sections []struct {
				ID    string   `json:"id"`
				Title string   `json:"title"`
				Pages []string `json:"pages"`
			} `json:"sections"`
			Pages []struct {
				Slug    string `json:"slug"`
				Title   string `json:"title"`
				Section string `json:"section"`
			} `json:"pages"`
		}
		if err := json.Unmarshal(data, &m); err == nil {
			navOrder = m.NavOrder
			manifestSections = m.Sections
			for _, p := range m.Pages {
				slugTitle[p.Slug] = p.Title
				slugSection[p.Slug] = p.Section
			}
		}
	}

	// Fallback: read title from markdown H1
	for _, e := range entries {
		if e.IsDir() || !strings.HasSuffix(e.Name(), ".md") {
			continue
		}
		slug := strings.TrimSuffix(e.Name(), ".md")
		if slugTitle[slug] == "" {
			if data, err := os.ReadFile(filepath.Join(wikiDir, e.Name())); err == nil {
				for _, line := range strings.Split(string(data), "\n") {
					line = strings.TrimSpace(line)
					if strings.HasPrefix(line, "# ") {
						slugTitle[slug] = strings.TrimPrefix(line, "# ")
						break
					}
				}
			}
			if slugTitle[slug] == "" {
				slugTitle[slug] = slug
			}
		}
	}

	seen := make(map[string]bool)
	var orderedSlugs []string
	for _, slug := range navOrder {
		if available[slug] {
			orderedSlugs = append(orderedSlugs, slug)
			seen[slug] = true
		}
	}
	var remainder []string
	for slug := range available {
		if !seen[slug] {
			remainder = append(remainder, slug)
		}
	}
	sort.Strings(remainder)
	orderedSlugs = append(orderedSlugs, remainder...)

	var pages []pageInfo
	for _, slug := range orderedSlugs {
		pages = append(pages, pageInfo{
			Slug:    slug,
			Title:   slugTitle[slug],
			Section: slugSection[slug],
		})
	}

	// Build section groups
	var sections []sectionGroup
	if len(manifestSections) > 0 {
		pageBySlug := make(map[string]pageInfo)
		for _, p := range pages {
			pageBySlug[p.Slug] = p
		}
		inSection := make(map[string]bool)
		for _, sec := range manifestSections {
			sg := sectionGroup{ID: sec.ID, Title: sec.Title}
			for _, slug := range sec.Pages {
				if p, ok := pageBySlug[slug]; ok {
					sg.Pages = append(sg.Pages, p)
					inSection[slug] = true
				}
			}
			if len(sg.Pages) > 0 {
				sections = append(sections, sg)
			}
		}
		// Pages not in any section → "Other"
		var other []pageInfo
		for _, p := range pages {
			if !inSection[p.Slug] {
				other = append(other, p)
			}
		}
		if len(other) > 0 {
			sections = append(sections, sectionGroup{ID: "other", Title: "Other", Pages: other})
		}
	} else if len(pages) > 0 {
		// Auto-group by section field
		var sectionOrder []string
		sectionPages := make(map[string][]pageInfo)
		for _, p := range pages {
			sec := p.Section
			if sec == "" {
				sec = "Other"
			}
			if _, exists := sectionPages[sec]; !exists {
				sectionOrder = append(sectionOrder, sec)
			}
			sectionPages[sec] = append(sectionPages[sec], p)
		}
		for _, sec := range sectionOrder {
			sections = append(sections, sectionGroup{ID: sec, Title: sec, Pages: sectionPages[sec]})
		}
	}

	return pages, sections
}

// listPages is kept for backward compat (used in tests).
func (s *Server) listPages() []pageInfo {
	pages, _ := s.listPagesAndSections()
	return pages
}

func writeJSON(w http.ResponseWriter, v any) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(v)
}
