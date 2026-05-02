// Package storage provides SQLite-backed persistence for rekipedia.
package storage

import (
	"database/sql"
	"fmt"
	"path/filepath"
	"time"

	_ "modernc.org/sqlite"

	"github.com/unrealandychan/rekipedia/internal/models"
)

const schemaVersion = 1

// Store wraps a SQLite database with high-level operations.
type Store struct {
	db   *sql.DB
	path string
}

// Open opens (or creates) a Store at dbPath.
func Open(dbPath string) (*Store, error) {
	db, err := sql.Open("sqlite", dbPath+"?_journal_mode=WAL&_foreign_keys=on")
	if err != nil {
		return nil, fmt.Errorf("open sqlite: %w", err)
	}
	s := &Store{db: db, path: dbPath}
	if err := s.migrate(); err != nil {
		_ = db.Close()
		return nil, fmt.Errorf("migrate: %w", err)
	}
	return s, nil
}

// DefaultPath returns the standard store path inside a repo's .rekipedia dir.
func DefaultPath(repoRoot string) string {
	return filepath.Join(repoRoot, ".rekipedia", "store.db")
}

// Close closes the underlying database connection.
func (s *Store) Close() error {
	return s.db.Close()
}

// migrate creates tables if they don't exist.
func (s *Store) migrate() error {
	ddl := []string{
		`CREATE TABLE IF NOT EXISTS runs (
			run_id      TEXT PRIMARY KEY,
			repo_path   TEXT NOT NULL,
			started_at  TEXT NOT NULL,
			finished_at TEXT,
			status      TEXT NOT NULL DEFAULT 'running',
			model       TEXT,
			page_count  INTEGER DEFAULT 0
		)`,
		`CREATE TABLE IF NOT EXISTS symbols (
			id         INTEGER PRIMARY KEY AUTOINCREMENT,
			run_id     TEXT NOT NULL,
			name       TEXT NOT NULL,
			kind       TEXT NOT NULL,
			file       TEXT NOT NULL,
			line_start INTEGER,
			line_end   INTEGER,
			signature  TEXT,
			docstring  TEXT
		)`,
		`CREATE TABLE IF NOT EXISTS relationships (
			id       INTEGER PRIMARY KEY AUTOINCREMENT,
			run_id   TEXT NOT NULL,
			from_sym TEXT NOT NULL,
			to_sym   TEXT NOT NULL,
			kind     TEXT NOT NULL,
			file     TEXT
		)`,
		`CREATE TABLE IF NOT EXISTS wiki_pages (
			id           INTEGER PRIMARY KEY AUTOINCREMENT,
			run_id       TEXT NOT NULL,
			slug         TEXT NOT NULL,
			title        TEXT NOT NULL,
			section      TEXT,
			content      TEXT,
			priority     INTEGER DEFAULT 50,
			importance   INTEGER DEFAULT 50,
			generated_at TEXT
		)`,
		`CREATE UNIQUE INDEX IF NOT EXISTS uq_wiki_slug ON wiki_pages(run_id, slug)`,
		`CREATE TABLE IF NOT EXISTS qa_history (
			id        INTEGER PRIMARY KEY AUTOINCREMENT,
			run_id    TEXT,
			question  TEXT NOT NULL,
			answer    TEXT,
			asked_at  TEXT NOT NULL
		)`,
		`CREATE TABLE IF NOT EXISTS file_manifest (
			path       TEXT PRIMARY KEY,
			sha256     TEXT NOT NULL,
			size_bytes INTEGER,
			language   TEXT,
			last_seen  TEXT NOT NULL
		)`,
	}
	for _, stmt := range ddl {
		if _, err := s.db.Exec(stmt); err != nil {
			return fmt.Errorf("ddl %q: %w", stmt[:40], err)
		}
	}
	return nil
}

// --- Runs ---

// CreateRun inserts a new scan run record.
func (s *Store) CreateRun(runID, repoPath, model string) error {
	_, err := s.db.Exec(
		`INSERT INTO runs (run_id, repo_path, started_at, status, model) VALUES (?, ?, ?, 'running', ?)`,
		runID, repoPath, time.Now().UTC().Format(time.RFC3339), model,
	)
	return err
}

// FinishRun marks a run as complete with page count.
func (s *Store) FinishRun(runID string, pageCount int) error {
	_, err := s.db.Exec(
		`UPDATE runs SET status='done', finished_at=?, page_count=? WHERE run_id=?`,
		time.Now().UTC().Format(time.RFC3339), pageCount, runID,
	)
	return err
}

// LatestRunID returns the most recent run_id for the given repo.
func (s *Store) LatestRunID(repoPath string) (string, error) {
	var id string
	err := s.db.QueryRow(
		`SELECT run_id FROM runs WHERE repo_path=? ORDER BY started_at DESC LIMIT 1`,
		repoPath,
	).Scan(&id)
	if err == sql.ErrNoRows {
		return "", nil
	}
	return id, err
}

// --- Symbols ---

// SaveSymbols bulk-inserts symbols for a run.
func (s *Store) SaveSymbols(runID string, syms []models.Symbol) error {
	tx, err := s.db.Begin()
	if err != nil {
		return err
	}
	stmt, err := tx.Prepare(
		`INSERT INTO symbols (run_id,name,kind,file,line_start,line_end,signature,docstring)
		 VALUES (?,?,?,?,?,?,?,?)`,
	)
	if err != nil {
		_ = tx.Rollback()
		return err
	}
	defer stmt.Close()
	for _, sym := range syms {
		if _, err := stmt.Exec(runID, sym.Name, string(sym.Kind), sym.File,
			sym.LineStart, sym.LineEnd, sym.Signature, sym.Docstring); err != nil {
			_ = tx.Rollback()
			return err
		}
	}
	return tx.Commit()
}

// ListSymbols returns all symbols for a run.
func (s *Store) ListSymbols(runID string) ([]models.Symbol, error) {
	rows, err := s.db.Query(
		`SELECT name,kind,file,line_start,line_end,signature,docstring FROM symbols WHERE run_id=?`,
		runID,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var syms []models.Symbol
	for rows.Next() {
		var sym models.Symbol
		var kind string
		if err := rows.Scan(&sym.Name, &kind, &sym.File,
			&sym.LineStart, &sym.LineEnd, &sym.Signature, &sym.Docstring); err != nil {
			return nil, err
		}
		sym.Kind = models.SymbolKind(kind)
		syms = append(syms, sym)
	}
	return syms, rows.Err()
}

// --- Relationships ---

// SaveRelationships bulk-inserts relationships.
func (s *Store) SaveRelationships(runID string, rels []models.Relationship) error {
	tx, err := s.db.Begin()
	if err != nil {
		return err
	}
	stmt, err := tx.Prepare(
		`INSERT INTO relationships (run_id,from_sym,to_sym,kind,file) VALUES (?,?,?,?,?)`,
	)
	if err != nil {
		_ = tx.Rollback()
		return err
	}
	defer stmt.Close()
	for _, r := range rels {
		if _, err := stmt.Exec(runID, r.From, r.To, string(r.Kind), r.File); err != nil {
			_ = tx.Rollback()
			return err
		}
	}
	return tx.Commit()
}

// --- Wiki Pages ---

// UpsertWikiPage inserts or replaces a wiki page.
func (s *Store) UpsertWikiPage(runID, slug, title, section, content string, priority, importance int) error {
	_, err := s.db.Exec(
		`INSERT INTO wiki_pages (run_id,slug,title,section,content,priority,importance,generated_at)
		 VALUES (?,?,?,?,?,?,?,?)
		 ON CONFLICT(run_id,slug) DO UPDATE SET
		   title=excluded.title, section=excluded.section, content=excluded.content,
		   priority=excluded.priority, importance=excluded.importance, generated_at=excluded.generated_at`,
		runID, slug, title, section, content, priority, importance,
		time.Now().UTC().Format(time.RFC3339),
	)
	return err
}

// GetWikiPage retrieves a single page by slug.
func (s *Store) GetWikiPage(runID, slug string) (title, section, content string, err error) {
	err = s.db.QueryRow(
		`SELECT title, section, content FROM wiki_pages WHERE run_id=? AND slug=?`,
		runID, slug,
	).Scan(&title, &section, &content)
	return
}

// ListWikiPages returns all pages for a run, ordered by importance desc.
func (s *Store) ListWikiPages(runID string) ([]WikiPageRow, error) {
	rows, err := s.db.Query(
		`SELECT slug, title, section, importance, priority FROM wiki_pages
		 WHERE run_id=? ORDER BY importance DESC, priority DESC`,
		runID,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var pages []WikiPageRow
	for rows.Next() {
		var p WikiPageRow
		if err := rows.Scan(&p.Slug, &p.Title, &p.Section, &p.Importance, &p.Priority); err != nil {
			return nil, err
		}
		pages = append(pages, p)
	}
	return pages, rows.Err()
}

// WikiPageRow is a lightweight summary of a wiki page (no content).
type WikiPageRow struct {
	Slug       string
	Title      string
	Section    string
	Importance int
	Priority   int
}

// --- Q&A History ---

// SaveQA records a question/answer pair.
func (s *Store) SaveQA(runID, question, answer string) error {
	_, err := s.db.Exec(
		`INSERT INTO qa_history (run_id,question,answer,asked_at) VALUES (?,?,?,?)`,
		runID, question, answer, time.Now().UTC().Format(time.RFC3339),
	)
	return err
}

// --- File Manifest ---

// UpsertManifest inserts or updates a file's manifest record.
func (s *Store) UpsertManifest(path, sha256, language string, sizeBytes int64) error {
	_, err := s.db.Exec(
		`INSERT INTO file_manifest (path,sha256,size_bytes,language,last_seen)
		 VALUES (?,?,?,?,?)
		 ON CONFLICT(path) DO UPDATE SET
		   sha256=excluded.sha256, size_bytes=excluded.size_bytes,
		   language=excluded.language, last_seen=excluded.last_seen`,
		path, sha256, sizeBytes, language, time.Now().UTC().Format(time.RFC3339),
	)
	return err
}

// GetManifest returns the stored manifest for a path, or ("","",0) if not found.
func (s *Store) GetManifest(path string) (sha256, language string, sizeBytes int64, err error) {
	err = s.db.QueryRow(
		`SELECT sha256, language, size_bytes FROM file_manifest WHERE path=?`, path,
	).Scan(&sha256, &language, &sizeBytes)
	if err == sql.ErrNoRows {
		return "", "", 0, nil
	}
	return
}
