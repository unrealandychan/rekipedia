"""Go source extractor using tree-sitter."""
# Copyright 2026 Eddie Chan. All rights reserved.
from __future__ import annotations

from pathlib import Path

import tree_sitter_go as tsg
from tree_sitter import Language, Parser

from rekipedia.extractors.base import BaseExtractor
from rekipedia.models.contracts import AnalysisResult, Relationship, Symbol

_GO_LANG = Language(tsg.language())
_PARSER = Parser(_GO_LANG)


def _node_text(node: object, src: bytes) -> str:
    """Return the decoded text of a tree-sitter node."""
    n = node  # type: ignore[assignment]
    return src[n.start_byte : n.end_byte].decode("utf-8", errors="replace")

def _walk(node: object):  # type: ignore[override]
    """Yield all descendant nodes (depth-first)."""
    stack = list(getattr(node, "named_children", []))
    while stack:
        cur = stack.pop(0)
        yield cur
        stack = list(getattr(cur, "named_children", [])) + stack


class GoExtractor(BaseExtractor):
    """Extract symbols and relationships from Go source files."""

    def can_handle(self, path: Path) -> bool:
        return path.suffix.lower() == ".go"

    def extract(self, path: Path, repo_root: Path) -> AnalysisResult:
        rel = str(path.relative_to(repo_root))
        try:
            src_bytes = path.read_bytes()
        except OSError:
            return AnalysisResult(shard_id=rel, files_seen=[rel], entry_points=[])

        tree = _PARSER.parse(src_bytes)
        root = tree.root_node

        symbols: list[Symbol] = []
        relationships: list[Relationship] = []
        entry_points: list[str] = []
        has_main_func = False

        for node in _walk(root):
            ntype = node.type  # type: ignore[attr-defined]

            # ── imports ──────────────────────────────────────────────────
            if ntype == "import_spec":
                # The import path is an interpreted_string_literal child
                for child in node.named_children:  # type: ignore[attr-defined]
                    if child.type in ("interpreted_string_literal",):
                        # strip quotes from the string content
                        raw = _node_text(child, src_bytes).strip('"').strip("'")
                        relationships.append(
                            Relationship.model_validate(
                                {"from": rel, "to": raw, "kind": "import",
                                 "file": rel, "confidence": 1.0, "evidence_tag": "EXTRACTED"}
                            )
                        )

            # ── functions ────────────────────────────────────────────────
            elif ntype == "function_declaration":
                name_node = node.child_by_field_name("name")  # type: ignore[attr-defined]
                if name_node is None:
                    # Fallback: first identifier child
                    for child in node.named_children:  # type: ignore[attr-defined]
                        if child.type == "identifier":
                            name_node = child
                            break
                if name_node is not None:
                    fname = _node_text(name_node, src_bytes)
                    start_line = node.start_point[0] + 1  # type: ignore[attr-defined]
                    end_line = node.end_point[0] + 1  # type: ignore[attr-defined]
                    symbols.append(
                        Symbol(
                            name=fname,
                            kind="function",
                            file=rel,
                            line_start=start_line,
                            line_end=end_line,
                        )
                    )
                    if fname == "main":
                        has_main_func = True

            # ── method declarations ───────────────────────────────────────
            elif ntype == "method_declaration":
                name_node = node.child_by_field_name("name")  # type: ignore[attr-defined]
                recv_node = node.child_by_field_name("receiver")  # type: ignore[attr-defined]
                if name_node is not None:
                    fname = _node_text(name_node, src_bytes)
                    recv_str = _node_text(recv_node, src_bytes) if recv_node else ""
                    full_name = f"{recv_str.strip()}.{fname}" if recv_str else fname
                    symbols.append(
                        Symbol(
                            name=full_name,
                            kind="function",
                            file=rel,
                            line_start=node.start_point[0] + 1,  # type: ignore[attr-defined]
                            line_end=node.end_point[0] + 1,  # type: ignore[attr-defined]
                        )
                    )

            # ── structs ──────────────────────────────────────────────────
            elif ntype == "type_spec":
                name_node = node.child_by_field_name("name")  # type: ignore[attr-defined]
                type_node = node.child_by_field_name("type")  # type: ignore[attr-defined]
                if name_node is None:
                    for child in node.named_children:  # type: ignore[attr-defined]
                        if child.type == "type_identifier":
                            name_node = child
                            break
                if name_node is not None and type_node is not None:
                    tname = _node_text(name_node, src_bytes)
                    ttype = type_node.type  # type: ignore[attr-defined]
                    if ttype == "struct_type":
                        symbols.append(
                            Symbol(
                                name=tname,
                                kind="type",
                                file=rel,
                                line_start=node.start_point[0] + 1,  # type: ignore[attr-defined]
                                line_end=node.end_point[0] + 1,  # type: ignore[attr-defined]
                                signature=f"struct {tname}",
                            )
                        )
                        # Detect struct embedding — Go's form of inheritance/composition.
                        # An embedded field is a field_declaration with a type_identifier
                        # but no field_identifier (no explicit name).
                        for descendant in _walk(type_node):
                            if descendant.type == "field_declaration":  # type: ignore[attr-defined]
                                embedded_name = _extract_embedded_type(descendant, src_bytes)
                                if embedded_name:
                                    relationships.append(
                                        Relationship.model_validate(
                                            {
                                                "from": tname,
                                                "to": embedded_name,
                                                "kind": "inherits",
                                                "file": rel,
                                                "confidence": 1.0,
                                                "evidence_tag": "EXTRACTED",
                                            }
                                        )
                                    )
                    elif ttype == "interface_type":
                        symbols.append(
                            Symbol(
                                name=tname,
                                kind="interface",
                                file=rel,
                                line_start=node.start_point[0] + 1,  # type: ignore[attr-defined]
                                line_end=node.end_point[0] + 1,  # type: ignore[attr-defined]
                                signature=f"interface {tname}",
                            )
                        )

        # Detect entry point: package main + func main
        if has_main_func:
            entry_points = [rel]

        return AnalysisResult(
            shard_id=rel,
            files_seen=[rel],
            entry_points=entry_points,
            symbols=symbols,
            relationships=relationships,
        )


# ── helpers ──────────────────────────────────────────────────────────

def _extract_embedded_type(node: object, src: bytes) -> str:
    """Return the embedded type name from a field_declaration node, or '' if not embedded.

    In tree-sitter-go, an embedded (anonymous) field is a ``field_declaration``
    whose named children contain a ``type_identifier`` but no ``field_identifier``.
    Both direct embedding (``Animal``) and pointer embedding (``*Dog``) produce
    a single ``type_identifier`` named child; the pointer ``*`` is an unnamed
    child token.  Cross-package embeddings (e.g. ``pkg.Type``) produce a
    ``qualified_type_identifier`` child instead, which is also handled.
    """
    children = list(getattr(node, "named_children", []))
    child_types = {c.type for c in children}  # type: ignore[attr-defined]
    # A field with an explicit name always has a field_identifier child.
    if "field_identifier" in child_types:
        return ""
    for child in children:
        ctype = getattr(child, "type", "")
        if ctype in ("type_identifier", "qualified_type_identifier"):
            return _node_text(child, src)
    return ""
