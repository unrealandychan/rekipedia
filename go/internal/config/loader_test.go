package config

import (
	"os"
	"path/filepath"
	"testing"
)

func TestDefaultConfig(t *testing.T) {
	cfg := DefaultConfig()
	if cfg.Version != 1 {
		t.Errorf("expected version 1, got %d", cfg.Version)
	}
	if cfg.LLM.Model != "ollama/llama4" {
		t.Errorf("expected model ollama/llama4, got %s", cfg.LLM.Model)
	}
	if len(cfg.Ignore) == 0 {
		t.Error("expected non-empty ignore list")
	}
}

func TestLoadMissingFile(t *testing.T) {
	tmp := t.TempDir()
	cfg, err := Load(tmp)
	if err != nil {
		t.Fatalf("Load returned error for missing config: %v", err)
	}
	// Should fall back to defaults
	if cfg.LLM.Model != "ollama/llama4" {
		t.Errorf("expected default model, got %s", cfg.LLM.Model)
	}
}

func TestLoadFromFile(t *testing.T) {
	tmp := t.TempDir()
	dir := filepath.Join(tmp, ".rekipedia")
	_ = os.MkdirAll(dir, 0o755)
	yaml := "version: 1\nllm:\n  model: gpt-4o\n  temperature: 0.5\n"
	_ = os.WriteFile(filepath.Join(dir, "config.yml"), []byte(yaml), 0o644)

	cfg, err := Load(tmp)
	if err != nil {
		t.Fatalf("Load error: %v", err)
	}
	if cfg.LLM.Model != "gpt-4o" {
		t.Errorf("expected gpt-4o, got %s", cfg.LLM.Model)
	}
	if cfg.LLM.Temperature != 0.5 {
		t.Errorf("expected temperature 0.5, got %f", cfg.LLM.Temperature)
	}
}

func TestEnvOverride(t *testing.T) {
	tmp := t.TempDir()
	t.Setenv("REKIPEDIA_MODEL", "gpt-override")
	t.Setenv("REKIPEDIA_API_KEY", "sk-override")
	t.Setenv("REKIPEDIA_BASE_URL", "https://custom.api/v1")

	cfg, _ := Load(tmp)
	if cfg.LLM.Model != "gpt-override" {
		t.Errorf("expected REKIPEDIA_MODEL override, got %q", cfg.LLM.Model)
	}
	if cfg.LLM.APIKey != "sk-override" {
		t.Errorf("expected REKIPEDIA_API_KEY override, got %q", cfg.LLM.APIKey)
	}
	if cfg.LLM.BaseURL != "https://custom.api/v1" {
		t.Errorf("expected REKIPEDIA_BASE_URL override, got %q", cfg.LLM.BaseURL)
	}
}

func TestEnvOverrideFallbackOpenAI(t *testing.T) {
	tmp := t.TempDir()
	t.Setenv("OPENAI_API_KEY", "sk-openai-fallback")

	cfg, _ := Load(tmp)
	if cfg.LLM.APIKey != "sk-openai-fallback" {
		t.Errorf("expected OPENAI_API_KEY fallback, got %q", cfg.LLM.APIKey)
	}
}

func TestInitDir(t *testing.T) {
	tmp := t.TempDir()
	if err := InitDir(tmp); err != nil {
		t.Fatalf("InitDir error: %v", err)
	}
	cfgPath := filepath.Join(tmp, ".rekipedia", "config.yml")
	if _, err := os.Stat(cfgPath); err != nil {
		t.Errorf("config.yml not created: %v", err)
	}
}

func TestInitDirIdempotent(t *testing.T) {
	tmp := t.TempDir()
	_ = InitDir(tmp)
	// Second call should not error
	if err := InitDir(tmp); err != nil {
		t.Fatalf("second InitDir call failed: %v", err)
	}
}
