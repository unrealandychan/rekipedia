"""Tests for the `rekipedia context` CLI command."""
from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from rekipedia.cli.context import context_cmd

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_wiki(tmp_path: Path, pages: dict[str, str] | None = None) -> Path:
    """Create a minimal .rekipedia/wiki structure under tmp_path."""
    wiki_dir = tmp_path / ".rekipedia" / "wiki"
    wiki_dir.mkdir(parents=True, exist_ok=True)
    for name, content in (pages or {}).items():
        (wiki_dir / name).write_text(content, encoding="utf-8")
    return tmp_path


def _make_symbols(tmp_path: Path, symbols: list[dict]) -> None:
    exports_dir = tmp_path / ".rekipedia" / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)
    (exports_dir / "symbols.json").write_text(json.dumps(symbols), encoding="utf-8")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_context_creates_output_file(tmp_path):
    """Running context_cmd should create the output file."""
    _make_wiki(tmp_path, {"overview.md": "# Overview\n\nThis is the overview page."})
    runner = CliRunner()
    output = tmp_path / "out.md"
    result = runner.invoke(
        context_cmd,
        ["--repo", str(tmp_path), "--output", str(output)],
    )
    assert result.exit_code == 0, result.output
    assert output.exists()
    assert output.stat().st_size > 0


def test_context_includes_frontmatter(tmp_path):
    """Output file must start with YAML frontmatter."""
    _make_wiki(tmp_path)
    runner = CliRunner()
    output = tmp_path / "ctx.md"
    result = runner.invoke(
        context_cmd,
        ["--repo", str(tmp_path), "--output", str(output)],
    )
    assert result.exit_code == 0, result.output
    text = output.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    assert "generated_at:" in text
    assert "source: rekipedia context" in text


def test_context_includes_wiki_content(tmp_path):
    """Wiki page content must appear in the output."""
    _make_wiki(tmp_path, {
        "architecture.md": "# Architecture\n\nThe system uses a layered design.",
    })
    runner = CliRunner()
    output = tmp_path / "ctx.md"
    result = runner.invoke(
        context_cmd,
        ["--repo", str(tmp_path), "--output", str(output)],
    )
    assert result.exit_code == 0, result.output
    text = output.read_text(encoding="utf-8")
    assert "layered design" in text
    assert "Architecture" in text


def test_context_respects_max_tokens(tmp_path):
    """Output must be truncated to fit within --max-tokens budget."""
    # Create a large wiki page
    big_content = "word " * 10_000  # ~50 000 chars
    _make_wiki(tmp_path, {"big.md": big_content})
    runner = CliRunner()
    output = tmp_path / "ctx.md"
    max_tokens = 500
    result = runner.invoke(
        context_cmd,
        ["--repo", str(tmp_path), "--output", str(output), "--max-tokens", str(max_tokens)],
    )
    assert result.exit_code == 0, result.output
    text = output.read_text(encoding="utf-8")
    # Output should be at most max_tokens * 4 chars (plus a short truncation notice)
    assert len(text) <= max_tokens * 4 + 300  # small slack for the truncation notice
    assert "truncated" in text.lower()


def test_context_empty_wiki_still_writes(tmp_path):
    """Even with no wiki pages, the command should succeed and write a file."""
    # No wiki pages at all (but directory exists)
    wiki_dir = tmp_path / ".rekipedia" / "wiki"
    wiki_dir.mkdir(parents=True, exist_ok=True)
    runner = CliRunner()
    output = tmp_path / "ctx.md"
    result = runner.invoke(
        context_cmd,
        ["--repo", str(tmp_path), "--output", str(output)],
    )
    assert result.exit_code == 0, result.output
    assert output.exists()
    text = output.read_text(encoding="utf-8")
    # Should indicate no pages found
    assert "No wiki pages found" in text or "## Wiki Pages" in text


def test_context_includes_symbols(tmp_path):
    """Symbols from exports/symbols.json should appear in the output."""
    _make_wiki(tmp_path)
    _make_symbols(tmp_path, [
        {"name": "MyClass", "kind": "class", "file": "src/myclass.py", "docstring": "A great class."},
    ])
    runner = CliRunner()
    output = tmp_path / "ctx.md"
    result = runner.invoke(
        context_cmd,
        ["--repo", str(tmp_path), "--output", str(output)],
    )
    assert result.exit_code == 0, result.output
    text = output.read_text(encoding="utf-8")
    assert "MyClass" in text


def test_context_no_rekipedia_dir(tmp_path):
    """When .rekipedia/ does not exist, command still writes a placeholder file."""
    runner = CliRunner()
    output = tmp_path / "ctx.md"
    result = runner.invoke(
        context_cmd,
        ["--repo", str(tmp_path), "--output", str(output)],
    )
    # Should not crash — it should gracefully handle missing dirs
    assert result.exit_code == 0, result.output
    assert output.exists()
