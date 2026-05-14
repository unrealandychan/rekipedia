// Package orchestrator — ShardPlanner groups files into token-budget shards.
package orchestrator

import (
	"os"
	"path/filepath"
	"strconv"
	"strings"

	"github.com/unrealandychan/close-wiki/internal/models"
)

const (
	bytesPerToken      = 4     // ~4 bytes per token
	defaultTokenBudget = 40000 // max tokens per shard; aligned with Python runtime
)

// resolveTokenBudget returns the effective token budget.
// Checks REKIPEDIA_SHARD_TOKEN_BUDGET env var first; falls back to defaultTokenBudget.
func resolveTokenBudget(override int) int {
	if override > 0 {
		return override
	}
	if v := os.Getenv("REKIPEDIA_SHARD_TOKEN_BUDGET"); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n > 0 {
			return n
		}
	}
	return defaultTokenBudget
}

// ShardPlanner groups FileManifest entries into shards that fit within a token budget.
type ShardPlanner struct {
	budget int
}

// NewShardPlanner creates a ShardPlanner with the given token budget.
// If budget ≤ 0, checks REKIPEDIA_SHARD_TOKEN_BUDGET env var, then falls back to 40 000.
func NewShardPlanner(budget int) *ShardPlanner {
	return &ShardPlanner{budget: resolveTokenBudget(budget)}
}

// Plan groups files by top-level directory and splits groups that exceed the budget.
func (sp *ShardPlanner) Plan(files []models.FileManifest) []models.Shard {
	if len(files) == 0 {
		return nil
	}

	// Group by top-level directory
	groups := make(map[string][]models.FileManifest)
	var order []string
	seen := make(map[string]bool)
	for _, f := range files {
		top := topLevelDir(f.Path)
		if !seen[top] {
			order = append(order, top)
			seen[top] = true
		}
		groups[top] = append(groups[top], f)
	}

	var shards []models.Shard
	for _, dir := range order {
		shards = append(shards, sp.splitGroup(dir, groups[dir])...)
	}
	return shards
}

func (sp *ShardPlanner) splitGroup(groupDir string, files []models.FileManifest) []models.Shard {
	var shards []models.Shard
	var bucket []models.FileManifest
	bucketTokens := 0
	bucketIdx := 0

	for _, f := range files {
		fileTokens := fileTokenEstimate(f.SizeBytes)
		if len(bucket) > 0 && bucketTokens+fileTokens > sp.budget {
			shards = append(shards, makeShard(groupDir, bucketIdx, bucket))
			bucket = nil
			bucketTokens = 0
			bucketIdx++
		}
		bucket = append(bucket, f)
		bucketTokens += fileTokens
	}
	if len(bucket) > 0 {
		shards = append(shards, makeShard(groupDir, bucketIdx, bucket))
	}
	return shards
}

func makeShard(groupDir string, idx int, files []models.FileManifest) models.Shard {
	id := groupDir
	if idx > 0 {
		id = groupDir + "#" + string(rune('0'+idx))
	}
	return models.Shard{
		ShardID: id,
		Root:    groupDir,
		Files:   files,
	}
}

func topLevelDir(path string) string {
	path = filepath.ToSlash(path)
	parts := strings.SplitN(path, "/", 2)
	if len(parts) > 1 {
		return parts[0]
	}
	return "."
}

func fileTokenEstimate(sizeBytes int64) int {
	tokens := int(sizeBytes) / bytesPerToken
	if tokens < 1 {
		return 1
	}
	return tokens
}
