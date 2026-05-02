// Package rag provides file chunking, embedding, and vector search for rekipedia.
package rag

import (
	"fmt"
	"path/filepath"
	"strings"
)

// Chunk represents a text segment from a file.
type Chunk struct {
	ID        string `json:"id"`
	FilePath  string `json:"file_path"`
	StartLine string `json:"start_line"`
	EndLine   string `json:"end_line"`
	Text      string `json:"text"`
}

var codeExts = map[string]bool{
	".py": true, ".ts": true, ".tsx": true, ".js": true, ".jsx": true,
	".go": true, ".rs": true, ".java": true, ".kt": true, ".rb": true,
	".swift": true, ".cs": true, ".cpp": true, ".c": true, ".h": true,
	".html": true, ".css": true, ".scss": true,
}

var docExts = map[string]bool{
	".md": true, ".txt": true, ".rst": true, ".yaml": true, ".yml": true,
	".toml": true, ".json": true,
}

const (
	chunkSize    = 2000
	chunkOverlap = 200
	maxCodeSize  = 320000
	maxDocSize   = 32000
)

// ChunkFile splits a file's content into overlapping chunks.
// Returns nil if the file should be skipped.
func ChunkFile(path, content string) []Chunk {
	ext := strings.ToLower(filepath.Ext(path))
	isCode := codeExts[ext]
	isDoc := docExts[ext]

	if !isCode && !isDoc {
		return nil
	}

	maxSize := maxCodeSize
	if isDoc {
		maxSize = maxDocSize
	}
	if len(content) > maxSize {
		return nil
	}

	lines := strings.Split(content, "\n")

	var chunks []Chunk
	runes := []rune(content)
	total := len(runes)
	idx := 0
	chunkIdx := 0

	for idx < total {
		end := idx + chunkSize
		if end > total {
			end = total
		}
		text := string(runes[idx:end])

		// Compute start/end line numbers
		startLine := countLines(string(runes[:idx]), lines)
		endLine := startLine + strings.Count(text, "\n")

		chunks = append(chunks, Chunk{
			ID:        fmt.Sprintf("%s#%d", path, chunkIdx),
			FilePath:  path,
			StartLine: fmt.Sprintf("%d", startLine+1),
			EndLine:   fmt.Sprintf("%d", endLine+1),
			Text:      text,
		})
		chunkIdx++

		if end == total {
			break
		}
		idx += chunkSize - chunkOverlap
	}

	return chunks
}

func countLines(before string, _ []string) int {
	return strings.Count(before, "\n")
}
