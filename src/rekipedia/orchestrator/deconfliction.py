"""Multi-source deconfliction for rekipedia.

Detects stale or conflicting context when code and external tickets disagree.
Pure heuristic — no LLM calls, stdlib-only.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rekipedia.connectors import ExternalSource

_DONE_STATUSES = {"done", "closed", "completed", "resolved", "merged", "fixed"}
_FIXED_KEYWORDS = re.compile(r'\b(fix(?:ed|es)?|resolv(?:ed|es)?|close[sd]?)\b', re.IGNORECASE)
_TODO_PATTERN = re.compile(r'#\s*(TODO|FIXME)\b', re.IGNORECASE)


@dataclass
class ConflictResult:
    symbol: str
    conflict_type: str  # "stale_ticket" | "resolved_but_code_unchanged" | "todo_never_linked"
    sources: list[str] = field(default_factory=list)
    summary: str = ""


class DeconflictionEngine:
    """Heuristic engine that detects conflicts between code context and external sources."""

    def detect(
        self,
        symbol: str,
        code_context: str,
        external_sources: list[ExternalSource],
    ) -> list[ConflictResult]:
        """Return a list of detected conflicts (empty = no conflicts)."""
        if not external_sources:
            return []

        conflicts: list[ConflictResult] = []
        symbol_lower = symbol.lower()

        for src in external_sources:
            state = (src.state or "").lower().strip()
            is_closed = state in _DONE_STATUSES

            if not is_closed:
                continue

            src_id = src.source_id
            title_lower = (src.title or "").lower()
            body_lower = (src.body or "").lower()

            # Rule a: stale ticket — ticket is closed but symbol appears in code
            # with no recent activity implied by external source date
            if symbol_lower in title_lower or symbol_lower in body_lower:
                conflicts.append(ConflictResult(
                    symbol=symbol,
                    conflict_type="stale_ticket",
                    sources=[src_id],
                    summary=(
                        f"Ticket {src_id!r} is marked '{state}' but the symbol "
                        f"`{symbol}` still appears in code context. "
                        "The ticket may be stale or the fix was not fully applied."
                    ),
                ))

            # Rule c: resolved_but_code_unchanged — ticket says "fixed" and mentions
            # a pattern that still appears verbatim in code_context
            if _FIXED_KEYWORDS.search(src.title or "") or _FIXED_KEYWORDS.search(src.body or ""):
                # Extract a short candidate phrase from the ticket body (first non-trivial word sequence)
                phrases = re.findall(r'`([^`]+)`', src.body or "")
                for phrase in phrases[:3]:
                    if len(phrase) > 3 and phrase.lower() in code_context.lower():
                        conflicts.append(ConflictResult(
                            symbol=symbol,
                            conflict_type="resolved_but_code_unchanged",
                            sources=[src_id],
                            summary=(
                                f"Ticket {src_id!r} claims to have fixed/resolved something, "
                                f"but the pattern `{phrase}` mentioned in the ticket is still "
                                "present in the code context."
                            ),
                        ))
                        break

        # Rule b: TODO never linked — code has TODO/FIXME near symbol but no
        # external source references that symbol
        if _TODO_PATTERN.search(code_context):
            linked = any(
                symbol_lower in (src.title or "").lower() or
                symbol_lower in (src.body or "").lower()
                for src in external_sources
            )
            if not linked:
                conflicts.append(ConflictResult(
                    symbol=symbol,
                    conflict_type="todo_never_linked",
                    sources=[],
                    summary=(
                        f"The code near `{symbol}` contains a TODO/FIXME comment, "
                        "but no external ticket or issue references this symbol. "
                        "Consider creating a tracking issue."
                    ),
                ))

        return conflicts
