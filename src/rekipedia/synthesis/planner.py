"""PlannerAgent — decides wiki structure dynamically from analysis data."""
from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Callable
from pathlib import Path

from rekipedia.llm.client import LLMClient
from rekipedia.models.contracts import AnalysisResult, LLMConfig

logger = logging.getLogger("rekipedia.planner")

_SYSTEM_PROMPT = """\
You are a technical documentation architect for software repositories. Your task: analyse a repo's static-analysis data and design the OPTIMAL wiki structure — like DeepWiki does for open-source projects.

Output a single JSON object — no markdown fences, no commentary:

{
  "sections": [
    {"id": "getting-started", "title": "Getting Started", "pages": ["index", "installation"]}
  ],
  "pages": [
    {
      "slug": "lowercase-hyphenated",
      "title": "Human Readable Title",
      "section": "section-id",
      "priority": 1,
      "importance": 90,
      "focus": "Very detailed instruction: exact sections to write, what tables/diagrams to include, which symbols to document.",
      "required_data": ["files_seen"],
      "tags": ["overview"]
    }
  ],
  "nav_order": ["slug1", "slug2"],
  "index_slug": "index"
}

## importance field (0–100):
Assign an importance score to each page:
- 95–100: index, architecture-overview (always-read pages)
- 80–94: core-module pages, data-flow, repository-structure
- 60–79: api-reference, configuration, testing
- 40–59: internals, algorithms, contributing
- 20–39: ecosystem, deployment, third-party integrations
importance drives nav prominence in the web UI and determines which pages are shown first.

## Section design (inspired by DeepWiki)

Group pages into logical sections. Common section patterns (adapt to actual repo):

| Section id | Title | Typical pages |
|---|---|---|
| getting-started | Getting Started | index, installation-and-setup, quick-start, configuration |
| architecture | Architecture | architecture-overview, data-flow, component-map, repository-structure |
| core-components | Core Components | One page per major module/subsystem |
| api-reference | API Reference | cli-reference, python-api, rest-api, data-models |
| internals | Internals | algorithms, data-structures, performance, concurrency |
| development | Development | testing, contributing, ci-cd, release-process |
| ecosystem | Ecosystem | integrations, plugins, third-party, deployment |

Only create sections that have ≥2 pages. If a section would have 1 page, merge it into the nearest section or make it standalone.

## Always include these pages (if data supports):
- `index`: Project overview, key features, quick-start snippet, repo structure tree (as code block), badges
- `repository-structure`: Full repo layout with annotations — every top-level dir/file explained. Use a tree diagram + table. REQUIRED if file_count ≥ 10.
|- `architecture-overview`: System diagram (Mermaid flowchart LR), component responsibilities, design decisions, data flow
- `technical-debt`: **ALWAYS include this page.** Analyse TODO/FIXME comments, code smells, missing tests, risky dependencies, and anti-patterns. Importance: 70. Section: development. required_data: [\"symbols\", \"files_seen\", \"relationships\"]

## Page splitting rules (critical for large repos):
- If a repo has ≥5 major top-level modules → one page PER module (e.g. `module-cli`, `module-storage`, `module-llm`)
- If architecture has distinct layers → split `architecture-overview` + `architecture-data-flow`
- If API is large → split `cli-reference` + `python-api` + `rest-api`
- Each page should be 400–1200 words. Too long = split. Too short = merge.
- Target: large repos → 10–15 pages; medium → 6–10 pages; small tools → 3–5 pages
- Use `impl_file_count` to gauge repo complexity: high impl_file_count → more core-component pages
- Use `test_file_count` to decide whether a dedicated `testing` page is warranted (skip if test_file_count < 3)
- Use `config_file_count` to decide whether a `configuration` page is needed (skip if config_file_count < 2)

## Focus instructions (write these carefully — they guide the LLM writing each page):
For each page, write a detailed `focus` (3–6 sentences) that specifies:
1. Exact sections/headings to include
2. Which tables to build (e.g. "Build a table of all CLI flags with types and defaults")
3. Which Mermaid diagrams (e.g. "Include a flowchart LR showing the scan pipeline")
4. Which symbols to document with source citations [ClassName](file.py#Lxx)
5. What NOT to include (keep scope tight)

Example focus for `repository-structure`:
"Create a complete repository map. Start with an annotated tree (```text block) showing every top-level directory and key files. Then a table: Directory | Purpose | Key Files. Explain the src layout, test layout, config files. Include a Mermaid graph showing how top-level packages depend on each other. Do NOT duplicate architecture content."

Example focus for `index`:
"Write a project overview for a developer landing on this page for the first time. Sections: What is it (2 sentences), Key Features (bullet list), Quick Start (code block with install + first command), Repository Map (tree of top dirs), Architecture at a glance (one-paragraph summary + link to architecture page). Include version badge and build status."

## required_data minimisation:
- `index`, `repository-structure`: files_seen, entry_points, build_commands, symbol_index
- `architecture-*`, `data-flow`: relationships, symbols, pre_built_module_graph, pre_built_dependency_graph, symbol_index
- module-specific pages: symbols (filtered), relationships (filtered), symbol_index
- `cli-reference`, `python-api`: symbols, entry_points, symbol_index
- `installation-and-setup`, `configuration`: build_commands, evidence, files_seen
- `testing`, `ci-cd`: test_commands, symbols, files_seen
- `algorithms`, `internals`: symbols, relationships, symbol_index
Never request full symbols+relationships for non-code pages.

## Navigation order:
Order: index → repo-structure → architecture → core-modules (section) → api-reference (section) → internals → development → ecosystem
Within each section, order from conceptual overview → specific reference.

## Tags (2–4 per page from):
overview, architecture, getting-started, reference, api, cli, testing, configuration, algorithms, deployment, modules, internals, ecosystem, data-flow, repository-structure, contributing
"""


class WikiPlan:
    """The output of PlannerAgent — a structured plan for wiki generation."""

    def __init__(self, data: dict) -> None:
        self.pages: list[dict] = data.get("pages", [])
        self.sections: list[dict] = data.get("sections", [])
        self.index_slug: str = data.get("index_slug", "index")

        # Build nav_order: respect planner's explicit order if provided,
        # then sort by importance (desc) then priority (asc) for stable ordering.
        raw_nav = data.get("nav_order", [])
        if raw_nav:
            # Planner provided an order — honour it, then append any missing slugs
            ordered = list(raw_nav)
            known = set(ordered)
            extras = sorted(
                [p for p in self.pages if p["slug"] not in known],
                key=lambda p: (-p.get("importance", 50), p.get("priority", 99)),
            )
            self.nav_order: list[str] = ordered + [p["slug"] for p in extras]
        else:
            # No explicit order — sort by importance desc, priority asc
            sorted_pages = sorted(
                self.pages,
                key=lambda p: (-p.get("importance", 50), p.get("priority", 99)),
            )
            self.nav_order = [p["slug"] for p in sorted_pages]

    def get_page(self, slug: str) -> dict | None:
        return next((p for p in self.pages if p["slug"] == slug), None)

    def get_section_for(self, slug: str) -> str | None:
        for s in self.sections:
            if slug in s.get("pages", []):
                return s["id"]
        return None

    def __repr__(self) -> str:
        section_ids = [s["id"] for s in self.sections]
        return f"WikiPlan({len(self.pages)} pages in {len(self.sections)} sections: {section_ids})"


class PlannerAgent:
    """One LLM call that designs the entire wiki structure."""

    def __init__(self, llm_config: LLMConfig) -> None:
        self._client = LLMClient(llm_config)

    def plan(
        self,
        combined: AnalysisResult,
        diagrams: dict | None = None,
        progress_cb: "Callable[[str], None] | None" = None,
    ) -> WikiPlan:
        """Analyse *combined* and return a WikiPlan.

        *progress_cb* is called with status strings during the (blocking) LLM
        call so callers can animate a spinner.  Falls back to a sensible
        default plan if the LLM call fails.
        """
        import threading  # noqa: PLC0415

        summary = _build_planning_summary(combined, diagrams)
        n_files = summary["file_count"]
        n_symbols = summary["symbol_count"]
        prompt = f"Repository analysis data:\n{json.dumps(summary, ensure_ascii=False)}"

        # Spin up a heartbeat thread that fires progress_cb every 0.5s
        _done = threading.Event()
        if progress_cb:
            progress_cb(
                f"🧠 PlannerAgent analysing {n_files} files, "
                f"{n_symbols} symbols…"
            )

            def _heartbeat() -> None:
                elapsed = 0.0
                phases = [
                    (10,  "📂 Reviewing repository structure…"),
                    (30, "🔍 Identifying key components…"),
                    (60, "🗂  Deciding page sections…"),
                    (120, "✍️  Writing page focus instructions…"),
                    (240, "📐 Finalising navigation order…"),
                    (999, "⏳ Almost there…"),
                ]
                phase_idx = 0
                while not _done.wait(0.5):
                    elapsed += 0.5
                    # Advance phase label when time threshold passed
                    while phase_idx < len(phases) - 1 and elapsed >= phases[phase_idx][0]:
                        phase_idx += 1
                    label = phases[phase_idx][1]
                    progress_cb(f"{label} ({elapsed:.0f}s)")

            t = threading.Thread(target=_heartbeat, daemon=True)
            t.start()
        else:
            t = None

        # Planner generates a large structured JSON — give it extra time
        _PLANNER_TIMEOUT = int(os.environ.get("REKIPEDIA_PLANNER_TIMEOUT", "600"))
        try:
            raw = self._client.call(prompt, system=_SYSTEM_PROMPT, timeout=_PLANNER_TIMEOUT)
        except Exception as exc:
            _done.set()
            if t:
                t.join(timeout=1)
            logger.warning("PlannerAgent failed (%s) — using default plan", exc)
            if progress_cb:
                progress_cb(f"⚠️  Planner failed ({type(exc).__name__}), using default plan")
            return _default_plan(combined)
        finally:
            _done.set()
            if t:
                t.join(timeout=1)

        raw = raw.strip()
        raw = re.sub(r"^```(?:json)?\s*\n?", "", raw)
        raw = re.sub(r"\n?```\s*$", "", raw)
        try:
            data = json.loads(raw)
            plan = WikiPlan(data)
        except Exception as exc:
            logger.warning("PlannerAgent JSON parse failed (%s) — using default plan", exc)
            if progress_cb:
                progress_cb("⚠️  Planner response unparseable, using default plan")
            return _default_plan(combined)

        logger.debug("PlannerAgent designed %d pages: %s", len(plan.pages), [p["slug"] for p in plan.pages])
        if progress_cb:
            section_names = ", ".join(s["title"] for s in plan.sections) or "—"
            progress_cb(
                f"✅ Plan ready: {len(plan.pages)} pages in {len(plan.sections)} sections "
                f"({section_names})"
            )
        return plan


def _build_planning_summary(combined: AnalysisResult, diagrams: dict | None) -> dict:
    """Compact summary for the planner — enough to make structural decisions."""
    # Count files by extension
    ext_counts: dict[str, int] = {}
    for f in combined.files_seen:
        ext = Path(f).suffix.lower() or "(no ext)"
        ext_counts[ext] = ext_counts.get(ext, 0) + 1

    # Count symbols by kind
    kind_counts: dict[str, int] = {}
    for s in combined.symbols:
        kind_counts[s.kind] = kind_counts.get(s.kind, 0) + 1

    # Detect what's present
    has_tests = any(
        "test" in f.lower() or "spec" in f.lower()
        for f in combined.files_seen
    ) or bool(combined.test_commands)

    has_cli = any(
        any(kw in (s.name or "").lower() for kw in ("cli", "command", "cmd", "click", "argparse", "argv"))
        for s in combined.symbols
    ) or any(kw in str(combined.evidence).lower() for kw in ("click", "argparse"))

    has_config = any(
        Path(f).suffix.lower() in (".yaml", ".yml", ".toml", ".json", ".env", ".cfg", ".ini")
        for f in combined.files_seen
    ) or bool(combined.evidence)

    # Implementation vs test/config file counts (same heuristic as RAG embedder)
    _DOC_EXTS = {".md", ".txt", ".rst", ".yaml", ".yml", ".toml", ".json"}
    impl_file_count = 0
    test_file_count = 0
    config_file_count = 0
    for f in combined.files_seen:
        p = f.lower()
        parts = Path(p).parts
        ext = Path(f).suffix.lower()
        if any(part.startswith("test") or part in ("tests", "spec", "specs", "__tests__") for part in parts):
            test_file_count += 1
        elif ext in _DOC_EXTS or any(kw in p for kw in ("config", "conf", "setting", "setup", ".env")):
            config_file_count += 1
        else:
            impl_file_count += 1

    # Top-level modules/directories
    top_dirs = sorted({
        Path(f).parts[0] for f in combined.files_seen if "/" in f
    })

    # Sample of symbols for planner context (just names + kinds, not full dump)
    symbol_sample = [
        {"name": s.name, "kind": s.kind, "file": s.file}
        for s in combined.symbols[:80]
    ]

    return {
        "file_count": len(combined.files_seen),
        "impl_file_count": impl_file_count,
        "test_file_count": test_file_count,
        "config_file_count": config_file_count,
        "file_extensions": ext_counts,
        "top_level_dirs": top_dirs[:20],
        "entry_points": combined.entry_points[:10],
        "symbol_count": len(combined.symbols),
        "symbol_kinds": kind_counts,
        "symbol_sample": symbol_sample,
        "relationship_count": len(combined.relationships),
        "build_commands": combined.build_commands[:10],
        "test_commands": combined.test_commands[:10],
        "has_tests": has_tests,
        "has_cli": has_cli,
        "has_config": has_config,
        "risks_count": len(combined.risks),
        "evidence_keys": list(combined.evidence.keys())[:20],
        "diagram_names": list((diagrams or {}).keys()),
    }


def _default_plan(combined: AnalysisResult) -> WikiPlan:
    """Fallback plan when LLM planning fails — uses heuristics."""
    has_tests = any("test" in f.lower() for f in combined.files_seen) or bool(combined.test_commands)
    has_cli = any("cli" in f.lower() or "cmd" in f.lower() for f in combined.files_seen)
    has_config = bool(combined.evidence) or bool(combined.build_commands)

    pages = [
        {
            "slug": "index",
            "title": "Project Overview",
            "priority": 1,
            "focus": "Write a comprehensive project overview: what it does, key features, quick start, and project structure with a Mermaid diagram.",
            "required_data": ["files_seen", "entry_points", "build_commands", "symbol_index", "pre_built_module_graph"],
            "tags": ["overview", "getting-started"],
        },
        {
            "slug": "architecture",
            "title": "Architecture",
            "priority": 2,
            "focus": "System architecture: major components, data flow, design decisions. Embed pre_built_module_graph if available.",
            "required_data": ["relationships", "entry_points", "symbols", "pre_built_module_graph", "pre_built_dependency_graph", "symbol_index"],
            "tags": ["architecture", "internals"],
        },
        {
            "slug": "core-modules",
            "title": "Core Modules",
            "priority": 3,
            "focus": "Document every significant module: purpose, public API, key classes/functions with source citations.",
            "required_data": ["symbols", "relationships", "files_seen", "symbol_index"],
            "tags": ["modules", "reference", "api"],
        },
    ]

    if has_cli:
        pages.append({
            "slug": "cli-and-api",
            "title": "CLI & API Reference",
            "priority": 4,
            "focus": "Document all CLI commands with options tables and usage examples. Document programmatic API.",
            "required_data": ["symbols", "entry_points", "files_seen", "symbol_index"],
            "tags": ["cli", "api", "reference"],
        })

    if has_config:
        pages.append({
            "slug": "installation-and-setup",
            "title": "Installation & Setup",
            "priority": 5,
            "focus": "Complete installation guide: requirements, installation methods, first run, env vars, troubleshooting.",
            "required_data": ["build_commands", "evidence", "files_seen"],
            "tags": ["getting-started", "deployment"],
        })

    if has_tests:
        pages.append({
            "slug": "testing",
            "title": "Testing",
            "priority": 6,
            "focus": "Testing strategy, test structure, how to run tests, how to write new tests.",
            "required_data": ["test_commands", "symbols", "files_seen"],
            "tags": ["testing"],
        })

    # Always add technical-debt page
    pages.append({
        "slug": "technical-debt",
        "title": "Technical Debt",
        "priority": 7,
        "focus": "Analyse TODO/FIXME comments, code smells, missing tests, risky dependencies, anti-patterns. Produce a prioritised debt inventory table with severity + effort estimates. Include a refactoring roadmap.",
        "required_data": ["symbols", "files_seen", "relationships"],
        "tags": ["internals", "contributing"],
        "section": "development",
    })

    nav_order = [p["slug"] for p in sorted(pages, key=lambda x: x["priority"])]
    sections = [
        {"id": "getting-started", "title": "Getting Started", "pages": ["index", "installation-and-setup"]},
        {"id": "architecture", "title": "Architecture", "pages": ["architecture"]},
        {"id": "core-components", "title": "Core Components", "pages": ["core-modules"]},
    ]
    # Filter sections to only include slugs present in pages
    page_slugs = {p["slug"] for p in pages}
    filtered_sections = []
    for section in sections:
        present = [slug for slug in section["pages"] if slug in page_slugs]
        if len(present) >= 1:
            filtered_sections.append({**section, "pages": present})
    # Update page section field
    slug_to_section = {}
    for s in filtered_sections:
        for slug in s["pages"]:
            slug_to_section[slug] = s["id"]
    for p in pages:
        if p["slug"] in slug_to_section:
            p["section"] = slug_to_section[p["slug"]]
    return WikiPlan({"pages": pages, "sections": filtered_sections, "nav_order": nav_order, "index_slug": "index"})
