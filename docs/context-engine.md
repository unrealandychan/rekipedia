# Context Engine

The rekipedia context engine assembles grounded knowledge for the `reki ask` pipeline by combining multiple sources:

- **Wiki pages** — prose summaries generated from the scanned codebase
- **Symbol index** — structured listing of all functions, classes, and methods
- **RAG chunks** — semantic search results from the FAISS embedding index
- **Git history** — recent commits surfaced when history-related keywords are detected
- **External sources** — GitHub Issues/PRs and Linear tickets linked to code symbols

## Multi-source Deconfliction

When external sources (GitHub Issues, Linear tickets) are present, rekipedia automatically runs **deconfliction** after generating an answer. The `DeconflictionEngine` (`src/rekipedia/orchestrator/deconfliction.py`) applies three heuristic rules:

| Rule | Description |
|------|-------------|
| `stale_ticket` | A ticket is marked done/closed/resolved but still references a symbol that appears in the code, suggesting the fix may be incomplete or the ticket is stale. |
| `todo_never_linked` | The code near the queried symbol contains a `# TODO` or `# FIXME` comment, but no external ticket references that symbol — indicating untracked work. |
| `resolved_but_code_unchanged` | A closed ticket claims to have "fixed" something and names a specific code pattern (in backticks), but that pattern still appears verbatim in the codebase. |

If any conflicts are detected, a **⚠️ Context Conflicts Detected** section is appended to the answer. Deconfliction is silent when no external sources have been fetched and never makes LLM calls — it is purely rule-based.
