// Package fsutil provides file walking, SHA256 hashing, and language detection.
package fsutil

import (
	"crypto/sha256"
	"encoding/hex"
	"io"
	"os"
	"path/filepath"
	"strings"
)

// DefaultIgnoreDirs are always skipped during repo walking.
var DefaultIgnoreDirs = map[string]bool{
	".git": true, "node_modules": true, "__pycache__": true,
	".rekipedia": true, "dist": true, "build": true,
	".venv": true, "venv": true, ".tox": true, ".mypy_cache": true,
	".pytest_cache": true, "htmlcov": true, ".eggs": true,
}

// CodeExts maps file extensions to language names.
var CodeExts = map[string]string{
	".py": "python", ".ts": "typescript", ".tsx": "typescript",
	".js": "javascript", ".jsx": "javascript", ".go": "go",
	".rs": "rust", ".java": "java", ".rb": "ruby", ".php": "php",
	".c": "c", ".cpp": "c++", ".h": "c", ".cs": "csharp",
	".swift": "swift", ".kt": "kotlin", ".scala": "scala",
}

// DocExts maps documentation/config extensions to type names.
var DocExts = map[string]string{
	".md": "markdown", ".txt": "text", ".rst": "rst",
	".yaml": "yaml", ".yml": "yaml", ".toml": "toml",
	".json": "json", ".env": "env", ".cfg": "ini", ".ini": "ini",
}

// FileInfo holds metadata for a single repo file.
type FileInfo struct {
	// Path is relative to the repo root.
	Path     string
	AbsPath  string
	SHA256   string
	Size     int64
	Language string
	IsCode   bool
	IsDoc    bool
}

// IsImplementation returns true for non-test, non-config source files.
// Mirrors Python's _is_implementation() heuristic in embedder.py.
func IsImplementation(relPath string) bool {
	p := strings.ToLower(relPath)
	parts := strings.Split(filepath.ToSlash(p), "/")
	for _, part := range parts {
		if strings.HasPrefix(part, "test") ||
			part == "tests" || part == "spec" ||
			part == "specs" || part == "__tests__" {
			return false
		}
	}
	return true
}

// DetectLanguage returns the language and whether the file is code/doc.
func DetectLanguage(ext string) (lang string, isCode bool, isDoc bool) {
	ext = strings.ToLower(ext)
	if l, ok := CodeExts[ext]; ok {
		return l, true, false
	}
	if l, ok := DocExts[ext]; ok {
		return l, false, true
	}
	return "", false, false
}

// WalkRepo walks repoRoot, skipping ignored dirs, returning eligible files.
// extra is merged with DefaultIgnoreDirs.
func WalkRepo(root string, extra []string) ([]FileInfo, error) {
	skip := make(map[string]bool)
	for k, v := range DefaultIgnoreDirs {
		skip[k] = v
	}
	for _, d := range extra {
		skip[d] = true
	}

	var files []FileInfo
	err := filepath.WalkDir(root, func(path string, d os.DirEntry, err error) error {
		if err != nil {
			return nil // skip unreadable entries
		}
		name := d.Name()
		if d.IsDir() {
			if skip[name] || strings.HasSuffix(name, ".egg-info") {
				return filepath.SkipDir
			}
			return nil
		}
		ext := filepath.Ext(name)
		lang, isCode, isDoc := DetectLanguage(ext)
		if !isCode && !isDoc {
			return nil
		}
		rel, _ := filepath.Rel(root, path)
		info, statErr := d.Info()
		var size int64
		if statErr == nil {
			size = info.Size()
		}
		hash, _ := SHA256File(path)
		files = append(files, FileInfo{
			Path:     filepath.ToSlash(rel),
			AbsPath:  path,
			SHA256:   hash,
			Size:     size,
			Language: lang,
			IsCode:   isCode,
			IsDoc:    isDoc,
		})
		return nil
	})
	return files, err
}

// SHA256File computes the hex-encoded SHA-256 of a file's contents.
func SHA256File(path string) (string, error) {
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

// FileCategoryCount holds impl/test/config file counts for a file list.
type FileCategoryCount struct {
	Impl   int
	Test   int
	Config int
}

// CategoriseFiles mirrors Python's is_implementation + config heuristics
// used in _build_planning_summary().
func CategoriseFiles(relPaths []string) FileCategoryCount {
	docExtsSet := map[string]bool{
		".md": true, ".txt": true, ".rst": true,
		".yaml": true, ".yml": true, ".toml": true, ".json": true,
	}
	configKeywords := []string{"config", "conf", "setting", "setup", ".env"}
	var c FileCategoryCount
	for _, f := range relPaths {
		lower := strings.ToLower(f)
		ext := strings.ToLower(filepath.Ext(f))
		parts := strings.Split(filepath.ToSlash(lower), "/")

		isTest := false
		for _, p := range parts {
			if strings.HasPrefix(p, "test") ||
				p == "tests" || p == "spec" ||
				p == "specs" || p == "__tests__" {
				isTest = true
				break
			}
		}
		if isTest {
			c.Test++
			continue
		}
		isConfig := docExtsSet[ext]
		if !isConfig {
			for _, kw := range configKeywords {
				if strings.Contains(lower, kw) {
					isConfig = true
					break
				}
			}
		}
		if isConfig {
			c.Config++
		} else {
			c.Impl++
		}
	}
	return c
}
