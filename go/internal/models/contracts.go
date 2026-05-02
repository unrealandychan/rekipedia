// Package models defines shared data contracts for rekipedia.
// These mirror the Python pydantic models in src/rekipedia/models/contracts.py.
package models

// LLMConfig holds LLM provider settings.
type LLMConfig struct {
	Model         string  `yaml:"model"          json:"model"`
	APIKey        string  `yaml:"api_key"        json:"api_key"`
	BaseURL       string  `yaml:"base_url"       json:"base_url"`
	Temperature   float64 `yaml:"temperature"    json:"temperature"`
	EmbedModel    string  `yaml:"embed_model"    json:"embed_model"`
	EmbedProvider string  `yaml:"embed_provider" json:"embed_provider"`
	EmbedAPIKey   string  `yaml:"embed_api_key"  json:"embed_api_key"`
	EmbedBaseURL  string  `yaml:"embed_base_url" json:"embed_base_url"`
}

// DefaultLLMConfig returns sensible defaults (Ollama local).
func DefaultLLMConfig() LLMConfig {
	return LLMConfig{
		Model:       "ollama/llama4",
		Temperature: 0.2,
	}
}

// SymbolKind enumerates the kinds of code symbols.
type SymbolKind string

const (
	SymbolFunction  SymbolKind = "function"
	SymbolClass     SymbolKind = "class"
	SymbolType      SymbolKind = "type"
	SymbolVariable  SymbolKind = "variable"
	SymbolInterface SymbolKind = "interface"
	SymbolEnum      SymbolKind = "enum"
	SymbolModule    SymbolKind = "module"
	SymbolOther     SymbolKind = "other"
	SymbolMethod    SymbolKind = "method"
	SymbolConstant  SymbolKind = "constant"
)

// RelKind enumerates the kinds of relationships between symbols.
type RelKind string

const (
	RelImport    RelKind = "import"
	RelCall      RelKind = "call"
	RelInherits  RelKind = "inherits"
	RelUses      RelKind = "uses"
	RelReExports RelKind = "re-exports"
)

// Symbol represents a named code entity.
type Symbol struct {
	Name      string     `json:"name"`
	Kind      SymbolKind `json:"kind"`
	File      string     `json:"file"`
	LineStart int        `json:"line_start,omitempty"`
	LineEnd   int        `json:"line_end,omitempty"`
	Signature string     `json:"signature,omitempty"`
	Docstring string     `json:"docstring,omitempty"`
}

// Relationship represents a directed dependency between two symbols/modules.
type Relationship struct {
	From string  `json:"from"`
	To   string  `json:"to"`
	Kind RelKind `json:"kind"`
	File string  `json:"file,omitempty"`
}

// AnalysisResult is the output of extracting a repo shard.
type AnalysisResult struct {
	ShardID       string            `json:"shard_id"`
	FilesSeen     []string          `json:"files_seen"`
	EntryPoints   []string          `json:"entry_points"`
	Symbols       []Symbol          `json:"symbols"`
	Relationships []Relationship    `json:"relationships"`
	BuildCommands []string          `json:"build_commands"`
	TestCommands  []string          `json:"test_commands"`
	Risks         []string          `json:"risks"`
	Unknowns      []string          `json:"unknowns"`
	Evidence      map[string]string `json:"evidence"`
}

// Shard is a slice of files assigned to one extraction worker.
type Shard struct {
	ShardID string         `json:"shard_id"`
	Root    string         `json:"root"`
	Files   []FileManifest `json:"files"`
}

// QAHistory records a previous question-answer pair for multi-turn context.
type QAHistory struct {
	Question  string `json:"question"`
	Answer    string `json:"answer"`
	CreatedAt string `json:"created_at,omitempty"`
}

// FileManifest records a file's identity for incremental updates.
type FileManifest struct {
	Path      string `json:"path"`
	SHA256    string `json:"sha256"`
	SizeBytes int64  `json:"size_bytes"`
	Language  string `json:"language,omitempty"`
}

// WikiPageSpec is the LLM planner's instruction for a single wiki page.
type WikiPageSpec struct {
	Slug         string   `json:"slug"`
	Title        string   `json:"title"`
	Section      string   `json:"section"`
	Priority     int      `json:"priority"`
	Importance   int      `json:"importance"`
	Focus        string   `json:"focus"`
	RequiredData []string `json:"required_data"`
	Tags         []string `json:"tags"`
}

// WikiSection groups pages in the sidebar.
type WikiSection struct {
	ID    string   `json:"id"`
	Title string   `json:"title"`
	Pages []string `json:"pages"`
}

// WikiPlan is the full output of PlannerAgent.
type WikiPlan struct {
	Sections  []WikiSection  `json:"sections"`
	Pages     []WikiPageSpec `json:"pages"`
	NavOrder  []string       `json:"nav_order"`
	IndexSlug string         `json:"index_slug"`
}

// ScanMeta records metadata about the last scan run.
type ScanMeta struct {
	Model             string `json:"model"`
	Timestamp         string `json:"timestamp"`
	RekipediaVersion  string `json:"rekipedia_version"`
	FileCount         int    `json:"file_count"`
	ImplFileCount     int    `json:"impl_file_count"`
	TestFileCount     int    `json:"test_file_count"`
	ConfigFileCount   int    `json:"config_file_count"`
	Embedded          bool   `json:"embedded"`
}
