"""Hyperedge detector: identifies N-ary relationships (design patterns, shared concepts, architectural motifs)."""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from rekipedia.models.contracts import Relationship, Symbol
from rekipedia.models.hyperedge import Hyperedge


def detect_structural_hyperedges(  # noqa: C901
    symbols: list[Symbol | dict],
    relationships: list[Relationship | dict],
    min_nodes: int = 3,
) -> list[Hyperedge]:
    """Detect architectural patterns and shared concepts from AST symbols and relationships.

    Identifies groups of 3+ symbols implementing common patterns:
    - Repository Pattern (*Repository, *Repo)
    - Service Layer (*Service)
    - Controller / API Layer (*Controller, *Handler, *Router)
    - Factory Pattern (*Factory)
    - Shared Interface / Base Class inheritance clusters
    """
    hyperedges: list[Hyperedge] = []

    # Normalize symbols and relationships
    sym_list: list[dict] = []
    for s in symbols:
        if hasattr(s, "model_dump"):
            sym_list.append(s.model_dump())
        elif isinstance(s, dict):
            sym_list.append(s)
        else:
            sym_list.append({"name": getattr(s, "name", ""), "kind": getattr(s, "kind", ""), "file": getattr(s, "file", "")})

    rel_list: list[dict] = []
    for r in relationships:
        if hasattr(r, "model_dump"):
            rel_list.append(r.model_dump())
        elif isinstance(r, dict):
            rel_list.append(r)
        else:
            rel_list.append({
                "from_": getattr(r, "from_", ""),
                "to": getattr(r, "to", ""),
                "kind": getattr(r, "kind", ""),
            })

    # 1. Pattern detection by naming motifs (Repository, Service, Controller, Factory)
    patterns = [
        (
            "Repository Pattern",
            re.compile(r"^[A-Z][a-zA-Z0-9]*(Repository|Repo)$"),
            "design_pattern",
            "Classes implementing the Repository Pattern to encapsulate data access and persistence logic.",
        ),
        (
            "Service Layer Pattern",
            re.compile(r"^[A-Z][a-zA-Z0-9]*Service$"),
            "architectural_motif",
            "Domain services coordinating business logic and use cases.",
        ),
        (
            "Controller / Handler Pattern",
            re.compile(r"^[A-Z][a-zA-Z0-9]*(Controller|Handler|Router|Endpoint)$"),
            "architectural_motif",
            "API endpoint handlers and request routing controllers.",
        ),
        (
            "Factory Pattern",
            re.compile(r"^[A-Z][a-zA-Z0-9]*Factory$"),
            "design_pattern",
            "Factory components responsible for instantiating and configuring domain objects.",
        ),
    ]

    for concept_name, pattern_re, pattern_type, desc in patterns:
        matching_nodes = [
            s["name"] for s in sym_list
            if s.get("name") and pattern_re.match(s["name"])
        ]
        if len(matching_nodes) >= min_nodes:
            slug = re.sub(r"[^a-z0-9]+", "_", concept_name.lower()).strip("_")
            hyperedges.append(
                Hyperedge(
                    id=f"pattern::{slug}",
                    concept=concept_name,
                    nodes=sorted(list(set(matching_nodes))),
                    description=desc,
                    confidence="EXTRACTED",
                    pattern_type=pattern_type,
                )
            )

    # 2. Inheritance clusters: 3+ classes inheriting from the same base class
    base_to_children: dict[str, list[str]] = defaultdict(list)
    for r in rel_list:
        kind = str(r.get("kind", ""))
        frm = r.get("from_") or r.get("from", "")
        to = r.get("to", "")
        if kind in ("inherits", "implements", "extends") and frm and to:
            base_to_children[to].append(frm)

    for base, children in base_to_children.items():
        unique_children = sorted(list(set(children)))
        if len(unique_children) >= min_nodes:
            slug = re.sub(r"[^a-z0-9]+", "_", base.lower()).strip("_")
            hyperedges.append(
                Hyperedge(
                    id=f"inheritance::{slug}",
                    concept=f"{base} Implementations",
                    nodes=unique_children,
                    description=f"Cluster of classes extending or implementing common abstraction `{base}`.",
                    confidence="EXTRACTED",
                    pattern_type="shared_concept",
                )
            )

    return hyperedges


def detect_hyperedges(
    symbols: list[Any],
    relationships: list[Any],
    llm_client: Any = None,  # noqa: ANN401
    min_nodes: int = 3,
) -> list[Hyperedge]:
    """Detect hyperedges using structural analysis, optionally enriched with LLM."""
    structural = detect_structural_hyperedges(symbols, relationships, min_nodes=min_nodes)
    # If no LLM client or --no-llm, return structural hyperedges directly
    if not llm_client:
        return structural

    # Optional LLM detection for higher-level architectural motifs
    try:
        sym_names = [getattr(s, "name", "") if hasattr(s, "name") else s.get("name", "") for s in symbols][:50]
        sym_names = [n for n in sym_names if n]
        if len(sym_names) >= min_nodes:
            prompt = (
                "Given the following symbols in a codebase, identify any groups of 3 or more symbols "
                "that together implement a named design pattern, architectural motif, or shared concept.\n"
                f"Symbols: {', '.join(sym_names[:30])}\n\n"
                "Return a JSON array of objects with keys:\n"
                "- concept: string (e.g. 'Event-Driven Pipeline', 'Observer Pattern')\n"
                "- nodes: list of strings (must be exact names from the symbols list, at least 3)\n"
                "- description: string (1 sentence explaining the relationship)\n"
                "- pattern_type: 'design_pattern' | 'architectural_motif' | 'shared_concept'\n"
                "Return only valid JSON."
            )
            import json
            response = llm_client.complete(
                prompt=prompt,
                system="You are an expert software architect analyzing code structure for design patterns.",
            )
            raw = response.strip()
            if raw.startswith("```"):
                raw = re.sub(r"^```(?:json)?\s*", "", raw)
                raw = re.sub(r"\s*```$", "", raw)
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                for item in parsed:
                    nodes = item.get("nodes", [])
                    concept = item.get("concept", "")
                    if len(nodes) >= min_nodes and concept:
                        slug = re.sub(r"[^a-z0-9]+", "_", concept.lower()).strip("_")
                        structural.append(
                            Hyperedge(
                                id=f"llm::{slug}",
                                concept=concept,
                                nodes=nodes,
                                description=item.get("description", ""),
                                confidence="INFERRED",
                                pattern_type=item.get("pattern_type", "architectural_motif"),
                            )
                        )
    except Exception:
        # Fall back gracefully to structural hyperedges
        pass

    # Deduplicate by ID
    seen_ids = set()
    deduped = []
    for h in structural:
        if h.id not in seen_ids:
            seen_ids.add(h.id)
            deduped.append(h)
    return deduped
