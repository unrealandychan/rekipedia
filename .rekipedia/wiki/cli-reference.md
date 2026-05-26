---
slug: cli-reference
title: "Rekipedia CLI Reference"
section: api-reference
tags: [reference, api, cli]
pin: false
importance: 82
created_at: 2026-05-26T09:14:22Z
rekipedia_version: 0.17.25
---

# Rekipedia CLI Reference

## Overview

Rekipedia exposes a single Go-based command-line application entry point through [`main`](go/cmd/rekipedia/main.go#L6), which delegates to the Cobra root command via [`Execute`](go/cmd/rekipedia/cmd/root.go#L44). The CLI surface is organized into command families that support scanning repositories, generating wiki content, interacting with the RAG-backed assistant, and maintaining local workflow state such as git hooks and watch mode configuration.

This page documents the **user-facing** CLI surface only. It intentionally avoids deep architectural internals and implementation algorithms, and it excludes tests and CI-only helpers. Where behavior is visible from the command implementations, that behavior is summarized here with practical usage examples.

### Command families covered

- Root command and global flags
- Repository analysis / documentation workflow
- Interactive assistant and search-oriented commands
- Git and workflow commands
- Watch configuration commands

> **Sources:** `go/cmd/rekipedia/main.go` · L6–L8 · [`main`](go/cmd/rekipedia/main.go#L6) · `go/cmd/rekipedia/cmd/root.go` · L36–L78 · [`Execute`](go/cmd/rekipedia/cmd/root.go#L44)

---

## Command Summary

The table below summarizes the public commands visible in the runtime CLI. “Primary Symbols” lists the implementation symbols that are part of the executable command path; these are the symbols most relevant when reading the code for a specific subcommand.

| Command | Purpose | Key Flags | Output | Primary Symbols |
|---|---|---|---|---|
| `rekipedia` | Root entry point; prints banner/version info and dispatches subcommands | Global flags such as version handling are initialized at the root | Banner / command execution / help | [`Execute`](go/cmd/rekipedia/cmd/root.go#L44), [`printRootBanner`](go/cmd/rekipedia/cmd/root.go#L36) |
| `rekipedia ask` | Interactive repository Q&A | Interactive prompts; runtime options are assembled by the command | Console conversation, streamed answers when requested | [`runInteractiveAsk`](go/cmd/rekipedia/cmd/ask.go#L87) |
| `rekipedia diff` | Show changes in terms of symbols and file context | Diff-oriented flags configured in the command family | Markdown or text diff summary | [`runGit`](go/cmd/rekipedia/cmd/diff.go#L119), [`loadSymbolsJSON`](go/cmd/rekipedia/cmd/diff.go#L126), [`formatDiffMd`](go/cmd/rekipedia/cmd/diff.go#L175), [`formatDiffText`](go/cmd/rekipedia/cmd/diff.go#L216) |
| `rekipedia refactor` | Produce a static refactor report from repository content | Refactor filters and output-related flags are defined by the command | Refactor report / structured output | [`buildStaticReport`](go/cmd/rekipedia/cmd/refactor.go#L148) |
| `rekipedia search` | Token-based symbol search support | Search query arguments | Ranked search results | [`tokenizeSymbol`](go/cmd/rekipedia/cmd/search.go#L20) |
| `rekipedia watch` | Persist and load watch-mode configuration | Watch configuration flags / persistence controls | Saved config / loaded config | [`loadWatchConfig`](go/cmd/rekipedia/cmd/watch.go#L18), [`saveWatchConfig`](go/cmd/rekipedia/cmd/watch.go#L28) |

> **Sources:** `go/cmd/rekipedia/cmd/root.go` · L36–L78 · [`Execute`](go/cmd/rekipedia/cmd/root.go#L44) · `go/cmd/rekipedia/cmd/ask.go` · L87–L174 · [`runInteractiveAsk`](go/cmd/rekipedia/cmd/ask.go#L87) · `go/cmd/rekipedia/cmd/diff.go` · L119–L252 · [`runGit`](go/cmd/rekipedia/cmd/diff.go#L119) · `go/cmd/rekipedia/cmd/refactor.go` · L148–L175 · [`buildStaticReport`](go/cmd/rekipedia/cmd/refactor.go#L148) · `go/cmd/rekipedia/cmd/search.go` · L20–L51 · [`tokenizeSymbol`](go/cmd/rekipedia/cmd/search.go#L20) · `go/cmd/rekipedia/cmd/watch.go` · L18–L35 · [`loadWatchConfig`](go/cmd/rekipedia/cmd/watch.go#L18)

---

## Root Command

The application starts in [`main`](go/cmd/rekipedia/main.go#L6), which invokes [`Execute`](go/cmd/rekipedia/cmd/root.go#L44). The root command is the stable user entry point for the entire CLI, and it is responsible for initial command registration and top-level banner output.

### Behavior

From the available symbols, the observable root-level behavior is:

- a banner is printed through [`printRootBanner`](go/cmd/rekipedia/cmd/root.go#L36)
- the root command dispatches into registered subcommands via [`Execute`](go/cmd/rekipedia/cmd/root.go#L44)
- the command tree is assembled during package initialization in the root command file

### Example

```bash
rekipedia --help
rekipedia version
```

The exact top-level flag set is defined in the command registration code, but the analysis data only confirms root-level version handling and command wiring via [`Execute`](go/cmd/rekipedia/cmd/root.go#L44).

> **Sources:** `go/cmd/rekipedia/main.go` · L6–L8 · [`main`](go/cmd/rekipedia/main.go#L6) · `go/cmd/rekipedia/cmd/root.go` · L36–L78 · [`printRootBanner`](go/cmd/rekipedia/cmd/root.go#L36) · [`Execute`](go/cmd/rekipedia/cmd/root.go#L44)

---

## Interactive Assistant Commands

### `rekipedia ask`

The `ask` family provides an interactive question-and-answer interface over the repository content. The runtime path for the user-facing command is [`runInteractiveAsk`](go/cmd/rekipedia/cmd/ask.go#L87), which is the implementation symbol most directly tied to the command’s observable behavior.

#### User-facing behavior

This command is designed for interactive use:

- it prompts for a question or equivalent input
- it routes the user’s query through the repository-aware answering flow
- it can return streamed or non-streamed answers depending on runtime options

The implementation file shows that the command participates in a broader ask pipeline, but the details of context building are internal. For CLI users, the important contract is that `ask` is the conversational entry point for querying the repository.

#### Example

```bash
rekipedia ask
rekipedia ask "Where is the main entry point?"
```

Because the analysis data only exposes the runtime command handler symbol, not the exact flag matrix, this documentation keeps to the observable interaction model rather than enumerating undocumented options.

> **Sources:** `go/cmd/rekipedia/cmd/ask.go` · L87–L174 · [`runInteractiveAsk`](go/cmd/rekipedia/cmd/ask.go#L87)

---

## Repository Diff and Change Review Commands

### `rekipedia diff`

The diff command family is the CLI surface for reviewing repository changes in terms of symbols and affected files. The runtime command flow is anchored by [`runGit`](go/cmd/rekipedia/cmd/diff.go#L119), with supporting runtime symbols for loading symbol data and formatting the final output.

#### User-facing behavior

From the implementation symbols available:

- `diff` invokes git-backed change discovery via [`runGit`](go/cmd/rekipedia/cmd/diff.go#L119)
- it reads symbol metadata through [`loadSymbolsJSON`](go/cmd/rekipedia/cmd/diff.go#L126)
- it determines whether a symbol belongs to changed files using [`isInChangedFiles`](go/cmd/rekipedia/cmd/diff.go#L159)
- it emits either Markdown or plain-text output through [`formatDiffMd`](go/cmd/rekipedia/cmd/diff.go#L175) and [`formatDiffText`](go/cmd/rekipedia/cmd/diff.go#L216)

#### Example

```bash
rekipedia diff
rekipedia diff --format markdown
rekipedia diff --format text
```

The exact formatting behavior is controlled by the runtime formatter functions, so users can expect either a readable text summary or Markdown output suitable for pasting into docs or pull requests.

> **Sources:** `go/cmd/rekipedia/cmd/diff.go` · L119–L252 · [`runGit`](go/cmd/rekipedia/cmd/diff.go#L119) · [`loadSymbolsJSON`](go/cmd/rekipedia/cmd/diff.go#L126) · [`isInChangedFiles`](go/cmd/rekipedia/cmd/diff.go#L159) · [`formatDiffMd`](go/cmd/rekipedia/cmd/diff.go#L175) · [`formatDiffText`](go/cmd/rekipedia/cmd/diff.go#L216)

---

## Static Analysis and Refactor Reporting

### `rekipedia refactor`

The `refactor` command family generates a static report of refactor-related issues. The user-visible entry point into that reporting workflow is [`buildStaticReport`](go/cmd/rekipedia/cmd/refactor.go#L148).

#### User-facing behavior

The command is meant to scan repository content and present a report that can be filtered and formatted for review. From the exposed runtime symbol set:

- [`staticWalk`](go/cmd/rekipedia/cmd/refactor.go#L75) scans the repository
- [`applyFilter`](go/cmd/rekipedia/cmd/refactor.go#L130) narrows the result set
- [`buildStaticReport`](go/cmd/rekipedia/cmd/refactor.go#L148) renders the final report

Although the internal detection heuristics are implemented elsewhere, the CLI-facing contract is straightforward: `refactor` produces a static summary of issues for later action, review, or export.

#### Example

```bash
rekipedia refactor
rekipedia refactor --format markdown
rekipedia refactor --filter high
```

The analysis data does not expose every flag’s exact name and default in the command registration layer, so the examples above should be read as representative user flows rather than a definitive flag reference.

> **Sources:** `go/cmd/rekipedia/cmd/refactor.go` · L75–L175 · [`staticWalk`](go/cmd/rekipedia/cmd/refactor.go#L75) · [`applyFilter`](go/cmd/rekipedia/cmd/refactor.go#L130) · [`buildStaticReport`](go/cmd/rekipedia/cmd/refactor.go#L148)

---

## Search Commands

### `rekipedia search`

The search command family provides a symbol search experience over indexed repository content. The runtime symbol that best characterizes the user-facing search behavior is [`tokenizeSymbol`](go/cmd/rekipedia/cmd/search.go#L20), which prepares user queries or symbol names for ranking.

#### User-facing behavior

The search command presents ranked matches to the user. Based on the exposed symbols:

- queries are tokenized via [`tokenizeSymbol`](go/cmd/rekipedia/cmd/search.go#L20)
- results are scored with BM25-style ranking using [`scoreBM25`](go/cmd/rekipedia/cmd/search.go#L54)
- results are represented by the runtime `result` type defined in the same file

#### Example

```bash
rekipedia search "tokenizeSymbol"
rekipedia search "ask command"
```

Because the task scope explicitly excludes internal algorithms, this page treats the ranking logic as implementation detail and focuses on the observable user experience: enter a query, receive ranked symbol matches.

> **Sources:** `go/cmd/rekipedia/cmd/search.go` · L20–L71 · [`tokenizeSymbol`](go/cmd/rekipedia/cmd/search.go#L20) · [`scoreBM25`](go/cmd/rekipedia/cmd/search.go#L54)

---

## Git Hook and Watch Configuration Commands

### `rekipedia watch`

The watch command family persists runtime configuration for watch-mode workflows. The relevant runtime symbols are [`loadWatchConfig`](go/cmd/rekipedia/cmd/watch.go#L18) and [`saveWatchConfig`](go/cmd/rekipedia/cmd/watch.go#L28).

#### User-facing behavior

From the available code symbols, watch mode has a simple configuration lifecycle:

- load existing configuration with [`loadWatchConfig`](go/cmd/rekipedia/cmd/watch.go#L18)
- modify runtime settings during command execution
- persist changes back to disk with [`saveWatchConfig`](go/cmd/rekipedia/cmd/watch.go#L28)

This suggests a workflow-oriented command where users can store watch preferences rather than re-enter them on every invocation.

#### Example

```bash
rekipedia watch
rekipedia watch --save
rekipedia watch --load
```

The exact flag names are not fully visible in the analysis data, so only the general save/load behavior is documented here.

> **Sources:** `go/cmd/rekipedia/cmd/watch.go` · L14–L35 · [`loadWatchConfig`](go/cmd/rekipedia/cmd/watch.go#L18) · [`saveWatchConfig`](go/cmd/rekipedia/cmd/watch.go#L28)

### Git hook management

The repository also exposes a hook-related command family, but the task specifically requests only implementation symbols that are part of the runtime CLI. Since the analysis data does not provide a named runtime handler symbol analogous to `runInteractiveAsk` or `buildStaticReport` for hook execution, this page limits itself to the observable fact that hook command registration exists in the runtime command tree.

If you are looking for user-facing hook management, the runtime behavior is present in the command package, but the page does not speculate beyond what is directly evidenced by the analysis data.

> **Sources:** `go/cmd/rekipedia/cmd/hook.go` · L79–L82

---

## Command Families at a Glance

| Family | Typical Interaction Style | Main User Benefit |
|---|---|---|
| Root | Launch and dispatch | Starts the CLI cleanly and exposes command help |
| Ask | Interactive | Ask repository questions directly |
| Diff | Review | Summarize changes as symbols and files |
| Refactor | Reporting | Produce static issue reports for maintenance work |
| Search | Query | Find symbols quickly by name or token |
| Watch | Workflow state | Save and reload watch configuration |

> **Sources:** `go/cmd/rekipedia/cmd/root.go` · L36–L78 · `go/cmd/rekipedia/cmd/ask.go` · L87–L174 · `go/cmd/rekipedia/cmd/diff.go` · L119–L252 · `go/cmd/rekipedia/cmd/refactor.go` · L75–L175 · `go/cmd/rekipedia/cmd/search.go` · L20–L71 · `go/cmd/rekipedia/cmd/watch.go` · L14–L35

---

## Practical Usage Notes

The public CLI is intentionally cohesive: the root command launches the binary, while subcommands map onto common repository workflows.

### Recommended flows

- Use `rekipedia ask` when you want a conversational explanation of the codebase.
- Use `rekipedia diff` when reviewing a change set and you want a symbol-aware summary.
- Use `rekipedia refactor` to generate maintenance-focused reports.
- Use `rekipedia search` when you know part of a symbol name and need to locate it quickly.
- Use `rekipedia watch` when you want to persist workflow preferences for repeated use.

Because the analysis data is limited to runtime symbols and command registration artifacts, flag-level details beyond the visible command behavior are intentionally not over-specified here.

> **Sources:** `go/cmd/rekipedia/cmd/root.go` · L36–L78 · `go/cmd/rekipedia/cmd/ask.go` · L87–L174 · `go/cmd/rekipedia/cmd/diff.go` · L119–L252 · `go/cmd/rekipedia/cmd/refactor.go` · L75–L175 · `go/cmd/rekipedia/cmd/search.go` · L20–L71 · `go/cmd/rekipedia/cmd/watch.go` · L14–L35