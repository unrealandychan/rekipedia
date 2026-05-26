"""Build wiki pages from combined AnalysisResult using the LLM."""
from __future__ import annotations

import contextlib
import importlib.metadata
import json
import re
from datetime import UTC, datetime
from pathlib import Path

from rekipedia.llm.client import LLMCaller, LLMClient
from rekipedia.models.contracts import AnalysisResult, LLMConfig
from rekipedia.synthesis.doc_types import doc_type_preamble as _doc_type_preamble
from rekipedia.synthesis.planner import WikiPlan
from rekipedia.synthesis.slug_utils import sanitize_slug as _sanitize_slug

_SYSTEM_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "digest_system.md"

try:
    _SYSTEM_PROMPT = _SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
except FileNotFoundError:
    _SYSTEM_PROMPT = ""  # fallback, will fail gracefully later

# The 9 canonical pages every project wiki should have
CANONICAL_PAGES = [
    "index",
    "architecture",
    "core-modules",
    "algorithms",
    "cli-and-api",
    "installation-and-setup",
    "configuration",
    "testing",
    "ecosystem-and-integrations",
    "technical-debt",
]

_PAGE_FOCUS: dict[str, str] = {
    "index": """Write a comprehensive project overview page. Include:
## What is this project?
Explain the purpose, goals, and the problem it solves. Reference actual entry points and top-level modules.
## Who is it for?
Target audience and use cases.
## Key Features
Bullet list of the most important capabilities, grounded in the symbols and files found.
## Quick Start
The fastest way to get the project running — use build_commands and entry_points.
## Project Structure
A Mermaid diagram showing the top-level directory/module layout.
## How it Works (High Level)
A 3–5 sentence summary of the end-to-end flow, referencing real symbols.""",

    "architecture": """Write a deep architectural overview. Include:
## System Architecture
If a pre-built module graph is provided in the analysis data under `pre_built_module_graph`, embed it EXACTLY as-is in a mermaid code block — do NOT modify it. Otherwise generate your own `flowchart TD` diagram.
## Component Breakdown
For each major component: what it does, its responsibilities, and which files implement it. For every component, cite the file using inline source links e.g. [`ComponentClass`](path/to/file.py#L1).
## Entry Points
List all entry points from `entry_points` data. For each one: what triggers it, what it does, and inline source link.
## Data Flow
Step-by-step description of how data moves through the system. Use a Mermaid sequence or flowchart diagram.
## Key Design Decisions
Notable patterns used (e.g. plugin architecture, event-driven, pipeline, sandbox isolation). Reference actual code evidence with source citations.
## Inter-Module Dependencies
If a pre-built dependency graph is provided in `pre_built_dependency_graph`, embed it. Otherwise describe the major import relationships.""",

    "core-modules": """Document every significant module/package. For each one:
### Module Name (`path/to/module`)
- **Purpose**: what this module does
- **Public API**: list key exported classes and functions with their signatures
- **Key Classes**: brief description of each class, its constructor, and main methods
- **Key Functions**: signature + one-line description
- **Interactions**: which other modules it imports from / is imported by
Include a Mermaid `classDiagram` showing class hierarchies if applicable.""",

    "algorithms": """Document the core algorithms and data processing logic. Include:
## Overview
What computational problems does this project solve?
## Algorithm Descriptions
For each significant algorithm or processing pipeline found in the symbols:
### Algorithm / Pipeline Name
- **Input**: what data it receives
- **Steps**: numbered list of processing steps
- **Output**: what it produces
- **Complexity**: time/space if discernible from the code
- **Code Reference**: file and function name
## Data Structures
Key data structures (classes, types, schemas) used internally — use a table or class diagram.
## Processing Pipeline
Mermaid flowchart of the main processing pipeline end-to-end.""",

    "cli-and-api": """Document all CLI commands and programmatic APIs. Include:
## CLI Reference
For each CLI command/subcommand found:
### `command-name`
| Option | Type | Default | Description |
|--------|------|---------|-------------|
List all flags and arguments. Show a usage example.
## Programmatic API
For each public class/function intended for external use:
### `ClassName` / `function_name`
- Signature
- Parameters table
- Return value
- Example usage (code block)
## Integration Examples
Show how to use the CLI and API together in a realistic workflow.""",

    "installation-and-setup": """Write a complete installation and setup guide. Include:
## Requirements
System requirements, language versions, dependencies.
## Installation Methods
### From Source
Step-by-step using build_commands found in the analysis.
### Via Package Manager
If pyproject.toml / package.json found, show pip/uv/npm install commands.
### Docker
If Dockerfile found, show docker build and run commands.
## First Run
Walk through running the project for the first time.
## Environment Variables
Any configuration via env vars found in the evidence/config files.
## Troubleshooting
Common setup issues and how to resolve them.""",

    "configuration": """Document all configuration options. Include:
## Configuration Files
List every config file found (YAML, TOML, JSON, .env) with its purpose.
## Configuration Reference
For each config file, a full table:
| Key | Type | Default | Required | Description |
|-----|------|---------|----------|-------------|
## Configuration Examples
Show a minimal config and a full-featured config as code blocks.
## Runtime Configuration
Any CLI flags or env vars that override file-based config.
## Validation
Describe how config is validated (Pydantic models, schema, etc.).""",

    "testing": """Document the testing strategy and how to run tests. Include:
## Testing Philosophy
What is tested, what the coverage goals are, and the testing approach.
## Test Structure
Directory layout of tests. Which directories/files contain which kinds of tests.
## Running Tests
Use test_commands from analysis data. Show:
```bash
# unit tests
# integration tests
# with coverage
```
## Test Categories
### Unit Tests
What units are tested, key fixtures/mocks.
### Integration Tests
What integrations are exercised.
## Writing New Tests
Conventions to follow, where to put new tests, how to run a single test.
## CI/CD
If CI config found in evidence, describe the pipeline.""",

    "ecosystem-and-integrations": """Document external integrations, plugins, and the broader ecosystem. Include:
## External Dependencies
Table of all significant third-party libraries: name, version, purpose.
## Integrations
For each external system or service the project integrates with:
### Integration Name
- What it does
- How it's configured
- Code reference (file/class)
## Extension Points
Plugin interfaces, hooks, or extension mechanisms found in the codebase.
## Related Projects
Similar tools or projects in the same space (based on evidence in README/docs if found).
## Roadmap / Known Limitations
Any TODOs, FIXMEs, or risk items found in the analysis.""",
    "technical-debt": """Analyse and document all technical debt found in this codebase. Include:
## Summary
A 2–3 sentence executive summary of the overall technical health of the codebase. Give an overall debt rating: Low / Medium / High / Critical.
## Debt Inventory
A prioritised table of every debt item found:
| # | Area | Severity | Description | Files Affected | Effort to Fix |
|---|------|----------|-------------|----------------|---------------|
Severity: 🔴 Critical / 🟠 High / 🟡 Medium / 🟢 Low.
Effort: S (< 1 day) / M (1–3 days) / L (1–2 weeks) / XL (> 2 weeks).
## Critical Issues
For each Critical/High item: a dedicated subsection with exact file references, the problematic pattern, why it's a problem, and a concrete fix suggestion with code snippet if applicable.
## Code Smell Patterns
Recurring anti-patterns found (e.g. God classes, deep nesting, duplicated logic, missing error handling, hardcoded values). For each: show a real example from the code and the recommended refactor.
## Missing Tests
Areas with insufficient test coverage based on test_file_count and impl_file_count ratio. List specific modules/functions that lack tests.
## Dependency & Security Concerns
Outdated or risky dependencies found in pyproject.toml / package.json / go.mod. Flag any known CVE-prone patterns.
## TODO / FIXME Tracker
Extract and list every TODO, FIXME, HACK, XXX comment found in the codebase in a table: File | Line | Comment | Suggested Action.
## Refactoring Roadmap
A prioritised action plan — order by impact/effort ratio:
| Priority | Action | Rationale | Estimated Effort |
|----------|--------|-----------|-----------------|
Do NOT fabricate issues — only report what is actually evidenced in the symbols, files, and relationships provided.""",
}


class PageBuilder:
    """Generate wiki pages from an AnalysisResult using an LLM.

    If a wiki page already exists on disk with `pin: true` in its YAML
    frontmatter it is left unchanged.  `prompt_overrides` in config.yml
    can customise the per-page user prompt.
    """

    def __init__(
        self,
        llm_config: LLMConfig,
        prompt_overrides: dict[str, str] | None = None,
        exclude_pages: list[str] | None = None,
        wiki_dir: Path | None = None,
        *,
        caller: LLMCaller | None = None,
        doc_type: str = "default",
    ) -> None:
        self._client: LLMCaller = caller if caller is not None else LLMClient(llm_config)
        self._overrides = prompt_overrides or {}
        self._exclude = set(exclude_pages or [])
        self._wiki_dir = wiki_dir
        preamble = _doc_type_preamble(doc_type)
        self._system = (preamble + "\n\n" + _SYSTEM_PROMPT).lstrip() if preamble else _SYSTEM_PROMPT
        self._doc_type = doc_type

    def build(self, combined: AnalysisResult) -> dict[str, tuple[str, str]]:
        """Return {slug: (title, markdown_content)} for each page."""
        results: dict[str, tuple[str, str]] = {}
        for slug in CANONICAL_PAGES:
            page = self.build_one(slug, combined)
            if page:
                results[slug] = page
        return results

    def build_from_plan(
        self,
        plan: WikiPlan,
        combined: AnalysisResult,
        diagrams: dict | None = None,
    ) -> dict[str, tuple[str, str]]:
        """Build wiki pages according to a WikiPlan.

        Each page only receives the data fields it declared in required_data.
        Pages are built in parallel via ThreadPoolExecutor.
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        # Pre-build full payload once, then slice per page
        full_payload = _build_payload(combined, diagrams=diagrams)

        results: dict[str, tuple[str, str]] = {}
        with ThreadPoolExecutor(max_workers=4) as executor:
            future_to_spec = {
                executor.submit(
                    self._build_page_from_spec,
                    spec,
                    _slice_payload(full_payload, spec.get("required_data")),
                ): spec
                for spec in plan.pages
                if spec["slug"] not in self._exclude
            }
            for future in as_completed(future_to_spec):
                spec = future_to_spec[future]
                slug = spec["slug"]
                try:
                    result = future.result()
                    if result:
                        results[slug] = result
                except Exception as exc:
                    title = spec.get("title", slug.replace("-", " ").title())
                    results[slug] = (title, f"# {title}\n\n> *Generation failed: {exc}*\n")

        return results

    def _build_page_from_spec(
        self,
        spec: dict,
        payload_slice: dict,
    ) -> tuple[str, str] | None:
        """Build one page from a PageSpec dict with a pre-sliced payload."""
        slug = spec["slug"]
        title_hint = spec.get("title", slug.replace("-", " ").title())

        if self._wiki_dir and _is_pinned(self._wiki_dir / f"{slug}.md"):
            existing = (self._wiki_dir / f"{slug}.md").read_text()
            title = _extract_title(existing) or title_hint
            return (title, existing)

        focus = self._overrides.get(slug) or spec.get("focus", f"Write a wiki page about {slug}.")
        nav_hint = ""
        if spec.get("tags"):
            nav_hint = f"\nTags for this page: {', '.join(spec['tags'])}"

        user_prompt = (
            f"Task: {focus}{nav_hint}\n\n"
            f"Analysis data (JSON):\n{json.dumps(payload_slice, ensure_ascii=False)}"
        )

        try:
            raw = self._client.call(user_prompt, system=self._system)
            title, content = _parse_llm_response(raw, slug)
        except Exception as exc:
            if "contextwindow" in type(exc).__name__.lower() or "token" in str(exc).lower():
                import logging as _logging
                _logging.getLogger("rekipedia.synthesis").warning(
                    "Page %s: context window exceeded even after truncation — writing stub", slug
                )
                stub = f"# {title_hint}\n\n> *This page could not be generated: the codebase section was too large for the model context window. Try scanning with a model with larger context (e.g. gemini-1.5-pro).*\n"
                return (title_hint, stub)
            title = title_hint
            content = f"# {title}\n\n> *LLM synthesis failed: {exc}*\n"

        content = _ensure_frontmatter(
            slug, title, content,
            tags=spec.get("tags", []),
            section=spec.get("section"),
            importance=spec.get("importance", 50),
        )
        return (title, content)

    def build_one(self, slug: str, combined: AnalysisResult, _payload: dict | None = None) -> tuple[str, str] | None:
        """Build a single wiki page. Returns (title, content) or None if skipped.

        Pass a pre-built *_payload* dict to avoid recomputing it for every page
        when calling build_one in parallel (payload is the same for all pages).
        """
        if slug not in _PAGE_FOCUS and slug not in self._overrides:
            return None
        if slug in self._exclude:
            return None
        if self._wiki_dir and _is_pinned(self._wiki_dir / f"{slug}.md"):
            existing = (self._wiki_dir / f"{slug}.md").read_text()
            title = _extract_title(existing) or slug
            return (title, existing)

        payload = _payload if _payload is not None else _build_payload(combined)
        focus = self._overrides.get(slug) or _PAGE_FOCUS[slug]
        user_prompt = (
            f"Task: {focus}\n\n"
            f"Analysis data (JSON):\n{json.dumps(payload, ensure_ascii=False)}"
        )

        try:
            raw = self._client.call(user_prompt, system=self._system)
            title, content = _parse_llm_response(raw, slug)
        except Exception as exc:
            title = slug.replace("-", " ").title()
            content = f"# {title}\n\n> *LLM synthesis failed: {exc}*\n"

        content = _ensure_frontmatter(slug, title, content)
        return (title, content)


# ── helpers ──────────────────────────────────────────────────────────

_STDLIB_PREFIXES = (
    "os", "sys", "re", "io", "json", "math", "time", "datetime", "pathlib",
    "typing", "collections", "itertools", "functools", "threading", "logging",
    "abc", "copy", "enum", "uuid", "hashlib", "base64", "struct", "string",
    "urllib", "http", "socket", "subprocess", "shutil", "tempfile", "glob",
    "ast", "inspect", "importlib", "contextlib", "dataclasses", "warnings",
)

_CROSS_MODULE_KINDS = {"imports", "import", "calls", "call", "inherits", "inherit"}
_CROSS_MODULE_REVERSE = {
    "imports": "imported_by",
    "import": "imported_by",
    "calls": "called_by",
    "call": "called_by",
    "inherits": "inherited_by",
    "inherit": "inherited_by",
}


def _build_cross_module_summary(
    relationships: list,
    symbols: list,
    files_seen: list,
    *,
    limit: int = 100,
) -> dict:
    """Build a per-module relationship summary from a list of relationship dicts.

    Each entry looks like::

        {
            "modA": {
                "imports": ["modB"],
                "imported_by": [],
                "calls": ["modC"],
                "called_by": [],
                "inherits": [],
                "inherited_by": [],
            }
        }

    Only the first *limit* modules (by first-seen order) are included.
    Duplicate edges are deduplicated.
    """
    summary: dict[str, dict[str, list]] = {}

    def _entry(mod: str) -> dict:
        if mod not in summary:
            summary[mod] = {
                "imports": [],
                "imported_by": [],
                "calls": [],
                "called_by": [],
                "inherits": [],
                "inherited_by": [],
            }
        return summary[mod]

    for rel in relationships:
        if isinstance(rel, dict):
            from_ = rel.get("from_") or rel.get("from", "")
            to = rel.get("to", "")
            kind = (rel.get("kind") or "").lower()
        else:
            # Pydantic model
            from_ = getattr(rel, "from_", "") or ""
            to = getattr(rel, "to", "") or ""
            kind = (getattr(rel, "kind", "") or "").lower()

        if not from_ or not to:
            continue

        # Limit total entries
        if len(summary) >= limit and from_ not in summary and to not in summary:
            continue

        forward_key = (
            "imports" if kind in {"imports", "import"} else
            "calls" if kind in {"calls", "call"} else
            "inherits" if kind in {"inherits", "inherit"} else
            None
        )
        if forward_key is None:
            continue

        reverse_key = _CROSS_MODULE_REVERSE.get(kind)
        if reverse_key is None:
            continue

        fe = _entry(from_)
        if to not in fe[forward_key]:
            fe[forward_key].append(to)

        te = _entry(to)
        if from_ not in te[reverse_key]:
            te[reverse_key].append(from_)

    # Apply limit (keep insertion order)
    if len(summary) > limit:
        summary = dict(list(summary.items())[:limit])

    return summary


def _classify_file_role(path: str) -> str:
    """Classify a file as impl / test / ci / config / doc."""
    p = path.lower()
    parts = Path(p).parts
    ext = Path(path).suffix.lower()
    _CI_DIRS = {".github", ".gitlab", ".circleci", ".travis"}
    _DOC_EXTS = {".md", ".txt", ".rst"}
    _CONFIG_EXTS = {".yaml", ".yml", ".toml", ".json", ".env", ".cfg", ".ini"}
    if any(part in _CI_DIRS for part in parts):
        return "ci"
    if any(part.startswith("test") or part in ("tests", "spec", "specs", "__tests__") for part in parts):
        return "test"
    if ext in _DOC_EXTS:
        return "doc"
    if ext in _CONFIG_EXTS or any(kw in p for kw in ("config", "conf", "setting", "setup", ".env")):
        return "config"
    return "impl"


def _build_payload(combined: AnalysisResult, diagrams: dict | None = None) -> dict:
    # Build file role map so LLM can distinguish impl vs CI/test/config
    file_roles = {f: _classify_file_role(f) for f in combined.files_seen}

    # Build a compact symbol index: name -> {file, line_start, line_end, kind, role}
    # Prioritise impl symbols — they are far more useful than CI/test helpers
    impl_symbols = [s for s in combined.symbols if file_roles.get(s.file, "impl") == "impl"]
    other_symbols = [s for s in combined.symbols if file_roles.get(s.file, "impl") != "impl"]
    ordered_symbols = impl_symbols + other_symbols

    symbol_index = {
        s.name: {
            "file": s.file,
            "line_start": s.line_start,
            "line_end": s.line_end,
            "kind": s.kind,
            "role": file_roles.get(s.file, "impl"),
        }
        for s in ordered_symbols[:600]
    }

    # Separate files by role for LLM context clarity
    impl_files = [f for f in combined.files_seen if file_roles.get(f) == "impl"]
    test_files = [f for f in combined.files_seen if file_roles.get(f) == "test"]
    ci_files = [f for f in combined.files_seen if file_roles.get(f) == "ci"]

    payload = {
        "files_seen": combined.files_seen[:500],
        "impl_files": impl_files[:300],
        "test_files": test_files[:100],
        "ci_files": ci_files[:50],
        "file_roles": file_roles,
        "entry_points": combined.entry_points,
        "symbols": [
            {**s.model_dump(), "role": file_roles.get(s.file, "impl")}
            for s in ordered_symbols[:600]
        ],
        "symbol_index": symbol_index,
        "relationships": [r.model_dump(by_alias=True) for r in combined.relationships[:1500]],
        "build_commands": combined.build_commands,
        "test_commands": combined.test_commands,
        "risks": combined.risks,
        "evidence": combined.evidence,
    }
    # ── relationship enrichment ──────────────────────────────────────────────
    rels_raw = [r.model_dump(by_alias=True) for r in combined.relationships]
    # Stats
    by_kind: dict[str, int] = {}
    for rel in rels_raw:
        k = rel.get("kind", "unknown")
        by_kind[k] = by_kind.get(k, 0) + 1
    payload["relationship_stats"] = {"total": len(rels_raw), "by_kind": by_kind}
    # Internal relationships — filter out stdlib-like modules, cap at 800
    _STDLIB = _STDLIB_PREFIXES
    internal = [
        r for r in rels_raw
        if not any((r.get("from_") or r.get("from", "")).startswith(p + ".") or
                   (r.get("from_") or r.get("from", "")) == p
                   for p in _STDLIB)
    ]
    payload["internal_relationships"] = internal[:800]
    # Cross-module summary
    payload["cross_module_summary"] = _build_cross_module_summary(
        rels_raw, combined.symbols, combined.files_seen
    )
    from rekipedia.analysis.graph_analysis import _build_knowledge_gaps
    payload["knowledge_gaps"] = _build_knowledge_gaps(combined)
    from rekipedia.analysis.graph_analysis import _build_hub_nodes
    payload["hub_nodes"] = _build_hub_nodes(combined.relationships, combined.symbols)
    if diagrams:
        payload["pre_built_module_graph"] = diagrams.get("module-graph", ("", ""))[1]
        payload["pre_built_dependency_graph"] = diagrams.get("class-hierarchy", ("", ""))[1]
    else:
        payload["pre_built_module_graph"] = combined.evidence.get("pre_built_module_graph", "")
        payload["pre_built_dependency_graph"] = combined.evidence.get("pre_built_dependency_graph", "")
    return payload


def _slice_payload(full: dict, required_keys: list[str] | None) -> dict:
    """Return only the keys the page actually needs.

    If required_keys is None or empty, return the full payload.
    Always includes 'entry_points' and 'symbol_index' as a minimum.
    """
    if not required_keys:
        return full
    always = {"entry_points", "symbol_index"}
    keys = set(required_keys) | always
    return {k: v for k, v in full.items() if k in keys}


def _is_pinned(path: Path) -> bool:
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8")
    return bool(re.search(r"^pin:\s*true", text, re.MULTILINE))


def _extract_title(content: str) -> str | None:
    m = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
    return m.group(1).strip() if m else None


def _parse_llm_response(raw: str, slug: str) -> tuple[str, str]:
    """LLM now returns plain Markdown. Extract title from first H1."""
    raw = raw.strip()
    # Strip accidental outer fences
    raw = re.sub(r"^```(?:markdown)?\s*\n", "", raw)
    raw = re.sub(r"\n```\s*$", "", raw)
    title = _extract_title(raw) or slug.replace("-", " ").title()
    return title, raw


_ALLOWED_FRONTMATTER_KEYS = {"slug", "title", "section", "tags", "pin", "importance", "created_at", "rekipedia_version", "keywords"}


def _sanitize_slug(slug: str) -> str:
    """Normalise a slug: lowercase, replace bad chars with hyphens, collapse runs."""
    slug = slug.lower().strip()
    slug = re.sub(r"[^a-z0-9_-]+", "-", slug)
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug or "untitled"


def _ensure_frontmatter(
    slug: str,
    title: str,
    content: str,
    tags: list[str] | None = None,
    section: str = "general",
    importance: int = 50,
) -> str:
    """Strip any existing frontmatter and rebuild a canonical block.

    Always strips+rebuilds so LLM-hallucinated fields (e.g. wrong
    created_at format, extra keys) never leak into the rendered wiki.
    The ``importance`` value is preserved from the old block if present.
    """
    slug = _sanitize_slug(slug)

    # Strip existing frontmatter, preserving importance if set
    body = content
    if content.startswith("---"):
        end = content.find("\n---", 3)
        if end != -1:
            old_fm = content[3:end]
            # Preserve importance from old frontmatter if caller didn't set it
            if importance == 50:
                for line in old_fm.splitlines():
                    if line.startswith("importance:"):
                        with contextlib.suppress(ValueError):
                            importance = int(line.split(":", 1)[1].strip())
                        break
            body = content[end + 4:].lstrip("\n")

    created_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        version = importlib.metadata.version("rekipedia")
    except importlib.metadata.PackageNotFoundError:
        version = "dev"

    tags_line = f"tags: [{', '.join(tags)}]\n" if tags else ""
    fm = (
        f"---\n"
        f"slug: {slug}\n"
        f'title: "{title}"\n'
        f"section: {section}\n"
        f"{tags_line}"
        f"pin: false\n"
        f"importance: {importance}\n"
        f"created_at: {created_at}\n"
        f"rekipedia_version: {version}\n"
        f"---\n\n"
    )
    return fm + body
