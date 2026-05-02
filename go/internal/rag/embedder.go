package rag

import (
	"context"
	"fmt"
	"os"
	"path/filepath"

	"github.com/unrealandychan/rekipedia/internal/llm"
	"github.com/unrealandychan/rekipedia/internal/models"
	"github.com/unrealandychan/rekipedia/pkg/fsutil"
)

// EmbedPipeline builds and queries a vector index for a repository.
type EmbedPipeline struct {
	outputDir string
	llmClient *llm.Client
}

// NewEmbedPipeline creates an EmbedPipeline.
func NewEmbedPipeline(outputDir string, cfg models.LLMConfig) *EmbedPipeline {
	return &EmbedPipeline{
		outputDir: outputDir,
		llmClient: llm.New(cfg),
	}
}

// Build walks repoRoot, chunks files, embeds in batches, and saves the VectorStore.
// Returns the total number of chunks embedded.
func (e *EmbedPipeline) Build(repoRoot string, progress func(string)) (int, error) {
	log := func(msg string) {
		if progress != nil {
			progress(msg)
		}
	}

	// Walk repo
	fileInfos, err := fsutil.WalkRepo(repoRoot, nil)
	if err != nil {
		return 0, fmt.Errorf("walk repo: %w", err)
	}

	var chunks []Chunk
	for _, fi := range fileInfos {
		data, err := os.ReadFile(fi.AbsPath)
		if err != nil {
			continue
		}
		cs := ChunkFile(fi.Path, string(data))
		chunks = append(chunks, cs...)
	}
	log(fmt.Sprintf("Chunked %d files → %d chunks", len(fileInfos), len(chunks)))

	store := NewVectorStore()
	batchSize := 100
	ctx := context.Background()

	for i := 0; i < len(chunks); i += batchSize {
		end := i + batchSize
		if end > len(chunks) {
			end = len(chunks)
		}
		batch := chunks[i:end]
		texts := make([]string, len(batch))
		for j, c := range batch {
			texts[j] = c.Text
		}
		embeddings, err := e.llmClient.Embed(ctx, texts)
		if err != nil {
			return 0, fmt.Errorf("embed batch %d: %w", i/batchSize, err)
		}
		for j, emb := range embeddings {
			store.Add(batch[j], emb)
		}
		log(fmt.Sprintf("Embedded %d/%d chunks", min(i+batchSize, len(chunks)), len(chunks)))
	}

	storeDir := filepath.Join(e.outputDir, "vectors")
	if err := store.Save(storeDir); err != nil {
		return 0, fmt.Errorf("save vector store: %w", err)
	}
	log(fmt.Sprintf("Vector store saved to %s", storeDir))
	return len(chunks), nil
}

// Search embeds the query and returns the top-K results from the vector store.
func (e *EmbedPipeline) Search(query string, topK int) ([]SearchResult, error) {
	storeDir := filepath.Join(e.outputDir, "vectors")
	store := NewVectorStore()
	if err := store.Load(storeDir); err != nil {
		return nil, fmt.Errorf("load vector store: %w", err)
	}
	ctx := context.Background()
	embeddings, err := e.llmClient.Embed(ctx, []string{query})
	if err != nil {
		return nil, fmt.Errorf("embed query: %w", err)
	}
	if len(embeddings) == 0 {
		return nil, fmt.Errorf("no embedding returned")
	}
	return store.Search(embeddings[0], topK), nil
}

func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}
