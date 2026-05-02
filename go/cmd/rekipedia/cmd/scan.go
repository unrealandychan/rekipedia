package cmd

import (
	"os"
	"strings"

	"github.com/pterm/pterm"
	"github.com/spf13/cobra"

	"github.com/unrealandychan/rekipedia/internal/config"
	"github.com/unrealandychan/rekipedia/internal/models"
	"github.com/unrealandychan/rekipedia/internal/orchestrator"
	"github.com/unrealandychan/rekipedia/internal/rag"
)

var scanFlags struct {
	model         string
	apiKey        string
	baseURL       string
	outputDir     string
	verbose       bool
	embedModel    string
	embedProvider string
	languages     string
}

var scanCmd = &cobra.Command{
	Use:   "scan [repo-path]",
	Short: "Full scan: extract, plan, and generate wiki pages",
	Long: `Performs a full scan of the repository:
  1. Walk files and extract symbols/relationships
  2. Run PlannerAgent to design wiki structure
  3. Build wiki pages concurrently via LLM
  4. Save results to .rekipedia/store.db and .rekipedia/wiki/`,
	Args: cobra.MaximumNArgs(1),
	RunE: func(cmd *cobra.Command, args []string) error {
		root := "."
		if len(args) > 0 {
			root = args[0]
		}

		outDir := outputDir
		if scanFlags.outputDir != "" {
			outDir = scanFlags.outputDir
		}
		if err := os.MkdirAll(outDir, 0o755); err != nil {
			return err
		}

		pterm.DefaultHeader.WithFullWidth(false).WithBackgroundStyle(pterm.NewStyle(pterm.BgDarkGray)).WithTextStyle(pterm.NewStyle(pterm.FgWhite)).Println("rekipedia scan ▸ " + root)

		cfg := loadLLMConfig(scanFlags.model, scanFlags.apiKey, scanFlags.baseURL)

	var progress func(string) // nil — terminal output handled by pterm in orchestrator

		if err := orchestrator.RunDigest(cmd.Context(), root, outDir, orchestrator.DigestOptions{
			LLMConfig: cfg,
			Verbose:   scanFlags.verbose,
			Progress:  progress,
			Languages: splitLanguages(scanFlags.languages),
		}); err != nil {
			return err
		}

		// Auto-embed: flag overrides config; config.EmbedModel enables embed by default.
		if scanFlags.embedModel != "" {
			cfg.EmbedModel = scanFlags.embedModel
		}
		if scanFlags.embedProvider != "" {
			cfg.EmbedProvider = scanFlags.embedProvider
		}
		if cfg.EmbedModel != "" {
			pterm.Info.Println("Auto-embedding after scan...")
			pipeline := rag.NewEmbedPipeline(outDir, cfg)
			n, err := pipeline.Build(root, nil)
			if err != nil {
				pterm.Warning.Printfln("Auto-embed failed: %v", err)
			} else {
				pterm.Success.Printf("Embeddings ready (%d chunks)\n", n)
			}
		}

		return nil
	},
}

func init() {
	scanCmd.Flags().StringVar(&scanFlags.model, "model", "", "LLM model override")
	scanCmd.Flags().StringVar(&scanFlags.apiKey, "api-key", "", "API key override")
	scanCmd.Flags().StringVar(&scanFlags.baseURL, "base-url", "", "LLM base URL override")
	scanCmd.Flags().StringVar(&scanFlags.outputDir, "output-dir", "", "Output directory (default: .rekipedia)")
	scanCmd.Flags().BoolVarP(&scanFlags.verbose, "verbose", "v", false, "Verbose output")
	scanCmd.Flags().StringVar(&scanFlags.embedModel, "embed-model", "", "Embedding model")
	scanCmd.Flags().StringVar(&scanFlags.embedProvider, "embed-provider", "", "Embedding provider")
	scanCmd.Flags().StringVarP(&scanFlags.languages, "languages", "l", "", "Comma-separated languages to include, e.g. python,typescript,go (default: all)")
}

// loadLLMConfig merges flags with config file defaults.
func loadLLMConfig(model, apiKey, baseURL string) models.LLMConfig {
	cfg, err := config.Load("")
	var llmCfg models.LLMConfig
	if err == nil {
		llmCfg = cfg.LLM
	} else {
		llmCfg = models.DefaultLLMConfig()
	}
	if model != "" {
		llmCfg.Model = model
	}
	if apiKey != "" {
		llmCfg.APIKey = apiKey
	}
	if baseURL != "" {
		llmCfg.BaseURL = baseURL
	}
	return llmCfg
}

// splitLanguages parses a comma-separated language string into a slice.
// Returns nil (= all languages) if the input is empty.
func splitLanguages(s string) []string {
	if s == "" {
		return nil
	}
	parts := strings.Split(s, ",")
	out := make([]string, 0, len(parts))
	for _, p := range parts {
		if t := strings.TrimSpace(strings.ToLower(p)); t != "" {
			out = append(out, t)
		}
	}
	if len(out) == 0 {
		return nil
	}
	return out
}
