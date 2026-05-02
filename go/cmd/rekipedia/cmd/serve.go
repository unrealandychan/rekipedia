package cmd

import (
	"context"
	"fmt"
	"os"

	"github.com/pterm/pterm"
	"github.com/spf13/cobra"

	"github.com/unrealandychan/rekipedia/internal/server"
)

var serveFlags struct {
	port      int
	noBrowser bool
	model     string
	host      string
	outputDir string
}

const ansiLogo = "\033[36m" + `  ██████╗ ███████╗██╗  ██╗██╗██████╗ ███████╗██████╗ ██╗ █████╗ 
  ██╔══██╗██╔════╝██║ ██╔╝██║██╔══██╗██╔════╝██╔══██╗██║██╔══██╗
  ██████╔╝█████╗  █████╔╝ ██║██████╔╝█████╗  ██║  ██║██║███████║
  ██╔══██╗██╔══╝  ██╔═██╗ ██║██╔═══╝ ██╔══╝  ██║  ██║██║██╔══██║
  ██║  ██║███████╗██║  ██╗██║██║     ███████╗██████╔╝██║██║  ██║
  ╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚═╝╚═╝     ╚══════╝╚═════╝ ╚═╝╚═╝  ╚═╝` + "\033[0m"

func printServeBanner(addr, root, outDir, model string) {
	fmt.Fprintln(os.Stderr)
	fmt.Fprintln(os.Stderr, ansiLogo)
	fmt.Fprintln(os.Stderr)

	browserStr := "auto-open"
	if serveFlags.noBrowser {
		browserStr = "disabled"
	}

	pterm.DefaultBox.WithTitle("").
		WithRightPadding(2).
		WithLeftPadding(2).
		Println(
			pterm.Sprintf("%-10s %-22s %-10s %s\n", "Version", version, "Serving", "http://"+addr) +
				pterm.Sprintf("%-10s %-22s %-10s %s\n", "Repo", root, "Model", model) +
				pterm.Sprintf("%-10s %-22s %-10s %s", "Output", outDir, "Browser", browserStr),
		)

	fmt.Fprintln(os.Stderr)
	pterm.FgGreen.Println("  Ready — press Ctrl+C to stop")
	fmt.Fprintln(os.Stderr)
}

var serveCmd = &cobra.Command{
	Use:   "serve [repo-path]",
	Short: "Start the rekipedia web UI",
	Args:  cobra.MaximumNArgs(1),
	RunE: func(cmd *cobra.Command, args []string) error {
		root := "."
		if len(args) > 0 {
			root = args[0]
		}
		cfg := loadLLMConfig(serveFlags.model, "", "")
		host := serveFlags.host
		if host == "" {
			host = "127.0.0.1"
		}
		addr := fmt.Sprintf("%s:%d", host, serveFlags.port)
		outDir := serveFlags.outputDir
		if outDir == "" {
			outDir = ".rekipedia"
		}
		printServeBanner(addr, root, outDir, cfg.Model)
		srv := server.New(root, outDir, addr, cfg)
		return srv.Start(context.Background())
	},
}

func init() {
	serveCmd.Flags().IntVar(&serveFlags.port, "port", 7070, "HTTP port")
	serveCmd.Flags().StringVar(&serveFlags.host, "host", "", "Bind host (default: 127.0.0.1)")
	serveCmd.Flags().StringVar(&serveFlags.outputDir, "output-dir", "", "Output directory (default: .rekipedia)")
	serveCmd.Flags().BoolVar(&serveFlags.noBrowser, "no-browser", false, "Don't open browser")
	serveCmd.Flags().StringVar(&serveFlags.model, "model", "", "LLM model")
}
