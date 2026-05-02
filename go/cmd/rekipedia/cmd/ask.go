package cmd

import (
	"bufio"
	"context"
	"fmt"
	"os"
	"os/signal"
	"strings"
	"syscall"

	"github.com/pterm/pterm"
	"github.com/spf13/cobra"

	"github.com/unrealandychan/rekipedia/internal/models"
	"github.com/unrealandychan/rekipedia/internal/orchestrator"
)

var askFlags struct {
	repo        string
	model       string
	query       string
	stream      bool
	outputDir   string
	interactive bool
}

var askCmd = &cobra.Command{
	Use:   "ask",
	Short: "Ask a question about the scanned repository",
	Long: `Stream an answer from the LLM using wiki pages + RAG context.
Use -q for single-shot (non-interactive) mode.
Use -i (or omit question) for interactive chat REPL.`,
	Args: cobra.MaximumNArgs(1),
	RunE: func(cmd *cobra.Command, args []string) error {
		outDir := askFlags.outputDir
		if outDir == "" {
			outDir = ".rekipedia"
		}

		cfg := loadLLMConfig(askFlags.model, "", "")
		opts := orchestrator.AskOptions{LLMConfig: cfg}

		// Determine mode
		question := askFlags.query
		if question == "" && len(args) > 0 {
			question = args[0]
		}

		// Enter interactive mode if -i flag set OR no question provided
		if askFlags.interactive || question == "" {
			return runInteractiveAsk(cmd.Context(), askFlags.repo, outDir, opts)
		}

		// Single-shot mode
		pterm.DefaultSection.WithLevel(2).Printf("rekipedia ask ▸ %s", askFlags.repo)

		if askFlags.stream {
			return orchestrator.StreamAsk(cmd.Context(), question, askFlags.repo, outDir, opts, func(chunk string) {
				fmt.Print(chunk)
			})
		}

		spinner, _ := pterm.DefaultSpinner.WithText("Thinking…").Start()
		result, err := orchestrator.RunAsk(cmd.Context(), question, askFlags.repo, outDir, opts)
		if err != nil {
			spinner.Fail("Failed")
			return err
		}
		spinner.Success("Done")
		fmt.Println()
		pterm.DefaultParagraph.Println(result.Answer)
		return nil
	},
}

func init() {
	askCmd.Flags().StringVar(&askFlags.repo, "repo", ".", "Repo path")
	askCmd.Flags().StringVar(&askFlags.outputDir, "output-dir", "", "Output directory (default: .rekipedia)")
	askCmd.Flags().StringVar(&askFlags.model, "model", "", "LLM model override")
	askCmd.Flags().StringVarP(&askFlags.query, "query", "q", "", "Single-shot question")
	askCmd.Flags().BoolVar(&askFlags.stream, "stream", false, "Stream the response")
	askCmd.Flags().BoolVarP(&askFlags.interactive, "interactive", "i", false, "Interactive chat REPL mode")
}

// runInteractiveAsk runs an interactive multi-turn Q&A REPL.
func runInteractiveAsk(ctx context.Context, repoRoot, outputDir string, opts orchestrator.AskOptions) error {
	// Handle Ctrl+C gracefully
	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, os.Interrupt, syscall.SIGTERM)
	ctx, cancel := context.WithCancel(ctx)
	defer cancel()
	go func() {
		<-sigCh
		fmt.Println()
		pterm.Info.Println("Bye!")
		cancel()
		os.Exit(0)
	}()

	// Welcome box
	pterm.DefaultBox.WithTitle("rekipedia ask").Println(
		pterm.LightCyan("Repo: ") + repoRoot + "\n" +
			pterm.LightWhite("Type your question. /quit to exit, /clear to reset history, /help for commands."),
	)
	fmt.Println()

	var history []models.QAHistory
	reader := bufio.NewReader(os.Stdin)

	for {
		// Prompt
		pterm.Print(pterm.LightCyan("You ▸ "))

		line, err := reader.ReadString('\n')
		if err != nil {
			// EOF (e.g. piped input ended)
			fmt.Println()
			pterm.Info.Println("Bye!")
			return nil
		}

		line = strings.TrimSpace(line)
		if line == "" {
			continue
		}

		// Handle slash commands
		switch strings.ToLower(line) {
		case "/quit", "/exit":
			pterm.Info.Println("Bye!")
			return nil
		case "/clear":
			history = nil
			pterm.Success.Println("History cleared.")
			fmt.Println()
			continue
		case "/help":
			pterm.DefaultBox.WithTitle("Commands").Println(
				"/quit, /exit  — exit the chat\n" +
					"/clear        — clear conversation history\n" +
					"/help         — show this help",
			)
			fmt.Println()
			continue
		}

		// Ask question
		spinner, _ := pterm.DefaultSpinner.WithText("Thinking…").Start()
		askOpts := opts
		askOpts.History = history

		result, err := orchestrator.RunAsk(ctx, line, repoRoot, outputDir, askOpts)
		if err != nil {
			spinner.Fail("Error: " + err.Error())
			fmt.Println()
			continue
		}
		spinner.Success("Done")

		// Print answer
		fmt.Println()
		fmt.Print(pterm.LightGreen("Assistant ▸ "))
		fmt.Println()
		pterm.DefaultParagraph.Println(result.Answer)
		fmt.Println()

		// Append to history
		history = append(history, models.QAHistory{
			Question: line,
			Answer:   result.Answer,
		})
	}
}
