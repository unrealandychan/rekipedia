package extractor

import (
	"encoding/json"
	"os"
	"regexp"
	"strings"

	"github.com/unrealandychan/rekipedia/internal/models"
)

// ConfigExtractor parses package.json, pyproject.toml, Makefile, Dockerfile, CI yml.
// Mirrors Python's config_extractor.py.

var (
	reCIPath = regexp.MustCompile(`\.github/workflows/.*\.ya?ml$|\.gitlab-ci\.ya?ml$|Jenkinsfile|\.circleci/config\.ya?ml$`)
	reMakeTarget = regexp.MustCompile(`^([a-zA-Z_-]+)\s*:`)
	reDockerFrom = regexp.MustCompile(`(?i)^FROM\s+(\S+)`)
	reDockerExpose = regexp.MustCompile(`(?i)^EXPOSE\s+(\d+)`)
	reGoMod = regexp.MustCompile(`^module\s+(\S+)`)
	reGoRequire = regexp.MustCompile(`^\s+(\S+)\s+v`)
)

var configFileNames = map[string]bool{
	"package.json":        true,
	"pyproject.toml":      true,
	"dockerfile":          true,
	"docker-compose.yml":  true,
	"docker-compose.yaml": true,
	".env.sample":         true,
	".env.example":        true,
	"makefile":            true,
	"go.mod":              true,
	"cargo.toml":          true,
	"build.gradle":        true,
	"pom.xml":             true,
}

// ConfigExtractor handles build/config/CI files.
type ConfigExtractor struct{}

// NewConfigExtractor returns a new ConfigExtractor.
func NewConfigExtractor() *ConfigExtractor { return &ConfigExtractor{} }

// CanHandle returns true for known config file names.
func (e *ConfigExtractor) CanHandle(ext string) bool {
	// Config extractor is matched by filename, not extension.
	// The Registry.ExtractFile passes the ext, so we also match common config exts.
	switch strings.ToLower(ext) {
	case ".toml", ".json", ".yaml", ".yml", ".mod":
		return true
	}
	return false
}

// CanHandleByName returns true when matched by filename (used by orchestrator).
func CanHandleByName(relPath string) bool {
	name := strings.ToLower(relPath)
	// Check exact filename at any depth
	parts := strings.Split(name, "/")
	base := parts[len(parts)-1]
	if configFileNames[base] {
		return true
	}
	return reCIPath.MatchString(name)
}

// Extract parses a config/build file.
func (e *ConfigExtractor) Extract(absPath, relPath string) models.AnalysisResult {
	result := models.AnalysisResult{
		ShardID:   relPath,
		FilesSeen: []string{relPath},
		Evidence:  make(map[string]string),
	}
	data, err := os.ReadFile(absPath)
	if err != nil {
		return result
	}
	text := string(data)
	name := strings.ToLower(relPath)
	parts := strings.Split(name, "/")
	base := parts[len(parts)-1]

	switch base {
	case "package.json":
		parsePackageJSON(text, &result)
	case "pyproject.toml":
		parsePyprojectToml(text, &result)
	case "dockerfile":
		parseDockerfile(text, &result)
	case "makefile":
		parseMakefile(text, &result)
	case "go.mod":
		parseGoMod(text, &result)
	default:
		if reCIPath.MatchString(name) {
			parseCIYaml(text, &result)
		}
	}

	return result
}

// ── package.json ─────────────────────────────────────────────────────────────

type packageJSON struct {
	Name    string            `json:"name"`
	Main    string            `json:"main"`
	Scripts map[string]string `json:"scripts"`
	Deps    map[string]string `json:"dependencies"`
	DevDeps map[string]string `json:"devDependencies"`
}

func parsePackageJSON(text string, r *models.AnalysisResult) {
	var pkg packageJSON
	if err := json.Unmarshal([]byte(text), &pkg); err != nil {
		return
	}
	if pkg.Name != "" {
		r.Evidence["package_name"] = pkg.Name
	}
	if pkg.Main != "" {
		r.EntryPoints = append(r.EntryPoints, pkg.Main)
	}
	for script, cmd := range pkg.Scripts {
		switch {
		case strings.Contains(script, "build") || script == "compile":
			r.BuildCommands = append(r.BuildCommands, "npm run "+script+" ("+cmd+")")
		case strings.Contains(script, "test") || script == "spec":
			r.TestCommands = append(r.TestCommands, "npm run "+script+" ("+cmd+")")
		case script == "start" || script == "dev":
			r.EntryPoints = append(r.EntryPoints, "npm run "+script)
		}
	}
	// Key deps as evidence
	keyDeps := []string{"react", "next", "express", "fastify", "vue", "angular", "svelte", "nestjs"}
	for _, dep := range keyDeps {
		if v, ok := pkg.Deps[dep]; ok {
			r.Evidence["dep_"+dep] = v
		}
	}
}

// ── pyproject.toml ────────────────────────────────────────────────────────────

func parsePyprojectToml(text string, r *models.AnalysisResult) {
	lines := strings.Split(text, "\n")
	inScripts := false
	for _, line := range lines {
		trimmed := strings.TrimSpace(line)
		if trimmed == "[tool.poetry.scripts]" || trimmed == "[project.scripts]" {
			inScripts = true
			continue
		}
		if strings.HasPrefix(trimmed, "[") {
			inScripts = false
		}
		if inScripts && strings.Contains(trimmed, "=") {
			r.EntryPoints = append(r.EntryPoints, strings.TrimSpace(strings.Split(trimmed, "=")[0]))
		}
		if strings.Contains(trimmed, "pytest") || strings.Contains(trimmed, "unittest") {
			r.TestCommands = append(r.TestCommands, "pytest")
		}
		if strings.HasPrefix(trimmed, "name =") || strings.HasPrefix(trimmed, "name=") {
			parts := strings.SplitN(trimmed, "=", 2)
			if len(parts) == 2 {
				r.Evidence["package_name"] = strings.Trim(strings.TrimSpace(parts[1]), `"'`)
			}
		}
	}
	// Build command
	if strings.Contains(text, "[build-system]") {
		r.BuildCommands = append(r.BuildCommands, "pip install -e .")
	}
}

// ── Dockerfile ────────────────────────────────────────────────────────────────

func parseDockerfile(text string, r *models.AnalysisResult) {
	for _, line := range strings.Split(text, "\n") {
		line = strings.TrimSpace(line)
		if m := reDockerFrom.FindStringSubmatch(line); m != nil {
			r.Evidence["docker_base"] = m[1]
		}
		if m := reDockerExpose.FindStringSubmatch(line); m != nil {
			r.Evidence["docker_port"] = m[1]
		}
		if strings.HasPrefix(strings.ToUpper(line), "RUN ") {
			cmd := strings.TrimPrefix(strings.TrimPrefix(line, "RUN "), "run ")
			if strings.Contains(cmd, "install") || strings.Contains(cmd, "build") {
				r.BuildCommands = append(r.BuildCommands, "docker: "+cmd)
			}
		}
		if strings.HasPrefix(strings.ToUpper(line), "CMD ") || strings.HasPrefix(strings.ToUpper(line), "ENTRYPOINT ") {
			r.EntryPoints = append(r.EntryPoints, line)
		}
	}
}

// ── Makefile ──────────────────────────────────────────────────────────────────

func parseMakefile(text string, r *models.AnalysisResult) {
	for _, line := range strings.Split(text, "\n") {
		if m := reMakeTarget.FindStringSubmatch(line); m != nil {
			target := m[1]
			switch {
			case target == "build" || target == "compile" || target == "all":
				r.BuildCommands = append(r.BuildCommands, "make "+target)
			case strings.Contains(target, "test") || target == "check":
				r.TestCommands = append(r.TestCommands, "make "+target)
			}
		}
	}
}

// ── go.mod ────────────────────────────────────────────────────────────────────

func parseGoMod(text string, r *models.AnalysisResult) {
	for _, line := range strings.Split(text, "\n") {
		if m := reGoMod.FindStringSubmatch(line); m != nil {
			r.Evidence["go_module"] = m[1]
		}
	}
	r.BuildCommands = append(r.BuildCommands, "go build ./...")
	r.TestCommands = append(r.TestCommands, "go test ./...")
}

// ── CI YAML ───────────────────────────────────────────────────────────────────

func parseCIYaml(text string, r *models.AnalysisResult) {
	for _, line := range strings.Split(text, "\n") {
		trimmed := strings.TrimSpace(line)
		if strings.HasPrefix(trimmed, "run: ") {
			cmd := strings.TrimPrefix(trimmed, "run: ")
			if strings.Contains(cmd, "test") || strings.Contains(cmd, "pytest") {
				r.TestCommands = append(r.TestCommands, "ci: "+cmd)
			} else if strings.Contains(cmd, "build") {
				r.BuildCommands = append(r.BuildCommands, "ci: "+cmd)
			}
		}
	}
	r.Evidence["has_ci"] = "true"
}
