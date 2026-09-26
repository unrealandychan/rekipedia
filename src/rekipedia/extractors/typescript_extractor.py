"""TypeScript/JavaScript extractor using Tree-sitter AST parsing with robust fallback."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from rekipedia.extractors.base_tree_sitter import BaseTreeSitterExtractor
from rekipedia.extractors.route_patterns import TYPESCRIPT_ROUTE_PATTERNS, extract_routes_from_line
from rekipedia.models.contracts import AnalysisResult, RationaleNote, Relationship, Symbol

_TS_SUFFIXES = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}
_RE_RATIONALE = re.compile(r"//\s*(NOTE|IMPORTANT|HACK|WHY|TODO):\s*(.*)", re.IGNORECASE)

# Tree-sitter parsers for TS and TSX
_PARSER_TS: Any = None
_PARSER_TSX: Any = None

try:
    import tree_sitter_typescript as tst
    from tree_sitter import Language, Parser

    _TS_LANG = Language(tst.language_typescript())
    _TSX_LANG = Language(tst.language_tsx())
    _PARSER_TS = Parser(_TS_LANG)
    _PARSER_TSX = Parser(_TSX_LANG)
except Exception:
    pass


class TypeScriptExtractor(BaseTreeSitterExtractor):
    """Extract symbols and relationships from TypeScript and JavaScript source files using Tree-sitter."""

    def can_handle(self, path: Path) -> bool:
        return path.suffix.lower() in _TS_SUFFIXES

    def extract(self, path: Path, repo_root: Path) -> AnalysisResult:
        rel = str(path.relative_to(repo_root))
        try:
            src_bytes = path.read_bytes()
            source = src_bytes.decode("utf-8", errors="replace")
        except OSError:
            return AnalysisResult(shard_id=rel, files_seen=[rel], entry_points=[])

        symbols: list[Symbol] = []
        relationships: list[Relationship] = []
        rationale_notes: list[RationaleNote] = []

        # ── Rationale notes ───────────────────────────────────────────
        for lineno, line in enumerate(source.splitlines(), start=1):
            m = _RE_RATIONALE.search(line)
            if m:
                tag = m.group(1).upper()
                rationale_notes.append(
                    RationaleNote(tag=tag, content=m.group(2).strip(), file=rel, line=lineno)  # type: ignore[arg-type]
                )

        # Select parser: TSX parser for .tsx/.jsx, TS parser for .ts/.js
        is_jsx = path.suffix.lower() in {".tsx", ".jsx"}
        parser = (_PARSER_TSX if is_jsx else _PARSER_TS)

        if parser is not None:
            self._extract_with_tree_sitter(parser, src_bytes, rel, symbols, relationships)
        else:
            self._extract_with_regex(source, rel, symbols, relationships)

        # ── Entry points ──────────────────────────────────────────────
        entry_points: list[str] = []
        if path.name in {
            "index.ts", "index.tsx", "index.js", "index.jsx",
            "main.ts", "main.tsx", "main.js", "main.jsx",
            "server.ts", "server.js", "app.ts", "app.js",
        }:
            entry_points = [rel]

        # ── Route extraction (Express / Koa / NestJS) ─────────────────
        existing_names = {s.name for s in symbols}
        for lineno, line in enumerate(source.splitlines(), start=1):
            for route_name, _fw in extract_routes_from_line(line, TYPESCRIPT_ROUTE_PATTERNS):
                if route_name not in existing_names:
                    symbols.append(
                        Symbol(
                            name=route_name,
                            kind="route",
                            file=rel,
                            line_start=lineno,
                            line_end=lineno,
                            docstring=f"HTTP endpoint detected via {_fw} pattern",
                        )
                    )
                    existing_names.add(route_name)

        # ── Next.js API route: infer from file path ───────────────────
        if "pages/api/" in rel or "app/api/" in rel:
            route_path = _nextjs_route_path(rel)
            if route_path and route_path not in existing_names:
                symbols.append(
                    Symbol(
                        name=route_path,
                        kind="route",
                        file=rel,
                        line_start=1,
                        signature=f"route: {route_path}",
                    )
                )

        return AnalysisResult(
            shard_id=rel,
            files_seen=[rel],
            entry_points=entry_points,
            symbols=symbols,
            relationships=relationships,
            rationale_notes=rationale_notes,
        )

    def _extract_with_tree_sitter(
        self,
        parser: Any,
        src_bytes: bytes,
        rel: str,
        symbols: list[Symbol],
        relationships: list[Relationship],
    ) -> None:
        tree = parser.parse(src_bytes)
        root = tree.root_node

        seen_imports: set[str] = set()

        for node in self.walk(root):
            ntype = node.type

            # ── 1. Import statements ───────────────────────────────────
            if ntype == "import_statement":
                # Find source string literal
                for child in node.named_children:
                    if child.type == "string":
                        raw_target = self.node_text(child, src_bytes).strip("\"'")
                        if raw_target and raw_target not in seen_imports:
                            seen_imports.add(raw_target)
                            relationships.append(
                                Relationship.model_validate(
                                    {
                                        "from": rel,
                                        "to": raw_target,
                                        "kind": "import",
                                        "file": rel,
                                        "confidence": 1.0,
                                        "evidence_tag": "EXTRACTED",
                                    }
                                )
                            )

            # ── 2. CommonJS require() calls ────────────────────────────
            elif ntype == "call_expression":
                fn_node = node.child_by_field_name("function") or (node.named_children[0] if node.named_children else None)
                if fn_node and self.node_text(fn_node, src_bytes) == "require":
                    args = node.child_by_field_name("arguments") or (node.named_children[1] if len(node.named_children) > 1 else None)
                    if args and args.named_children:
                        first_arg = args.named_children[0]
                        if first_arg.type == "string":
                            raw_target = self.node_text(first_arg, src_bytes).strip("\"'")
                            if raw_target and raw_target not in seen_imports:
                                seen_imports.add(raw_target)
                                relationships.append(
                                    Relationship.model_validate(
                                        {
                                            "from": rel,
                                            "to": raw_target,
                                            "kind": "import",
                                            "file": rel,
                                            "confidence": 1.0,
                                            "evidence_tag": "EXTRACTED",
                                        }
                                    )
                                )

            # ── 3. Class declarations & inheritance ────────────────────
            elif ntype in ("class_declaration", "class"):
                name_node = node.child_by_field_name("name")
                if not name_node:
                    for c in node.named_children:
                        if c.type in ("type_identifier", "identifier"):
                            name_node = c
                            break
                if name_node:
                    class_name = self.node_text(name_node, src_bytes)
                    symbols.append(
                        Symbol(
                            name=class_name,
                            kind="class",
                            file=rel,
                            line_start=self.line_start(node),
                            line_end=self.line_end(node),
                        )
                    )

                    # Inheritance: extends clause
                    heritage = node.child_by_field_name("heritage") or next(
                        (c for c in node.named_children if c.type in ("class_heritage", "extends_clause")),
                        None,
                    )
                    if heritage:
                        for hchild in self.walk(heritage):
                            if hchild.type in ("identifier", "type_identifier"):
                                base_name = self.node_text(hchild, src_bytes)
                                if base_name and base_name != class_name and base_name != "extends":
                                    relationships.append(
                                        Relationship.model_validate(
                                            {
                                                "from": class_name,
                                                "to": base_name,
                                                "kind": "inherits",
                                                "file": rel,
                                                "confidence": 1.0,
                                                "evidence_tag": "EXTRACTED",
                                            }
                                        )
                                    )
                                    break

            # ── 4. Functions ───────────────────────────────────────────
            elif ntype in ("function_declaration", "generator_function_declaration"):
                name_node = node.child_by_field_name("name")
                if name_node:
                    func_name = self.node_text(name_node, src_bytes)
                    params_node = node.child_by_field_name("parameters")
                    sig = f"{func_name}{self.node_text(params_node, src_bytes) if params_node else '()'}"
                    symbols.append(
                        Symbol(
                            name=func_name,
                            kind="function",
                            file=rel,
                            line_start=self.line_start(node),
                            line_end=self.line_end(node),
                            signature=sig,
                        )
                    )

            # Arrow functions / const fn = () => {}
            elif ntype == "variable_declarator":
                name_node = node.child_by_field_name("name")
                val_node = node.child_by_field_name("value")
                if name_node and val_node and val_node.type in ("arrow_function", "function_expression"):
                    fn_name = self.node_text(name_node, src_bytes)
                    params_node = val_node.child_by_field_name("parameters")
                    sig = f"{fn_name}{self.node_text(params_node, src_bytes) if params_node else '()'}"
                    symbols.append(
                        Symbol(
                            name=fn_name,
                            kind="function",
                            file=rel,
                            line_start=self.line_start(node),
                            line_end=self.line_end(node),
                            signature=sig,
                        )
                    )

            # ── 5. Interfaces ──────────────────────────────────────────
            elif ntype == "interface_declaration":
                name_node = node.child_by_field_name("name")
                if name_node:
                    iface_name = self.node_text(name_node, src_bytes)
                    symbols.append(
                        Symbol(
                            name=iface_name,
                            kind="interface",
                            file=rel,
                            line_start=self.line_start(node),
                            line_end=self.line_end(node),
                        )
                    )

            # ── 6. Type aliases ────────────────────────────────────────
            elif ntype == "type_alias_declaration":
                name_node = node.child_by_field_name("name")
                if name_node:
                    type_name = self.node_text(name_node, src_bytes)
                    symbols.append(
                        Symbol(
                            name=type_name,
                            kind="type",
                            file=rel,
                            line_start=self.line_start(node),
                            line_end=self.line_end(node),
                        )
                    )

    def _extract_with_regex(
        self,
        source: str,
        rel: str,
        symbols: list[Symbol],
        relationships: list[Relationship],
    ) -> None:
        """Fallback regex extraction if tree-sitter parser is not available."""
        clean = re.sub(r"//[^\n]*", "", source)

        _RE_IMPORT = re.compile(
            r"""(?:import\s+(?:.*?\s+from\s+)?|require\s*\()\s*['"]([^'"]+)['"]""",
            re.MULTILINE,
        )
        _RE_EXPORT_FUNC = re.compile(
            r"""(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(([^)]*)\)""",
            re.MULTILINE,
        )
        _RE_ARROW_FUNC = re.compile(
            r"""(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\(([^)]*)\)\s*=>""",
            re.MULTILINE,
        )
        _RE_CLASS = re.compile(
            r"""(?:export\s+)?(?:abstract\s+)?class\s+(\w+)(?:\s+extends\s+(\w+))?""",
            re.MULTILINE,
        )
        _RE_INTERFACE = re.compile(r"""(?:export\s+)?interface\s+(\w+)""", re.MULTILINE)
        _RE_TYPE = re.compile(r"""(?:export\s+)?type\s+(\w+)\s*=""", re.MULTILINE)

        def _line_of(text: str, offset: int) -> int:
            return text[:offset].count("\n") + 1

        for m in _RE_IMPORT.finditer(clean):
            relationships.append(
                Relationship.model_validate(
                    {"from": rel, "to": m.group(1), "kind": "import", "file": rel,
                     "confidence": 1.0, "evidence_tag": "EXTRACTED"}
                )
            )

        for m in _RE_EXPORT_FUNC.finditer(clean):
            symbols.append(
                Symbol(
                    name=m.group(1),
                    kind="function",
                    file=rel,
                    line_start=_line_of(source, m.start()),
                    signature=f"{m.group(1)}({m.group(2).strip()})",
                )
            )
        for m in _RE_ARROW_FUNC.finditer(clean):
            symbols.append(
                Symbol(
                    name=m.group(1),
                    kind="function",
                    file=rel,
                    line_start=_line_of(source, m.start()),
                    signature=f"{m.group(1)}({m.group(2).strip()})",
                )
            )

        for m in _RE_CLASS.finditer(clean):
            symbols.append(
                Symbol(name=m.group(1), kind="class", file=rel, line_start=_line_of(source, m.start()))
            )
            if m.group(2):
                relationships.append(
                    Relationship.model_validate(
                        {"from": m.group(1), "to": m.group(2), "kind": "inherits", "file": rel,
                         "confidence": 1.0, "evidence_tag": "EXTRACTED"}
                    )
                )

        for m in _RE_INTERFACE.finditer(clean):
            symbols.append(Symbol(name=m.group(1), kind="interface", file=rel, line_start=_line_of(source, m.start())))
        for m in _RE_TYPE.finditer(clean):
            symbols.append(Symbol(name=m.group(1), kind="type", file=rel, line_start=_line_of(source, m.start())))


def _nextjs_route_path(rel: str) -> str:
    """Convert a Next.js file path to an API route path."""
    path = rel
    for prefix in ("src/", "app/", "pages/"):
        if path.startswith(prefix):
            path = path[len(prefix):]
            break
    path = re.sub(r"\.[jt]sx?$", "", path)
    path = re.sub(r"/(index|route)$", "", path)
    path = re.sub(r"\[([^\]]+)\]", r"{\1}", path)
    if not path.startswith("/"):
        path = "/" + path
    return path
