// Package cmd wires up the close-wiki CLI using cobra.
package cmd

import (
	"fmt"
	"os"
	"path/filepath"

	"github.com/spf13/cobra"
)

// Version is injected at build time via -ldflags.
var (
	version = "0.8.3"
	commit  = "none"
	date    = "unknown"
)

// outputDir is the persistent output directory flag (default: .close-wiki).
var outputDir string

var rootCmd = &cobra.Command{
	Use:   "close-wiki",
	Short: "Your AI tech lead — always available, always up to date.",
	Long: `close-wiki scans any codebase and generates a navigable knowledge store:
wiki pages, symbols, relationships, and a Q&A interface.

Usage: close-wiki <command> [flags]`,
	Version: fmt.Sprintf("%s (commit %s, built %s)", version, commit, date),
}

// Execute runs the root command.
func Execute() {
	if err := rootCmd.Execute(); err != nil {
		os.Exit(1)
	}
}

func init() {
	cwd, _ := os.Getwd()
	defaultOutput := filepath.Join(cwd, ".close-wiki")
	rootCmd.PersistentFlags().StringVarP(&outputDir, "output", "o", defaultOutput, "Output directory")

	rootCmd.AddCommand(
		initCmd,
		scanCmd,
		updateCmd,
		askCmd,
		serveCmd,
		embedCmd,
		exportCmd,
	)
}
