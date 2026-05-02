package cmd

import (
	"os"

	"github.com/pterm/pterm"
	"github.com/spf13/cobra"

	"github.com/unrealandychan/rekipedia/internal/orchestrator"
)

var updateFlags struct {
	model     string
	verbose   bool
	languages string
	outputDir string
	noDocker  bool
}

var updateCmd = &cobra.Command{
	Use:   "update [repo-path]",
	Short: "Incremental update: re-scan changed files only",
	Args:  cobra.MaximumNArgs(1),
	RunE: func(cmd *cobra.Command, args []string) error {
		root := "."
		if len(args) > 0 {
			root = args[0]
		}
		outDir := outputDir
		if updateFlags.outputDir != "" {
			outDir = updateFlags.outputDir
		}
		if err := os.MkdirAll(outDir, 0o755); err != nil {
			return err
		}
		pterm.DefaultHeader.WithFullWidth(false).WithBackgroundStyle(pterm.NewStyle(pterm.BgDarkGray)).WithTextStyle(pterm.NewStyle(pterm.FgWhite)).Println("rekipedia update ▸ " + root)
		cfg := loadLLMConfig(updateFlags.model, "", "")
		var progress func(string) // nil — terminal output handled by pterm in orchestrator
		return orchestrator.RunUpdate(cmd.Context(), root, outDir, orchestrator.UpdateOptions{
			LLMConfig: cfg,
			Progress:  progress,
			Languages: splitLanguages(updateFlags.languages),
		})
	},
}

func init() {
	updateCmd.Flags().StringVar(&updateFlags.model, "model", "", "LLM model override")
	updateCmd.Flags().BoolVarP(&updateFlags.verbose, "verbose", "v", false, "Verbose output")
	updateCmd.Flags().StringVarP(&updateFlags.languages, "languages", "l", "", "Comma-separated languages to include, e.g. python,typescript,go (default: all)")
	updateCmd.Flags().StringVar(&updateFlags.outputDir, "output-dir", "", "Output directory (default: .rekipedia)")
	updateCmd.Flags().BoolVar(&updateFlags.noDocker, "no-docker", false, "Skip Docker, run extractors in-process")
}
