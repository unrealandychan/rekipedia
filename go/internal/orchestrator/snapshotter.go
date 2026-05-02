// Package orchestrator wires together all rekipedia subsystems.
//
// This file provides the Snapshotter, which walks a repository root and
// produces a list of FileManifest objects with SHA-256 hashes.
package orchestrator

import (
	"crypto/sha256"
	"encoding/hex"
	"io"
	"os"
	"path/filepath"
	"strings"

	"github.com/unrealandychan/rekipedia/internal/models"
)

// languageMap maps file extensions to language names.
var languageMap = map[string]string{
	".py":         "python",
	".ts":         "typescript",
	".tsx":        "typescript",
	".js":         "javascript",
	".jsx":        "javascript",
	".go":         "go",
	".rs":         "rust",
	".java":       "java",
	".kt":         "kotlin",
	".rb":         "ruby",
	".md":         "markdown",
	".yaml":       "yaml",
	".yml":        "yaml",
	".json":       "json",
	".toml":       "toml",
	".sql":        "sql",
	".sh":         "shell",
	".bash":       "shell",
	".zsh":        "shell",
	".tf":         "terraform",
	".html":       "html",
	".css":        "css",
	".scss":       "scss",
	".dockerfile": "docker",
	".c":          "c",
	".cpp":        "cpp",
	".h":          "c",
}

var defaultIgnore = []string{
	".git", ".rekipedia", "__pycache__", "node_modules",
	"dist", "build", ".venv", "venv", ".env",
	".mypy_cache", ".pytest_cache", ".tox", "htmlcov",
	"*.pyc", "*.egg-info", ".DS_Store",
}

// Snapshotter walks a repo root and produces FileManifest entries.
type Snapshotter struct {
	root        string
	ignoreGlobs []string
	ignoreDirs  map[string]bool
	languages   map[string]bool // nil = all
}

// NewSnapshotter creates a Snapshotter for the given repo root.
// extraIgnore adds additional gitignore-style patterns.
// languages, if non-empty, restricts files to those languages (lowercase).
func NewSnapshotter(root string, extraIgnore []string, languages []string) *Snapshotter {
	all := append(defaultIgnore, extraIgnore...)
	dirs := make(map[string]bool)
	var globs []string
	for _, pat := range all {
		if !strings.Contains(pat, "*") && !strings.Contains(pat, "/") {
			dirs[pat] = true
		} else {
			globs = append(globs, pat)
		}
	}
	var langSet map[string]bool
	if len(languages) > 0 {
		langSet = make(map[string]bool, len(languages))
		for _, l := range languages {
			langSet[strings.ToLower(l)] = true
		}
	}
	return &Snapshotter{root: root, ignoreGlobs: globs, ignoreDirs: dirs, languages: langSet}
}

// Snapshot walks the repository and returns all relevant files.
func (s *Snapshotter) Snapshot() ([]models.FileManifest, error) {
	var manifests []models.FileManifest

	err := filepath.WalkDir(s.root, func(path string, d os.DirEntry, err error) error {
		if err != nil {
			return nil // skip unreadable entries
		}

		rel, _ := filepath.Rel(s.root, path)
		rel = filepath.ToSlash(rel)

		if d.IsDir() {
			// Never skip the root itself (path == s.root or rel == ".")
			if path == s.root || rel == "." {
				return nil
			}
			base := d.Name()
			if s.ignoreDirs[base] || strings.HasPrefix(base, ".") {
				return filepath.SkipDir
			}
			return nil
		}

		// Check glob patterns
		base := filepath.Base(path)
		for _, glob := range s.ignoreGlobs {
			if matched, _ := filepath.Match(glob, base); matched {
				return nil
			}
		}

		info, err := d.Info()
		if err != nil {
			return nil
		}
		if info.Size() == 0 {
			return nil
		}

		hash, err := sha256File(path)
		if err != nil {
			return nil
		}

		lang := detectLanguage(path)
		if s.languages != nil && !s.languages[lang] {
			return nil
		}
		manifests = append(manifests, models.FileManifest{
			Path:      rel,
			SHA256:    hash,
			SizeBytes: info.Size(),
			Language:  lang,
		})
		return nil
	})

	return manifests, err
}

func sha256File(path string) (string, error) {
	f, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer f.Close()
	h := sha256.New()
	if _, err := io.Copy(h, f); err != nil {
		return "", err
	}
	return hex.EncodeToString(h.Sum(nil)), nil
}

func detectLanguage(path string) string {
	base := strings.ToLower(filepath.Base(path))
	if base == "dockerfile" {
		return "docker"
	}
	ext := strings.ToLower(filepath.Ext(path))
	if lang, ok := languageMap[ext]; ok {
		return lang
	}
	return ""
}
