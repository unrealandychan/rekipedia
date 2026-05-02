package rag

import (
	"context"
	"fmt"
	"os"
	"path/filepath"

	chromem "github.com/philippgille/chromem-go"
)

const collectionName = "rekipedia"

// VectorStore wraps chromem-go for persistent vector search.
type VectorStore struct {
	db  *chromem.DB
	col *chromem.Collection
}

// SearchResult holds a matched chunk and its similarity score.
type SearchResult struct {
	Chunk Chunk   `json:"chunk"`
	Score float32 `json:"score"`
}

// NewVectorStore creates an empty in-memory VectorStore.
func NewVectorStore() *VectorStore {
	return &VectorStore{db: chromem.NewDB()}
}

// ensureCollection lazily creates the collection on first Add.
func (v *VectorStore) ensureCollection() error {
	if v.col != nil {
		return nil
	}
	col, err := v.db.GetOrCreateCollection(collectionName, nil, nil)
	if err != nil {
		return err
	}
	v.col = col
	return nil
}

// Add inserts a chunk with its pre-computed embedding vector.
func (v *VectorStore) Add(chunk Chunk, embedding []float32) {
	if err := v.ensureCollection(); err != nil {
		return
	}
	doc := chromem.Document{
		ID:        chunk.ID,
		Content:   chunk.Text,
		Embedding: embedding,
		Metadata: map[string]string{
			"file_path":  chunk.FilePath,
			"start_line": chunk.StartLine,
			"end_line":   chunk.EndLine,
		},
	}
	_ = v.col.AddDocument(context.Background(), doc)
}

// Len returns the number of stored vectors.
func (v *VectorStore) Len() int {
	if v.col == nil {
		return 0
	}
	return v.col.Count()
}

// Search returns the top-K most similar chunks to the query vector.
func (v *VectorStore) Search(query []float32, topK int) []SearchResult {
	if v.col == nil || v.col.Count() == 0 {
		return nil
	}
	results, err := v.col.QueryEmbedding(context.Background(), query, topK, nil, nil)
	if err != nil {
		return nil
	}
	out := make([]SearchResult, 0, len(results))
	for _, r := range results {
		out = append(out, SearchResult{
			Chunk: Chunk{
				ID:        r.ID,
				FilePath:  r.Metadata["file_path"],
				StartLine: r.Metadata["start_line"],
				EndLine:   r.Metadata["end_line"],
				Text:      r.Content,
			},
			Score: r.Similarity,
		})
	}
	return out
}

// Save persists the vector store to dir.
func (v *VectorStore) Save(dir string) error {
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return err
	}
	exportPath := filepath.Join(dir, "chromem.gob")
	if err := v.db.ExportToFile(exportPath, true, ""); err != nil {
		return fmt.Errorf("export chromem: %w", err)
	}
	return nil
}

// Load reads a previously saved vector store from dir.
func (v *VectorStore) Load(dir string) error {
	exportPath := filepath.Join(dir, "chromem.gob")
	if err := v.db.ImportFromFile(exportPath, ""); err != nil {
		return fmt.Errorf("import chromem: %w", err)
	}
	v.col = v.db.GetCollection(collectionName, nil)
	if v.col == nil {
		return fmt.Errorf("collection %q not found after import", collectionName)
	}
	return nil
}
