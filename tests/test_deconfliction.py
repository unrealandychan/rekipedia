"""Tests for rekipedia.orchestrator.deconfliction."""
from __future__ import annotations

import pytest

from rekipedia.connectors import ExternalSource
from rekipedia.orchestrator.deconfliction import ConflictResult, DeconflictionEngine


def _make_source(
    source_id: str = "owner/repo#1",
    title: str = "",
    body: str = "",
    state: str = "open",
    source_type: str = "github_issue",
) -> ExternalSource:
    return ExternalSource(
        source_type=source_type,
        source_id=source_id,
        title=title,
        body=body,
        url=f"https://github.com/{source_id}",
        state=state,
    )


class TestDeconflictionEngine:
    def setup_method(self):
        self.engine = DeconflictionEngine()

    # ------------------------------------------------------------------
    # Rule a: stale_ticket
    # ------------------------------------------------------------------

    def test_stale_ticket_detected(self):
        """Closed ticket that mentions the symbol → stale_ticket conflict."""
        src = _make_source(
            source_id="owner/repo#42",
            title="Fix the payment_processor module",
            state="closed",
        )
        conflicts = self.engine.detect("payment_processor", "def payment_processor(): pass", [src])
        types = [c.conflict_type for c in conflicts]
        assert "stale_ticket" in types

    def test_stale_ticket_not_detected_for_open(self):
        """Open ticket that mentions symbol should NOT produce stale_ticket."""
        src = _make_source(
            source_id="owner/repo#43",
            title="Fix the payment_processor module",
            state="open",
        )
        conflicts = self.engine.detect("payment_processor", "def payment_processor(): pass", [src])
        types = [c.conflict_type for c in conflicts]
        assert "stale_ticket" not in types

    def test_stale_ticket_requires_symbol_in_source(self):
        """Closed ticket that does NOT mention the symbol → no stale_ticket."""
        src = _make_source(
            source_id="owner/repo#44",
            title="Unrelated bug fix",
            body="Fixes UI glitch",
            state="done",
        )
        conflicts = self.engine.detect("payment_processor", "def payment_processor(): pass", [src])
        types = [c.conflict_type for c in conflicts]
        assert "stale_ticket" not in types

    # ------------------------------------------------------------------
    # Rule b: todo_never_linked
    # ------------------------------------------------------------------

    def test_todo_never_linked_detected(self):
        """TODO in code but no external source references symbol."""
        src = _make_source(
            source_id="owner/repo#10",
            title="Improve UI performance",
            body="Nothing about auth here.",
            state="open",
        )
        code = "def auth_check():\n    # TODO: add rate limiting\n    pass"
        conflicts = self.engine.detect("auth_check", code, [src])
        types = [c.conflict_type for c in conflicts]
        assert "todo_never_linked" in types

    def test_todo_never_linked_not_triggered_when_linked(self):
        """TODO in code but external source DOES reference symbol → no todo_never_linked."""
        src = _make_source(
            source_id="owner/repo#11",
            title="auth_check rate limiting",
            body="We need to add rate limiting to auth_check",
            state="open",
        )
        code = "def auth_check():\n    # TODO: add rate limiting\n    pass"
        conflicts = self.engine.detect("auth_check", code, [src])
        types = [c.conflict_type for c in conflicts]
        assert "todo_never_linked" not in types

    def test_no_todo_no_conflict(self):
        """Clean code with no TODO/FIXME → no todo_never_linked."""
        src = _make_source(state="open")
        code = "def clean_func():\n    return 42"
        conflicts = self.engine.detect("clean_func", code, [src])
        types = [c.conflict_type for c in conflicts]
        assert "todo_never_linked" not in types

    # ------------------------------------------------------------------
    # Rule c: resolved_but_code_unchanged
    # ------------------------------------------------------------------

    def test_resolved_but_code_unchanged_detected(self):
        """Closed ticket says 'fixed', mentions a backtick pattern still in code."""
        src = _make_source(
            source_id="owner/repo#55",
            title="Fixed dangerous eval call",
            body="We fixed the `eval(user_input)` call in the handler.",
            state="resolved",
        )
        code = "def handler(user_input):\n    return eval(user_input)"
        conflicts = self.engine.detect("handler", code, [src])
        types = [c.conflict_type for c in conflicts]
        assert "resolved_but_code_unchanged" in types

    # ------------------------------------------------------------------
    # Empty external sources → no conflicts
    # ------------------------------------------------------------------

    def test_empty_sources_returns_no_conflicts(self):
        conflicts = self.engine.detect("my_func", "def my_func(): pass", [])
        assert conflicts == []

    # ------------------------------------------------------------------
    # ConflictResult dataclass sanity
    # ------------------------------------------------------------------

    def test_conflict_result_fields(self):
        c = ConflictResult(
            symbol="foo",
            conflict_type="stale_ticket",
            sources=["owner/repo#1"],
            summary="summary text",
        )
        assert c.symbol == "foo"
        assert c.conflict_type == "stale_ticket"
        assert c.sources == ["owner/repo#1"]
        assert c.summary == "summary text"
