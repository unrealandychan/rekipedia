package cmd

import (
	"os"
	"path/filepath"

	"github.com/pterm/pterm"
	"github.com/spf13/cobra"
	"github.com/unrealandychan/rekipedia/internal/config"
)

var initCmd = &cobra.Command{
	Use:   "init [repo-path]",
	Short: "Initialise .rekipedia/ in a repository",
	Long:  `Creates .rekipedia/config.yml with defaults. Safe to re-run (idempotent).`,
	Args:  cobra.MaximumNArgs(1),
	RunE: func(cmd *cobra.Command, args []string) error {
		root := "."
		if len(args) > 0 {
			root = args[0]
		}

		// Check if already initialised before calling InitDir
		cfgPath := filepath.Join(root, ".rekipedia", "config.yml")
		_, statErr := os.Stat(cfgPath)
		alreadyExists := statErr == nil

		if err := config.InitDir(root); err != nil {
			return err
		}

		if alreadyExists {
			pterm.Warning.Println("Already initialised — skipping")
			return nil
		}

		pterm.Success.Printfln("Initialised .rekipedia/ in %s", root)

		boxContent := ".rekipedia/config.yml  ✓\n.gitignore updated      ✓"
		pterm.DefaultBox.Println(boxContent)
		pterm.Info.Println("Next: run `rekipedia scan .`")

		return nil
	},
}
