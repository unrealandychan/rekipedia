// Package cmd wires up the rekipedia CLI using cobra.
package cmd

import (
	"fmt"
	"os"
	"path/filepath"

	"github.com/pterm/pterm"
	"github.com/spf13/cobra"
)

// Version is injected at build time via -ldflags.
var (
	version = "dev"
	commit  = "none"
	date    = "unknown"
)

// outputDir is the persistent output directory flag (default: .rekipedia).
var outputDir string

var rootCmd = &cobra.Command{
	Use:   "rekipedia",
	Short: "Your AI tech lead — always available, always up to date.",
	Long: `rekipedia scans any codebase and generates a navigable knowledge store:
wiki pages, symbols, relationships, and a Q&A interface.

Usage: rekipedia <command> [flags]`,
	Version: fmt.Sprintf("%s (commit %s, built %s)", version, commit, date),
	PersistentPreRun: func(cmd *cobra.Command, args []string) {
		// Banner is printed per-command for serve; root shows it on bare invocation
	},
}

func printRootBanner() {
	fmt.Fprintln(os.Stderr, ansiLogo)
	fmt.Fprintln(os.Stderr)
	pterm.FgLightCyan.Println("  Agentic repo-to-wiki: scan any repository into a portable knowledge store.")
	fmt.Fprintln(os.Stderr)
}

// Execute runs the root command.
func Execute() {
	if err := rootCmd.Execute(); err != nil {
		os.Exit(1)
	}
}

func init() {
	cwd, _ := os.Getwd()
	defaultOutput := filepath.Join(cwd, ".rekipedia")
	rootCmd.PersistentFlags().StringVarP(&outputDir, "output", "o", defaultOutput, "Output directory")

	// Show ANSI banner before help output
	rootCmd.SetHelpFunc(func(cmd *cobra.Command, args []string) {
		printRootBanner()
		cmd.Usage() //nolint:errcheck
	})

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
