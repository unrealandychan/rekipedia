"""Tests for PageBuilder (LLM calls mocked)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from rekipedia.models.contracts import AnalysisResult, LLMConfig, Symbol
from rekipedia.synthesis.page_builder import PageBuilder, CANONICAL_PAGES


@pytest.fixture()
def sample_result():
    return AnalysisResult(
        shard_id="all",
        files_seen=["src/main.py", "src/utils.py"],
        entry_points=["src/main.py"],
        symbols=[
            Symbol(name="greet", kind="function", file="src/main.py", line_start=3),
            Symbol(name="add", kind="function", file="src/utils.py", line_start=1),
        ],
        build_commands=["python -m build"],
        test_commands=["pytest"],
        risks=[],
    )


def _make_fake_llm_response(slug: str) -> str:
    import json
    return json.dumps({
        "title": slug.replace("-", " ").title(),
        "summary": f"This is the {slug} page.",
        "key_concepts": ["concept1"],
        "symbols": [],
        "relationships": [],
        "risks": [],
        "build_commands": [],
        "test_commands": [],
        "mermaid_graph": "",
    })


def test_builds_all_canonical_pages(sample_result):
    with patch("rekipedia.synthesis.page_builder.LLMClient") as MockClient:
        mock_instance = MagicMock()
        mock_instance.call.side_effect = lambda prompt, system="": _make_fake_llm_response("index")
        MockClient.return_value = mock_instance

        builder = PageBuilder(LLMConfig())
        pages = builder.build(sample_result)

    assert set(pages.keys()) == set(CANONICAL_PAGES)


def test_each_page_has_title_and_content(sample_result):
    with patch("rekipedia.synthesis.page_builder.LLMClient") as MockClient:
        mock_instance = MagicMock()
        mock_instance.call.side_effect = lambda prompt, system="": _make_fake_llm_response("index")
        MockClient.return_value = mock_instance

        builder = PageBuilder(LLMConfig())
        pages = builder.build(sample_result)

    for slug, (title, content) in pages.items():
        assert isinstance(title, str) and title
        assert isinstance(content, str) and content


def test_page_has_yaml_frontmatter(sample_result):
    with patch("rekipedia.synthesis.page_builder.LLMClient") as MockClient:
        mock_instance = MagicMock()
        mock_instance.call.side_effect = lambda prompt, system="": _make_fake_llm_response("index")
        MockClient.return_value = mock_instance

        builder = PageBuilder(LLMConfig())
        pages = builder.build(sample_result)

    for slug, (title, content) in pages.items():
        assert content.startswith("---"), f"{slug} missing frontmatter"


def test_exclude_pages(sample_result):
    with patch("rekipedia.synthesis.page_builder.LLMClient") as MockClient:
        mock_instance = MagicMock()
        mock_instance.call.side_effect = lambda prompt, system="": _make_fake_llm_response("index")
        MockClient.return_value = mock_instance

        builder = PageBuilder(LLMConfig(), exclude_pages=["testing-strategy"])
        pages = builder.build(sample_result)

    assert "testing-strategy" not in pages


def test_pinned_page_not_overwritten(sample_result, tmp_path):
    wiki_dir = tmp_path / "wiki"
    wiki_dir.mkdir()
    pinned = wiki_dir / "index.md"
    pinned.write_text("---\nslug: index\npin: true\n---\n\n# My Custom Index\n\nPinned content.\n")

    with patch("rekipedia.synthesis.page_builder.LLMClient") as MockClient:
        mock_instance = MagicMock()
        mock_instance.call.return_value = _make_fake_llm_response("other")
        MockClient.return_value = mock_instance

        builder = PageBuilder(LLMConfig(), wiki_dir=wiki_dir)
        pages = builder.build(sample_result)

    assert "Pinned content." in pages["index"][1]


def test_llm_error_fallback(sample_result):
    with patch("rekipedia.synthesis.page_builder.LLMClient") as MockClient:
        mock_instance = MagicMock()
        mock_instance.call.side_effect = RuntimeError("LLM unavailable")
        MockClient.return_value = mock_instance

        builder = PageBuilder(LLMConfig())
        pages = builder.build(sample_result)

    # Should still produce all pages (with error placeholder)
    assert set(pages.keys()) == set(CANONICAL_PAGES)
    for slug, (title, content) in pages.items():
        assert "LLM synthesis failed" in content
