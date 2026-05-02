# rekipedia

> Agentic repo-to-wiki: scan any repository into a portable SQLite knowledge store with wiki pages, diagrams, and grounded Q&A.

## Installation

### Homebrew (macOS / Linux)

```bash
brew tap unrealandychan/tap
brew install rekipedia
```

### Download Binary

Download the latest release from [GitHub Releases](https://github.com/unrealandychan/rekipedia/releases).

| Platform | Architecture | File |
|----------|-------------|------|
| macOS    | Apple Silicon (M1/M2/M3) | `rekipedia_darwin_arm64.tar.gz` |
| macOS    | Intel | `rekipedia_darwin_amd64.tar.gz` |
| Linux    | x86_64 | `rekipedia_linux_amd64.tar.gz` |
| Linux    | ARM64 | `rekipedia_linux_arm64.tar.gz` |
| Windows  | x86_64 | `rekipedia_windows_amd64.zip` |

Extract and move the binary to your `$PATH`:

```bash
tar -xzf rekipedia_darwin_arm64.tar.gz
mv rekipedia /usr/local/bin/
```

## Usage

```bash
# Scan a repository and generate wiki
rekipedia scan --path /path/to/repo

# Serve the wiki locally
rekipedia serve --path /path/to/repo

# Ask questions about the codebase
rekipedia ask --path /path/to/repo "How does the authentication work?"

# Update wiki after code changes
rekipedia update --path /path/to/repo

# Scan specific languages only
rekipedia scan --path /path/to/repo --languages go,python,typescript
```

## Commands

| Command | Description |
|---------|-------------|
| `scan` | Scan repository and generate wiki pages |
| `serve` | Start local web server to browse the wiki |
| `ask` | Ask questions about the codebase (grounded Q&A) |
| `update` | Incrementally update wiki after code changes |
| `embed` | Generate embeddings for semantic search |

## Supported Languages

- Go
- Python
- TypeScript / JavaScript
- Rust
- Java
- Ruby
- C / C++

## Configuration

Create a `config.yml` in your project root:

```yaml
llm:
  provider: openai
  model: gpt-4o
  api_key: your-api-key

output_dir: .wiki
```

## Full Documentation

See the [main repository](https://github.com/unrealandychan/rekipedia) for full documentation, Python package, and advanced usage.
