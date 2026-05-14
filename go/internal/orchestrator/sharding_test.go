package orchestrator

import (
	"os"
	"testing"

	"github.com/unrealandychan/close-wiki/internal/models"
)

func makeFiles(n int, sizeBytes int64) []models.FileManifest {
	files := make([]models.FileManifest, n)
	for i := range files {
		files[i] = models.FileManifest{
			Path:      "src/file" + string(rune('A'+i)) + ".go",
			SHA256:    "abc",
			SizeBytes: sizeBytes,
		}
	}
	return files
}

// ---------------------------------------------------------------------------
// Issue #87: default budget alignment + env var override
// ---------------------------------------------------------------------------

func TestDefaultTokenBudget_Is40000(t *testing.T) {
	if defaultTokenBudget != 40000 {
		t.Errorf("expected defaultTokenBudget=40000, got %d", defaultTokenBudget)
	}
}

func TestResolveTokenBudget_ExplicitOverride(t *testing.T) {
	got := resolveTokenBudget(8000)
	if got != 8000 {
		t.Errorf("expected 8000, got %d", got)
	}
}

func TestResolveTokenBudget_EnvVar(t *testing.T) {
	t.Setenv("REKIPEDIA_SHARD_TOKEN_BUDGET", "25000")
	got := resolveTokenBudget(0)
	if got != 25000 {
		t.Errorf("expected 25000 from env, got %d", got)
	}
}

func TestResolveTokenBudget_InvalidEnvFallsBack(t *testing.T) {
	t.Setenv("REKIPEDIA_SHARD_TOKEN_BUDGET", "notanumber")
	got := resolveTokenBudget(0)
	if got != defaultTokenBudget {
		t.Errorf("expected fallback %d on invalid env, got %d", defaultTokenBudget, got)
	}
}

func TestResolveTokenBudget_NoEnvFallsBack(t *testing.T) {
	os.Unsetenv("REKIPEDIA_SHARD_TOKEN_BUDGET")
	got := resolveTokenBudget(0)
	if got != defaultTokenBudget {
		t.Errorf("expected default %d, got %d", defaultTokenBudget, got)
	}
}

func TestNewShardPlanner_UsesEnvVar(t *testing.T) {
	t.Setenv("REKIPEDIA_SHARD_TOKEN_BUDGET", "5000")
	sp := NewShardPlanner(0)
	if sp.budget != 5000 {
		t.Errorf("expected budget 5000 from env, got %d", sp.budget)
	}
}

// ---------------------------------------------------------------------------
// Existing plan behaviour (regression)
// ---------------------------------------------------------------------------

func TestPlan_Empty(t *testing.T) {
	sp := NewShardPlanner(40000)
	if got := sp.Plan(nil); got != nil {
		t.Error("expected nil for empty input")
	}
}

func TestPlan_SingleFile(t *testing.T) {
	sp := NewShardPlanner(40000)
	shards := sp.Plan(makeFiles(1, 1000))
	if len(shards) != 1 {
		t.Errorf("expected 1 shard, got %d", len(shards))
	}
}

func TestPlan_SplitsOversizedGroup(t *testing.T) {
	// 3 files × 4000 bytes = 1000 tokens each; budget = 1000 → each file = own shard
	sp := NewShardPlanner(1000)
	shards := sp.Plan(makeFiles(3, 4000))
	if len(shards) != 3 {
		t.Errorf("expected 3 shards, got %d", len(shards))
	}
}

func TestPlan_ShardIDs_Unique(t *testing.T) {
	sp := NewShardPlanner(1000)
	shards := sp.Plan(makeFiles(5, 4001))
	seen := map[string]bool{}
	for _, s := range shards {
		if seen[s.ShardID] {
			t.Errorf("duplicate shard ID: %s", s.ShardID)
		}
		seen[s.ShardID] = true
	}
}
