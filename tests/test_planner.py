"""Tests for Planner keywords field (issue #54)."""
from __future__ import annotations


def test_keywords_in_planner_prompt():
    """The planner system prompt should include the keywords field description."""
    from rekipedia.synthesis.planner import _SYSTEM_PROMPT
    assert "keywords" in _SYSTEM_PROMPT
    assert "keywords field" in _SYSTEM_PROMPT


def test_keywords_allowed_in_page_builder():
    """keywords should be in _ALLOWED_FRONTMATTER_KEYS."""
    from rekipedia.synthesis.page_builder import _ALLOWED_FRONTMATTER_KEYS
    assert "keywords" in _ALLOWED_FRONTMATTER_KEYS


def test_planner_parse_keywords_from_llm_response():
    """Planner should handle LLM response with keywords field."""
    from rekipedia.synthesis.planner import WikiPlan

    plan_data = {
        "pages": [
            {
                "slug": "auth-module",
                "title": "Authentication Module",
                "priority": 1,
                "importance": 80,
                "focus": "Auth details",
                "required_data": ["symbols"],
                "tags": ["auth"],
                "keywords": ["jwt", "token", "authenticate", "verify_credentials", "AuthService"],
            }
        ],
        "sections": [],
        "nav_order": ["auth-module"],
        "index_slug": "auth-module",
    }

    plan = WikiPlan(plan_data)
    pages = plan.pages
    assert len(pages) == 1
    page = pages[0]
    # Keywords should be preserved in the raw plan data
    assert plan_data["pages"][0]["keywords"] == ["jwt", "token", "authenticate", "verify_credentials", "AuthService"]
