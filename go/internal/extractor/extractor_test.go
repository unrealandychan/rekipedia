package extractor

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/unrealandychan/rekipedia/internal/models"
)

// ── helpers ──────────────────────────────────────────────────────────────────

func writeTempFile(t *testing.T, name, content string) (absPath, relPath string) {
	t.Helper()
	dir := t.TempDir()
	abs := filepath.Join(dir, name)
	_ = os.WriteFile(abs, []byte(content), 0o644)
	return abs, name
}

func symbolNames(syms []models.Symbol) []string {
	names := make([]string, len(syms))
	for i, s := range syms {
		names[i] = s.Name
	}
	return names
}

func hasSymbol(syms []models.Symbol, name string, kind models.SymbolKind) bool {
	for _, s := range syms {
		if s.Name == name && s.Kind == kind {
			return true
		}
	}
	return false
}

func hasRelationship(rels []models.Relationship, to string, kind models.RelKind) bool {
	for _, r := range rels {
		if r.To == to && r.Kind == kind {
			return true
		}
	}
	return false
}

// ── Python extractor tests ────────────────────────────────────────────────────

func TestPythonCanHandle(t *testing.T) {
	e := NewPythonExtractor()
	if !e.CanHandle(".py") {
		t.Error("should handle .py")
	}
	if !e.CanHandle(".pyw") {
		t.Error("should handle .pyw")
	}
	if e.CanHandle(".ts") {
		t.Error("should not handle .ts")
	}
}

func TestPythonFunctions(t *testing.T) {
	src := `
def greet(name: str) -> str:
    """Return greeting."""
    return f"hello {name}"

async def fetch(url: str):
    pass
`
	abs, rel := writeTempFile(t, "greet.py", src)
	e := NewPythonExtractor()
	r := e.Extract(abs, rel)

	if !hasSymbol(r.Symbols, "greet", models.SymbolFunction) {
		t.Errorf("expected 'greet' function, got %v", symbolNames(r.Symbols))
	}
	if !hasSymbol(r.Symbols, "fetch", models.SymbolFunction) {
		t.Errorf("expected 'fetch' function, got %v", symbolNames(r.Symbols))
	}
}

func TestPythonClass(t *testing.T) {
	src := `
class Animal:
    """Base animal."""
    def __init__(self, name: str):
        self.name = name

    def speak(self):
        pass

class Dog(Animal):
    def speak(self):
        return "Woof"
`
	abs, rel := writeTempFile(t, "animal.py", src)
	e := NewPythonExtractor()
	r := e.Extract(abs, rel)

	if !hasSymbol(r.Symbols, "Animal", models.SymbolClass) {
		t.Errorf("expected class 'Animal', got %v", symbolNames(r.Symbols))
	}
	if !hasSymbol(r.Symbols, "Dog", models.SymbolClass) {
		t.Errorf("expected class 'Dog'")
	}
	if !hasSymbol(r.Symbols, "Animal.__init__", models.SymbolFunction) {
		t.Errorf("expected method 'Animal.__init__', got %v", symbolNames(r.Symbols))
	}
	if !hasSymbol(r.Symbols, "Animal.speak", models.SymbolFunction) {
		t.Errorf("expected method 'Animal.speak'")
	}
}

func TestPythonImports(t *testing.T) {
	src := `
import os
import sys
from pathlib import Path
from collections import defaultdict, OrderedDict
`
	abs, rel := writeTempFile(t, "imports.py", src)
	e := NewPythonExtractor()
	r := e.Extract(abs, rel)

	if !hasRelationship(r.Relationships, "os", models.RelImport) {
		t.Error("expected import 'os'")
	}
	if !hasRelationship(r.Relationships, "sys", models.RelImport) {
		t.Error("expected import 'sys'")
	}
	if !hasRelationship(r.Relationships, "pathlib", models.RelImport) {
		t.Error("expected import 'pathlib'")
	}
	if !hasRelationship(r.Relationships, "collections", models.RelImport) {
		t.Error("expected import 'collections'")
	}
}

func TestPythonEntryPoint(t *testing.T) {
	src := `
def main():
    print("hello")

if __name__ == "__main__":
    main()
`
	abs, rel := writeTempFile(t, "main.py", src)
	e := NewPythonExtractor()
	r := e.Extract(abs, rel)

	if len(r.EntryPoints) == 0 {
		t.Error("expected entry point for if __name__ == '__main__'")
	}
}

func TestPythonUnreadable(t *testing.T) {
	e := NewPythonExtractor()
	r := e.Extract("/nonexistent/file.py", "file.py")
	if len(r.Risks) == 0 {
		t.Error("expected risk for unreadable file")
	}
}

func TestPythonFilesSeen(t *testing.T) {
	src := "x = 1\n"
	abs, rel := writeTempFile(t, "x.py", src)
	e := NewPythonExtractor()
	r := e.Extract(abs, rel)
	if len(r.FilesSeen) != 1 || r.FilesSeen[0] != rel {
		t.Errorf("expected FilesSeen=[%s], got %v", rel, r.FilesSeen)
	}
}

// ── TypeScript extractor tests ────────────────────────────────────────────────

func TestTSCanHandle(t *testing.T) {
	e := NewTypeScriptExtractor()
	for _, ext := range []string{".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"} {
		if !e.CanHandle(ext) {
			t.Errorf("should handle %s", ext)
		}
	}
	if e.CanHandle(".py") {
		t.Error("should not handle .py")
	}
}

func TestTSFunctions(t *testing.T) {
	src := `
export function greet(name: string): string {
	return "Hello " + name;
}

export async function fetchData(url: string) {
  return fetch(url);
}

const handler = (req: Request, res: Response) => {
  res.send('ok');
}
`
	abs, rel := writeTempFile(t, "greet.ts", src)
	e := NewTypeScriptExtractor()
	r := e.Extract(abs, rel)

	if !hasSymbol(r.Symbols, "greet", models.SymbolFunction) {
		t.Errorf("expected 'greet', got %v", symbolNames(r.Symbols))
	}
	if !hasSymbol(r.Symbols, "fetchData", models.SymbolFunction) {
		t.Errorf("expected 'fetchData'")
	}
}

func TestTSClass(t *testing.T) {
	src := `
export class UserService extends BaseService {
  private users: User[] = [];
}

export abstract class BaseService {
  abstract doWork(): void;
}
`
	abs, rel := writeTempFile(t, "service.ts", src)
	e := NewTypeScriptExtractor()
	r := e.Extract(abs, rel)

	if !hasSymbol(r.Symbols, "UserService", models.SymbolClass) {
		t.Errorf("expected 'UserService' class, got %v", symbolNames(r.Symbols))
	}
	if !hasRelationship(r.Relationships, "BaseService", models.RelInherits) {
		t.Error("expected inherits relationship to BaseService")
	}
}

func TestTSInterface(t *testing.T) {
	src := `
export interface User {
  id: number;
  name: string;
}

export type UserId = string | number;

export enum Status {
  Active = 'active',
  Inactive = 'inactive',
}
`
	abs, rel := writeTempFile(t, "types.ts", src)
	e := NewTypeScriptExtractor()
	r := e.Extract(abs, rel)

	if !hasSymbol(r.Symbols, "User", models.SymbolInterface) {
		t.Errorf("expected interface 'User', got %v", symbolNames(r.Symbols))
	}
	if !hasSymbol(r.Symbols, "UserId", models.SymbolType) {
		t.Errorf("expected type 'UserId'")
	}
	if !hasSymbol(r.Symbols, "Status", models.SymbolEnum) {
		t.Errorf("expected enum 'Status'")
	}
}

func TestTSImports(t *testing.T) {
	src := `
import React from 'react';
import { useState, useEffect } from 'react';
import type { FC } from 'react';
const path = require('path');
`
	abs, rel := writeTempFile(t, "app.tsx", src)
	e := NewTypeScriptExtractor()
	r := e.Extract(abs, rel)

	if !hasRelationship(r.Relationships, "react", models.RelImport) {
		t.Errorf("expected import 'react', got %v", r.Relationships)
	}
	if !hasRelationship(r.Relationships, "path", models.RelImport) {
		t.Error("expected import 'path'")
	}
}

// ── Config extractor tests ────────────────────────────────────────────────────

func TestConfigCanHandle(t *testing.T) {
	e := NewConfigExtractor()
	for _, ext := range []string{".toml", ".json", ".yaml", ".yml", ".mod"} {
		if !e.CanHandle(ext) {
			t.Errorf("should handle %s", ext)
		}
	}
}

func TestConfigPackageJSON(t *testing.T) {
	src := `{
  "name": "my-app",
  "main": "src/index.js",
  "scripts": {
    "build": "tsc",
    "test": "jest",
    "start": "node dist/index.js"
  },
  "dependencies": {
    "react": "^18.0.0",
    "express": "^4.18.0"
  }
}`
	abs, rel := writeTempFile(t, "package.json", src)
	e := NewConfigExtractor()
	r := e.Extract(abs, rel)

	if r.Evidence["package_name"] != "my-app" {
		t.Errorf("expected package_name 'my-app', got %q", r.Evidence["package_name"])
	}
	if len(r.BuildCommands) == 0 {
		t.Error("expected build commands from npm scripts")
	}
	if len(r.TestCommands) == 0 {
		t.Error("expected test commands from npm scripts")
	}
	found := false
	for _, ep := range r.EntryPoints {
		if ep == "src/index.js" || ep == "npm run start" {
			found = true
		}
	}
	if !found {
		t.Errorf("expected entry point, got %v", r.EntryPoints)
	}
}

func TestConfigPyprojectToml(t *testing.T) {
	src := `
[tool.poetry]
name = "rekipedia"
version = "0.7.3"

[build-system]
requires = ["poetry-core"]

[tool.pytest.ini_options]
testpaths = ["tests"]
`
	abs, rel := writeTempFile(t, "pyproject.toml", src)
	e := NewConfigExtractor()
	r := e.Extract(abs, rel)

	if r.Evidence["package_name"] != "rekipedia" {
		t.Errorf("expected package_name 'rekipedia', got %q", r.Evidence["package_name"])
	}
	if len(r.BuildCommands) == 0 {
		t.Error("expected build command for pyproject.toml with build-system")
	}
}

func TestConfigDockerfile(t *testing.T) {
	src := `FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN pip install -e .
EXPOSE 8000
CMD ["python", "-m", "rekipedia.server"]
`
	abs, rel := writeTempFile(t, "dockerfile", src)
	e := NewConfigExtractor()
	r := e.Extract(abs, rel)

	if r.Evidence["docker_base"] != "python:3.12-slim" {
		t.Errorf("expected docker_base 'python:3.12-slim', got %q", r.Evidence["docker_base"])
	}
	if r.Evidence["docker_port"] != "8000" {
		t.Errorf("expected docker_port '8000', got %q", r.Evidence["docker_port"])
	}
}

func TestConfigGoMod(t *testing.T) {
	src := `module github.com/unrealandychan/rekipedia

go 1.22

require (
    github.com/spf13/cobra v1.8.0
    github.com/mattn/go-sqlite3 v1.14.22
)
`
	abs, rel := writeTempFile(t, "go.mod", src)
	e := NewConfigExtractor()
	r := e.Extract(abs, rel)

	if r.Evidence["go_module"] != "github.com/unrealandychan/rekipedia" {
		t.Errorf("expected go_module, got %q", r.Evidence["go_module"])
	}
	if len(r.BuildCommands) == 0 {
		t.Error("expected build command go build ./...")
	}
	if len(r.TestCommands) == 0 {
		t.Error("expected test command go test ./...")
	}
}

func TestConfigMakefile(t *testing.T) {
	src := `
.PHONY: build test clean

build:
	go build ./...

test:
	go test ./... -v

clean:
	rm -rf dist/
`
	abs, rel := writeTempFile(t, "makefile", src)
	e := NewConfigExtractor()
	r := e.Extract(abs, rel)

	if len(r.BuildCommands) == 0 {
		t.Error("expected build command from Makefile")
	}
	if len(r.TestCommands) == 0 {
		t.Error("expected test command from Makefile")
	}
}

// ── Registry + MergeResults tests ─────────────────────────────────────────────

func TestRegistryExtractPython(t *testing.T) {
	reg := NewRegistry()
	src := "def hello(): pass\n"
	abs, rel := writeTempFile(t, "hello.py", src)
	r := reg.ExtractFile(abs, rel, ".py")
	if !hasSymbol(r.Symbols, "hello", models.SymbolFunction) {
		t.Error("expected function 'hello' via registry")
	}
}

func TestRegistryExtractTS(t *testing.T) {
	reg := NewRegistry()
	src := "export function add(a: number, b: number) { return a + b; }\n"
	abs, rel := writeTempFile(t, "math.ts", src)
	r := reg.ExtractFile(abs, rel, ".ts")
	if !hasSymbol(r.Symbols, "add", models.SymbolFunction) {
		t.Errorf("expected function 'add' via registry, got %v", symbolNames(r.Symbols))
	}
}

func TestRegistryUnknownExt(t *testing.T) {
	reg := NewRegistry()
	abs, rel := writeTempFile(t, "data.bin", "binary content")
	r := reg.ExtractFile(abs, rel, ".bin")
	if len(r.FilesSeen) != 1 || r.FilesSeen[0] != rel {
		t.Error("expected fallback result with FilesSeen set")
	}
}

func TestMergeResults(t *testing.T) {
	r1 := models.AnalysisResult{
		FilesSeen: []string{"a.py"},
		Symbols: []models.Symbol{
			{Name: "funcA", Kind: models.SymbolFunction, File: "a.py"},
		},
		BuildCommands: []string{"make build"},
		Evidence:      map[string]string{"k1": "v1"},
	}
	r2 := models.AnalysisResult{
		FilesSeen: []string{"b.ts"},
		Symbols: []models.Symbol{
			{Name: "classB", Kind: models.SymbolClass, File: "b.ts"},
		},
		TestCommands: []string{"npm test"},
		Evidence:     map[string]string{"k2": "v2"},
	}
	merged := MergeResults([]models.AnalysisResult{r1, r2})

	if len(merged.FilesSeen) != 2 {
		t.Errorf("expected 2 FilesSeen, got %d", len(merged.FilesSeen))
	}
	if len(merged.Symbols) != 2 {
		t.Errorf("expected 2 symbols, got %d", len(merged.Symbols))
	}
	if merged.Evidence["k1"] != "v1" || merged.Evidence["k2"] != "v2" {
		t.Error("evidence merge failed")
	}
	if len(merged.BuildCommands) != 1 {
		t.Errorf("expected 1 build command, got %d", len(merged.BuildCommands))
	}
	if len(merged.TestCommands) != 1 {
		t.Errorf("expected 1 test command, got %d", len(merged.TestCommands))
	}
}

func TestCanHandleByName(t *testing.T) {
	cases := []struct {
		path     string
		expected bool
	}{
		{"package.json", true},
		{"pyproject.toml", true},
		{"dockerfile", true},
		{"makefile", true},
		{"go.mod", true},
		{".github/workflows/ci.yml", true},
		{".gitlab-ci.yml", true},
		{"src/app.py", false},
		{"README.md", false},
	}
	for _, tc := range cases {
		got := CanHandleByName(tc.path)
		if got != tc.expected {
			t.Errorf("CanHandleByName(%q) = %v, want %v", tc.path, got, tc.expected)
		}
	}
}
