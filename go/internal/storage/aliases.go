// Package storage — alias methods for orchestrator compatibility.
// These thin wrappers adapt the store's canonical method names to the
// names expected by the orchestrator layer.
package storage

import "github.com/unrealandychan/rekipedia/internal/models"

// UpsertRun creates or updates a run record.
func (s *Store) UpsertRun(runID, repoPath string) error {
	return s.CreateRun(runID, repoPath, "")
}

// UpsertSnapshot persists the list of FileManifests for a run.
func (s *Store) UpsertSnapshot(runID string, files []models.FileManifest) error {
	for _, f := range files {
		if err := s.UpsertManifest(f.Path, f.SHA256, f.Language, f.SizeBytes); err != nil {
			return err
		}
	}
	return nil
}

// GetSnapshot returns the FileManifests stored for a run.
// Current schema stores manifests globally (not per-run), so we return all.
func (s *Store) GetSnapshot(_ string) ([]models.FileManifest, error) {
	rows, err := s.db.Query(`SELECT path, sha256, language, size_bytes FROM manifest`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var files []models.FileManifest
	for rows.Next() {
		var f models.FileManifest
		if err := rows.Scan(&f.Path, &f.SHA256, &f.Language, &f.SizeBytes); err != nil {
			continue
		}
		files = append(files, f)
	}
	return files, rows.Err()
}

// GetLatestRunID returns the most recent run ID for the given repo path.
func (s *Store) GetLatestRunID(repoPath string) (string, error) {
	return s.LatestRunID(repoPath)
}

// UpsertSymbols saves symbols for a run.
func (s *Store) UpsertSymbols(runID string, syms []models.Symbol) error {
	return s.SaveSymbols(runID, syms)
}

// UpsertRelationships saves relationships for a run.
func (s *Store) UpsertRelationships(runID string, rels []models.Relationship) error {
	return s.SaveRelationships(runID, rels)
}

// GetAllSymbols returns all symbols for a run.
func (s *Store) GetAllSymbols(runID string) ([]models.Symbol, error) {
	return s.ListSymbols(runID)
}

// GetAllRelationships returns all relationships for a run.
func (s *Store) GetAllRelationships(runID string) ([]models.Relationship, error) {
	rows, err := s.db.Query(
		`SELECT from_sym, to_sym, kind, file FROM relationships WHERE run_id = ?`, runID,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var rels []models.Relationship
	for rows.Next() {
		var r models.Relationship
		var kind string
		if err := rows.Scan(&r.From, &r.To, &kind, &r.File); err != nil {
			continue
		}
		r.Kind = models.RelKind(kind)
		rels = append(rels, r)
	}
	return rels, rows.Err()
}

// UpsertPage saves a wiki page for a run.
func (s *Store) UpsertPage(runID, slug, title, content string) error {
	return s.UpsertWikiPage(runID, slug, title, "", content, 0, 0)
}

// SaveQAHistory persists a Q&A pair keyed by repoRoot (stored as run_id="repo:<repoRoot>").
func (s *Store) SaveQAHistory(repoRoot, question, answer string) error {
	return s.SaveQA("repo:"+repoRoot, question, answer)
}

// GetQAHistory returns all Q&A pairs for a repo, oldest first.
func (s *Store) GetQAHistory(repoRoot string) ([]models.QAHistory, error) {
	rows, err := s.db.Query(
		`SELECT question, answer, asked_at FROM qa_history WHERE run_id=? ORDER BY asked_at ASC`,
		"repo:"+repoRoot,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var hist []models.QAHistory
	for rows.Next() {
		var h models.QAHistory
		if err := rows.Scan(&h.Question, &h.Answer, &h.CreatedAt); err != nil {
			return nil, err
		}
		hist = append(hist, h)
	}
	return hist, rows.Err()
}

// QueryRunTime fills dest with the finished_at (or started_at) time for a run.
func (s *Store) QueryRunTime(runID string, dest *string) error {
	return s.db.QueryRow(
		`SELECT COALESCE(finished_at, started_at, '') FROM runs WHERE run_id=?`, runID,
	).Scan(dest)
}
