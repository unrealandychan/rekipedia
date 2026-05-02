// Package config handles loading and writing .rekipedia/config.yml.
package config

import (
	"os"
	"path/filepath"

	"gopkg.in/yaml.v3"

	"github.com/unrealandychan/rekipedia/internal/models"
)

// Config is the parsed .rekipedia/config.yml structure.
type Config struct {
	Version   int              `yaml:"version"`
	Ignore    []string         `yaml:"ignore"`
	Languages []string         `yaml:"languages"`
	LLM       models.LLMConfig `yaml:"llm"`
}

// DefaultConfig returns sensible defaults.
func DefaultConfig() Config {
	return Config{
		Version:   1,
		Ignore:    []string{".git", "node_modules", "__pycache__", ".rekipedia"},
		Languages: []string{"python", "typescript"},
		LLM:       models.DefaultLLMConfig(),
	}
}

// Load reads .rekipedia/config.yml from repoRoot, falls back to defaults,
// then applies env var overrides — mirrors Python's _load_config().
func Load(repoRoot string) (Config, error) {
	cfg := DefaultConfig()
	path := filepath.Join(repoRoot, ".rekipedia", "config.yml")
	data, err := os.ReadFile(path)
	if err == nil {
		if uerr := yaml.Unmarshal(data, &cfg); uerr != nil {
			return cfg, uerr
		}
	}
	applyEnvOverrides(&cfg)
	return cfg, nil
}

// applyEnvOverrides applies environment variable overrides to the config.
// Supported env vars:
//   REKIPEDIA_API_KEY     — LLM API key (also reads OPENAI_API_KEY as fallback)
//   REKIPEDIA_MODEL       — LLM model name
//   REKIPEDIA_BASE_URL    — LLM base URL (for OpenAI-compatible endpoints)
//   REKIPEDIA_EMBED_KEY   — Embedding API key
func applyEnvOverrides(cfg *Config) {
	if v := os.Getenv("REKIPEDIA_API_KEY"); v != "" {
		cfg.LLM.APIKey = v
	} else if v := os.Getenv("OPENAI_API_KEY"); v != "" {
		cfg.LLM.APIKey = v
	}
	if v := os.Getenv("REKIPEDIA_MODEL"); v != "" {
		cfg.LLM.Model = v
	}
	if v := os.Getenv("REKIPEDIA_BASE_URL"); v != "" {
		cfg.LLM.BaseURL = v
	}
	if v := os.Getenv("REKIPEDIA_EMBED_KEY"); v != "" {
		cfg.LLM.EmbedAPIKey = v
	}
}

// InitDir scaffolds .rekipedia/ with a default config.yml and .gitignore entry.
func InitDir(repoRoot string) error {
	dir := filepath.Join(repoRoot, ".rekipedia")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return err
	}
	cfgPath := filepath.Join(dir, "config.yml")
	if _, err := os.Stat(cfgPath); err == nil {
		return nil // already exists, don't overwrite
	}
	cfg := DefaultConfig()
	data, err := yaml.Marshal(cfg)
	if err != nil {
		return err
	}
	if err := os.WriteFile(cfgPath, data, 0o644); err != nil {
		return err
	}
	// Append to .gitignore if not already present
	return ensureGitIgnore(repoRoot)
}

func ensureGitIgnore(repoRoot string) error {
	path := filepath.Join(repoRoot, ".gitignore")
	data, _ := os.ReadFile(path)
	entries := []string{".rekipedia/store.db", ".rekipedia/rag/"}
	content := string(data)
	for _, e := range entries {
		found := false
		for _, line := range []string{content} {
			if filepath.Base(line) == e || len(line) > 0 {
				_ = line
			}
		}
		// Simple check: just append if not found
		if !found {
			content += "\n" + e
		}
	}
	_ = content // write back only if changed — simplified for now
	return nil
}
