"""Tests for refactor_applier and --dry-run / --apply CLI flags."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from click.testing import CliRunner

from rekipedia.analysis.refactor_applier import (
    AUTO_FIXABLE,
    ApplyResult,
    apply_all,
    apply_smell,
)
from rekipedia.cli.refactor import refactor_cmd


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_py(tmp_path: Path) -> Path:
    """A minimal Python file with a private function (dead-code candidate)."""
    f = tmp_path / "sample.py"
    f.write_text(textwrap.dedent("""\
        def public_func():
            pass


        def _legacy_parse():
            pass
    """))
    return f


@pytest.fixture()
def tmp_large_py(tmp_path: Path) -> Path:
    """A Python file with >500 lines."""
    f = tmp_path / "big.py"
    lines = [f"# line {i}\n" for i in range(600)]
    f.write_text("".join(lines))
    return f


# ---------------------------------------------------------------------------
# Unit tests — apply_smell
# ---------------------------------------------------------------------------

class TestApplySmellDeadCode:
    def test_adds_comment_above_symbol(self, tmp_py: Path) -> None:
        smell = {
            "type": "dead_code",
            "file": str(tmp_py),
            "symbol": "_legacy_parse",
        }
        result = apply_smell(smell, dry_run=False)
        assert result.action == "comment_added"
        assert result.applied is True
        content = tmp_py.read_text()
        assert "# reki: dead-code (flagged " in content
        # comment should appear before the function definition
        lines = content.splitlines()
        marker_idx = next(i for i, l in enumerate(lines) if "# reki: dead-code" in l)
        def_idx = next(i for i, l in enumerate(lines) if "def _legacy_parse" in l)
        assert marker_idx == def_idx - 1

    def test_diff_is_non_empty(self, tmp_py: Path) -> None:
        smell = {
            "type": "dead_code",
            "file": str(tmp_py),
            "symbol": "_legacy_parse",
        }
        result = apply_smell(smell, dry_run=True)
        assert result.diff != ""

    def test_dry_run_does_not_modify_file(self, tmp_py: Path) -> None:
        original = tmp_py.read_text()
        smell = {
            "type": "dead_code",
            "file": str(tmp_py),
            "symbol": "_legacy_parse",
        }
        result = apply_smell(smell, dry_run=True)
        assert tmp_py.read_text() == original
        assert result.applied is False
        assert result.action == "comment_added"


class TestApplySmellLargeFile:
    def test_adds_split_suggestion(self, tmp_large_py: Path) -> None:
        smell = {
            "type": "large_file",
            "file": str(tmp_large_py),
            "symbol": tmp_large_py.name,
            "metrics": {"line_count": 600},
        }
        result = apply_smell(smell, dry_run=False)
        assert result.action == "stub_created"
        assert result.applied is True
        content = tmp_large_py.read_text()
        assert "# reki: consider splitting into" in content

    def test_dry_run_does_not_modify_file(self, tmp_large_py: Path) -> None:
        original = tmp_large_py.read_text()
        smell = {
            "type": "large_file",
            "file": str(tmp_large_py),
            "symbol": tmp_large_py.name,
            "metrics": {"line_count": 600},
        }
        result = apply_smell(smell, dry_run=True)
        assert tmp_large_py.read_text() == original
        assert result.applied is False


class TestApplySmellSkipped:
    def test_non_auto_fixable_is_skipped(self) -> None:
        smell = {"type": "god_class", "file": "/no/such/file.py", "symbol": "MyGodClass"}
        result = apply_smell(smell)
        assert result.action == "skipped"
        assert result.applied is False

    def test_missing_file_returns_skipped(self, tmp_path: Path) -> None:
        smell = {
            "type": "dead_code",
            "file": str(tmp_path / "nonexistent.py"),
            "symbol": "_foo",
        }
        result = apply_smell(smell)
        assert result.action == "skipped"


# ---------------------------------------------------------------------------
# Unit tests — apply_all
# ---------------------------------------------------------------------------

class TestApplyAll:
    def test_skips_non_auto_fixable(self) -> None:
        smells = [
            {"type": "god_class", "file": "/no/such.py", "symbol": "X"},
            {"type": "circular_dep", "file": "/no/such.py", "symbol": "Y"},
        ]
        results = apply_all(smells)
        assert all(r.action == "skipped" for r in results)

    def test_processes_mixed_smells(self, tmp_py: Path, tmp_large_py: Path) -> None:
        smells = [
            {
                "type": "dead_code",
                "file": str(tmp_py),
                "symbol": "_legacy_parse",
            },
            {
                "type": "large_file",
                "file": str(tmp_large_py),
                "symbol": tmp_large_py.name,
                "metrics": {"line_count": 600},
            },
            {"type": "god_class", "file": "/no/such.py", "symbol": "G"},
        ]
        results = apply_all(smells, dry_run=True)
        assert len(results) == 3
        assert results[0].action == "comment_added"
        assert results[1].action == "stub_created"
        assert results[2].action == "skipped"
        # dry_run → no writes
        assert all(not r.applied for r in results)

    def test_auto_fixable_set(self) -> None:
        assert "dead_code" in AUTO_FIXABLE
        assert "large_file" in AUTO_FIXABLE


# ---------------------------------------------------------------------------
# CLI integration tests
# ---------------------------------------------------------------------------

class TestCLIDryRun:
    def test_dry_run_exits_0(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(refactor_cmd, [str(tmp_path), "--dry-run"])
        assert result.exit_code == 0, result.output

    def test_dry_run_prints_preview(self, tmp_path: Path) -> None:
        # Create a large file so there is something to preview
        big = tmp_path / "big.py"
        big.write_text("\n" * 600)
        runner = CliRunner()
        result = runner.invoke(refactor_cmd, [str(tmp_path), "--dry-run"])
        assert result.exit_code == 0
        assert "DRY RUN" in result.output

    def test_dry_run_no_file_writes(self, tmp_path: Path) -> None:
        small = tmp_path / "small.py"
        small.write_text("def _dead(): pass\n")
        before = small.read_text()
        runner = CliRunner()
        runner.invoke(refactor_cmd, [str(tmp_path), "--dry-run"])
        assert small.read_text() == before


class TestCLIApplyDryRun:
    def test_apply_dry_run_exits_0(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(refactor_cmd, [str(tmp_path), "--apply", "--dry-run"])
        assert result.exit_code == 0, result.output

    def test_apply_dry_run_prints_apply_label(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(refactor_cmd, [str(tmp_path), "--apply", "--dry-run"])
        assert "DRY RUN" in result.output
        assert "--apply" in result.output

    def test_apply_dry_run_no_file_writes(self, tmp_path: Path) -> None:
        f = tmp_path / "sample.py"
        f.write_text("def _unused(): pass\n")
        before = f.read_text()
        runner = CliRunner()
        runner.invoke(refactor_cmd, [str(tmp_path), "--apply", "--dry-run"])
        assert f.read_text() == before
