"""Build Mermaid diagrams from relationship data."""
from __future__ import annotations

import re


class DiagramBuilder:
    """Generate Mermaid diagrams from relationship rows."""

    def build(self, relationships: list, entry_points: list[str] | None = None) -> dict[str, tuple[str, str]]:
        """Return {name: (diagram_type, mermaid_content)}."""
        results: dict[str, tuple[str, str]] = {}
        if not relationships:
            return results
        rows = [_to_dict(r) for r in relationships]
        results["module-graph"] = ("flowchart", _build_module_graph(rows, entry_points=entry_points))
        results["class-hierarchy"] = ("classDiagram", _build_class_hierarchy(rows))
        return results


# ── diagram builders ─────────────────────────────────────────────────

def _build_module_graph(rows: list[dict], entry_points: list[str] | None = None) -> str:
    """flowchart LR showing module relationships with labelled edges and entry point highlights."""
    entry_set = set(entry_points or [])

    # Collect all edges by type
    import_edges: list[tuple[str, str]] = []
    call_edges: list[tuple[str, str]] = []
    inherit_edges: list[tuple[str, str]] = []

    seen_nodes: set[str] = set()

    for r in rows:
        frm = r.get("from_") or r.get("from") or ""
        to = r.get("to") or ""
        kind = r.get("kind") or ""
        if not frm or not to:
            continue
        # Only keep internal relationships — filter out stdlib/well-known external packages
        _EXTERNAL_PREFIXES = (
            "os", "sys", "re", "io", "json", "time", "math", "typing", "pathlib",
            "collections", "itertools", "functools", "dataclasses", "enum", "abc",
            "logging", "threading", "subprocess", "asyncio", "contextlib", "copy",
            "hashlib", "base64", "uuid", "random", "datetime", "string", "struct",
            # popular third-party
            "fastapi", "pydantic", "sqlalchemy", "django", "flask", "requests",
            "httpx", "aiohttp", "numpy", "pandas", "torch", "sklearn", "openai",
            "boto3", "celery", "redis", "pytest", "click", "typer", "rich",
            "starlette", "uvicorn", "gunicorn", "alembic", "litellm", "faiss",
        )
        if kind == "import":
            # Keep if it looks internal: has path separator, has dot-notation, or
            # doesn't start with a known external package name
            is_external = any(to == p or to.startswith(p + ".") or to.startswith(p + "/")
                              for p in _EXTERNAL_PREFIXES)
            if not is_external and to:
                import_edges.append((frm, to))
                seen_nodes.add(frm)
                seen_nodes.add(to)
        elif kind == "call":
            call_edges.append((frm, to))
            seen_nodes.add(frm)
            seen_nodes.add(to)
        elif kind == "inherits":
            inherit_edges.append((frm, to))
            seen_nodes.add(frm)
            seen_nodes.add(to)

    if not seen_nodes:
        return "flowchart LR\n  A[No internal relationships detected]"

    # Build id -> display label mapping
    def node_id(name: str) -> str:
        return re.sub(r"[^A-Za-z0-9_]", "_", name)

    def node_label(name: str) -> str:
        # Use last path component or class name as display label
        label = name.split("/")[-1].split(".")[0]
        return label or name

    lines = ["flowchart LR"]

    # Define nodes with display labels
    defined: set[str] = set()
    for name in sorted(seen_nodes):
        nid = node_id(name)
        if nid not in defined:
            label = node_label(name)
            lines.append(f'  {nid}["{label}"]')
            defined.add(nid)

    lines.append("")

    # Import edges (limit 25)
    for frm, to in import_edges[:25]:
        lines.append(f"  {node_id(frm)} -->|imports| {node_id(to)}")

    # Call edges (limit 15)
    for frm, to in call_edges[:15]:
        lines.append(f"  {node_id(frm)} -.->|calls| {node_id(to)}")

    # Inheritance edges (limit 10)
    for child, parent in inherit_edges[:10]:
        lines.append(f"  {node_id(parent)} <|-- {node_id(child)} : inherits")

    lines.append("")

    # Style entry points in gold
    for ep in (entry_points or []):
        nid = node_id(ep)
        if nid in defined:
            lines.append(f"  style {nid} fill:#f4a700,stroke:#c47d00,color:#000")

    return "\n".join(lines)


def _build_class_hierarchy(rows: list[dict]) -> str:
    """classDiagram showing inheritance relationships."""
    inheritances: list[tuple[str, str]] = []

    for r in rows:
        if r.get("kind") == "inherits":
            frm = r.get("from_") or r.get("from") or ""
            to = r.get("to") or ""
            if frm and to:
                inheritances.append((_sanitise_class(frm), _sanitise_class(to)))

    if not inheritances:
        return "classDiagram\n  note \"No inheritance relationships detected\""

    lines = ["classDiagram"]
    for child, parent in inheritances[:20]:
        lines.append(f"  {parent} <|-- {child}")
    return "\n".join(lines)


# ── helpers ──────────────────────────────────────────────────────────

def _to_dict(row) -> dict:
    if isinstance(row, dict):
        return row
    try:
        return dict(row)
    except Exception:  # noqa: BLE001
        return {}


def _sanitise(name: str) -> str:
    """Convert a file path to a valid Mermaid node id."""
    # Replace non-alphanumeric characters
    s = re.sub(r"[^A-Za-z0-9_]", "_", name)
    # Ensure doesn't start with digit
    if s and s[0].isdigit():
        s = "_" + s
    return s or "unknown"


def _sanitise_class(name: str) -> str:
    """Strip fully-qualified prefix for class names."""
    return re.sub(r"[^A-Za-z0-9_]", "_", name.split(".")[-1]) or "Unknown"
