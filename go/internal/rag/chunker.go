// Package rag provides file chunking, embedding, and vector search for close-wiki.
package rag

import (
	"fmt"
	"path/filepath"
	"regexp"
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
	minChunkRune = 200 // merge chunks smaller than this with the next one
)

// reGoTopLevel matches the first line of a top-level Go declaration.
// Groups: (1) keyword — func/type/var/const
var reGoTopLevel = regexp.MustCompile(`^(?:func|type|var|const)\s`)

// reGoComment matches a full-line comment.
var reGoComment = regexp.MustCompile(`^//`)

// ChunkFile splits a file's content into overlapping chunks.
// For .go files it uses symbol-boundary chunking (func/type/var/const boundaries).
// For other code/doc files it falls back to the line-boundary sliding-window strategy.
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

	if ext == ".go" {
		return chunkGo(path, content)
	}
	return chunkWindow(path, content)
}

// ---------------------------------------------------------------------------
// Go AST-aware chunker
// ---------------------------------------------------------------------------

// chunkGo splits a .go file at top-level declaration boundaries.
// Strategy (mirrors Python _symbol_chunk_file):
//  1. Identify "boundary lines" — lines that start a top-level declaration.
//  2. Group lines between boundaries into segments.
//  3. Merge segments that are too small (< minChunkRune runes) with the next.
//  4. If a segment exceeds chunkSize, further split it with chunkWindow.
func chunkGo(path, content string) []Chunk {
	lines := strings.Split(content, "\n")
	// Collect boundary line indices (0-based).
	boundaries := []int{0}
	for i, line := range lines {
		if i == 0 {
			continue
		}
		trimmed := strings.TrimSpace(line)
		if trimmed == "" {
			continue
		}
		// A top-level declaration starts at column 0 (no leading whitespace)
		// and matches func/type/var/const.
		if reGoTopLevel.MatchString(line) {
			boundaries = append(boundaries, i)
		}
	}
	boundaries = append(boundaries, len(lines))

	// Build raw segments between boundaries.
	type segment struct {
		startLine int // 1-based
		endLine   int // 1-based inclusive
		text      string
	}
	var segments []segment
	for i := 0; i < len(boundaries)-1; i++ {
		start := boundaries[i]
		end := boundaries[i+1]
		segLines := lines[start:end]
		text := strings.Join(segLines, "\n")
		segments = append(segments, segment{
			startLine: start + 1,
			endLine:   end, // end is exclusive boundary, so last line = end-1+1 = end
			text:      text,
		})
	}

	// Merge small segments forward.
	merged := make([]segment, 0, len(segments))
	for _, seg := range segments {
		if len(merged) > 0 && len([]rune(merged[len(merged)-1].text)) < minChunkRune {
			prev := merged[len(merged)-1]
			merged[len(merged)-1] = segment{
				startLine: prev.startLine,
				endLine:   seg.endLine,
				text:      prev.text + "\n" + seg.text,
			}
		} else {
			merged = append(merged, seg)
		}
	}

	// Emit chunks — split oversized segments with chunkWindow.
	var chunks []Chunk
	chunkIdx := 0
	for _, seg := range merged {
		runes := []rune(seg.text)
		if len(runes) <= chunkSize {
			if strings.TrimSpace(seg.text) == "" {
				continue
			}
			chunks = append(chunks, Chunk{
				ID:        fmt.Sprintf("%s#%d", path, chunkIdx),
				FilePath:  path,
				StartLine: fmt.Sprintf("%d", seg.startLine),
				EndLine:   fmt.Sprintf("%d", seg.endLine),
				Text:      seg.text,
			})
			chunkIdx++
		} else {
			// Oversized: window-chunk the segment, preserving line offsets.
			sub := chunkWindow(path, seg.text)
			for _, sc := range sub {
				// Adjust line numbers by segment offset.
				startOff := seg.startLine - 1
				sl := parseLineNum(sc.StartLine) + startOff
				el := parseLineNum(sc.EndLine) + startOff
				chunks = append(chunks, Chunk{
					ID:        fmt.Sprintf("%s#%d", path, chunkIdx),
					FilePath:  path,
					StartLine: fmt.Sprintf("%d", sl),
					EndLine:   fmt.Sprintf("%d", el),
					Text:      sc.Text,
				})
				chunkIdx++
			}
		}
	}
	return chunks
}

// ---------------------------------------------------------------------------
// Line-boundary sliding window (used for non-Go code + docs)
// ---------------------------------------------------------------------------

// chunkWindow chunks content using a sliding window that never splits mid-line.
func chunkWindow(path, content string) []Chunk {
	lines := strings.Split(content, "\n")
	runes := []rune(content)
	total := len(runes)

	var chunks []Chunk
	idx := 0
	chunkIdx := 0

	for idx < total {
		end := idx + chunkSize
		if end > total {
			end = total
		}

		// Snap end to nearest newline (don't split mid-line)
		if end < total {
			for end > idx && runes[end] != '\n' {
				end--
			}
			if end == idx {
				end = idx + chunkSize // no newline found, accept mid-line split
				if end > total {
					end = total
				}
			}
		}

		text := string(runes[idx:end])
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

func parseLineNum(s string) int {
	n := 0
	for _, c := range s {
		if c >= '0' && c <= '9' {
			n = n*10 + int(c-'0')
		}
	}
	return n
}
