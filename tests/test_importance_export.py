"""Tests for page importance, export command, and embed provider."""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from rekipedia.models.contracts import LLMConfig
from rekipedia.synthesis.planner import WikiPlan


# ---------------------------------------------------------------------------
# WikiPlan importance / nav_order sorting
# ---------------------------------------------------------------------------

def _make_plan(pages: list[dict], nav_order: list[str] | None = None) -> WikiPlan:
    data = {"pages": pages, "sections": [], "index_slug": "index"}
    if nav_order is not None:
        data["nav_order"] = nav_order
    return WikiPlan(data)


def test_wiki_plan_sorts_by_importance_when_no_nav_order() -> None:
    plan = _make_plan([
        {"slug": "internals", "priority": 3, "importance": 40},
        {"slug": "index", "priority": 1, "importance": 100},
        {"slug": "architecture", "priority": 2, "importance": 85},
    ])
    assert plan.nav_order == ["index", "architecture", "internals"]


def test_wiki_plan_respects_explicit_nav_order() -> None:
    pages = [
        {"slug": "a", "priority": 1, "importance": 90},
        {"slug": "b", "priority": 2, "importance": 50},
        {"slug": "c", "priority": 3, "importance": 70},
    ]
    plan = _make_plan(pages, nav_order=["b", "c", "a"])
    assert plan.nav_order == ["b", "c", "a"]


def test_wiki_plan_appends_missing_slugs_after_nav_order() -> None:
    pages = [
        {"slug": "index", "priority": 1, "importance": 100},
        {"slug": "extra", "priority": 5, "importance": 30},
    ]
    plan = _make_plan(pages, nav_order=["index"])
    assert plan.nav_order[0] == "index"
    assert "extra" in plan.nav_order


def test_wiki_plan_importance_defaults_to_50() -> None:
    # Pages without importance field fall back gracefully
    plan = _make_plan([
        {"slug": "a", "priority": 1},
        {"slug": "b", "priority": 2, "importance": 80},
    ])
    assert plan.nav_order[0] == "b"  # higher importance first


# ---------------------------------------------------------------------------
# LLMConfig embed fields
# ---------------------------------------------------------------------------

def test_llm_config_embed_fields() -> None:
    cfg = LLMConfig(embed_model="text-embedding-3-small", embed_provider="openai")
    assert cfg.embed_model == "text-embedding-3-small"
    assert cfg.embed_provider == "openai"


def test_llm_config_embed_fields_default_empty() -> None:
    cfg = LLMConfig()
    assert cfg.embed_model == ""
    assert cfg.embed_provider == ""


def test_embed_pipeline_uses_provider_prefix(tmp_path: Path) -> None:
    from rekipedia.rag.embedder import EmbedPipeline

    cfg = LLMConfig(embed_model="nomic-embed-text", embed_provider="ollama")
    pipe = EmbedPipeline(tmp_path / ".rekipedia", cfg)
    assert pipe._model == "ollama/nomic-embed-text"


def test_embed_pipeline_no_prefix_when_slash_in_model(tmp_path: Path) -> None:
    from rekipedia.rag.embedder import EmbedPipeline
    import os
    os.environ.pop("REKIPEDIA_EMBED_MODEL", None)
    os.environ.pop("REKIPEDIA_EMBED_PROVIDER", None)
    cfg = LLMConfig(embed_model="openai/text-embedding-3-small", embed_provider="openai")
    pipe = EmbedPipeline(tmp_path / ".rekipedia", cfg)
    # Already has slash — should NOT double-prefix
    assert pipe._model == "openai/text-embedding-3-small"


# ---------------------------------------------------------------------------
# export command (md + zip)
# ---------------------------------------------------------------------------

def _make_wiki_dir(tmp_path: Path, pages: list[tuple[str, str]]) -> tuple[Path, Path]:
    """Create a minimal .rekipedia/ layout with wiki pages."""
    out_dir = tmp_path / ".rekipedia"
    wiki_dir = out_dir / "wiki"
    wiki_dir.mkdir(parents=True)

    for slug, content in pages:
        (wiki_dir / f"{slug}.md").write_text(content, encoding="utf-8")

    # Write a minimal manifest
    exports_dir = out_dir / "exports"
    exports_dir.mkdir()
    manifest = {
        "run_id": "test-run",
        "generated_at": "2025-01-01T00:00:00+00:00",
        "file_count": 5,
        "symbol_count": 10,
        "relationship_count": 3,
        "nav_order": [s for s, _ in pages],
        "pages": [
            {"slug": s, "title": s.title(), "importance": 80 - i * 10, "section": "core"}
            for i, (s, _) in enumerate(pages)
        ],
        "diagrams": [],
        "risks": [],
        "build_commands": [],
        "test_commands": [],
    }
    (exports_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return out_dir, wiki_dir


def test_export_md(tmp_path: Path) -> None:
    from click.testing import CliRunner
    from rekipedia.cli.export import export_cmd

    pages = [("index", "# Index\n\nWelcome."), ("architecture", "# Architecture\n\nDesign.")]
    out_dir, _ = _make_wiki_dir(tmp_path, pages)

    dest = tmp_path / "out.md"
    runner = CliRunner()
    result = runner.invoke(export_cmd, [
        str(tmp_path), "--output-dir", str(out_dir),
        "--format", "md", "--output", str(dest),
    ])
    assert result.exit_code == 0, result.output
    assert dest.exists()
    content = dest.read_text(encoding="utf-8")
    assert "# Table of Contents" in content
    assert "index" in content
    assert "architecture" in content
    assert "importance: **80**" in content


def test_export_zip(tmp_path: Path) -> None:
    from click.testing import CliRunner
    from rekipedia.cli.export import export_cmd

    pages = [("index", "# Index\n\nHello."), ("core", "# Core\n\nDetails.")]
    out_dir, _ = _make_wiki_dir(tmp_path, pages)

    dest = tmp_path / "wiki.zip"
    runner = CliRunner()
    result = runner.invoke(export_cmd, [
        str(tmp_path), "--output-dir", str(out_dir),
        "--format", "zip", "--output", str(dest),
    ])
    assert result.exit_code == 0, result.output
    assert dest.exists()
    with zipfile.ZipFile(dest) as zf:
        names = zf.namelist()
    assert "wiki/index.md" in names
    assert "wiki/core.md" in names
    assert "manifest.json" in names
    assert "README.md" in names


def test_export_fails_gracefully_without_wiki(tmp_path: Path) -> None:
    from click.testing import CliRunner
    from rekipedia.cli.export import export_cmd

    runner = CliRunner()
    result = runner.invoke(export_cmd, [str(tmp_path)])
    assert result.exit_code != 0
