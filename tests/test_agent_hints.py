"""Tests for agent_hints module (issues #60, #61)."""
from __future__ import annotations

import json


def test_write_agent_hints_creates_files(tmp_path):
    from rekipedia.orchestrator.agent_hints import write_agent_hints
    written = write_agent_hints(tmp_path)
    assert len(written) == 3
    assert (tmp_path / "CLAUDE.md").exists()
    assert (tmp_path / "AGENTS.md").exists()
    assert (tmp_path / ".github" / "copilot-instructions.md").exists()
    content = (tmp_path / "CLAUDE.md").read_text()
    assert "reki ask" in content


def test_write_agent_hints_no_duplicate(tmp_path):
    from rekipedia.orchestrator.agent_hints import _MARKER, write_agent_hints
    write_agent_hints(tmp_path)
    write_agent_hints(tmp_path)  # second call should not duplicate
    content = (tmp_path / "CLAUDE.md").read_text()
    assert content.count(_MARKER) == 1


def test_write_agent_hints_appends_to_existing(tmp_path):
    from rekipedia.orchestrator.agent_hints import write_agent_hints
    claude_md = tmp_path / "CLAUDE.md"
    claude_md.write_text("# My Project\n\nSome existing content.\n")
    write_agent_hints(tmp_path)
    content = claude_md.read_text()
    assert "My Project" in content
    assert "reki ask" in content


def test_write_mcp_json_creates_file(tmp_path):
    from rekipedia.orchestrator.agent_hints import write_mcp_json
    result = write_mcp_json(tmp_path)
    assert result is True
    data = json.loads((tmp_path / ".mcp.json").read_text())
    assert "rekipedia" in data["mcpServers"]
    assert data["mcpServers"]["rekipedia"]["command"] == "reki"


def test_write_mcp_json_no_duplicate(tmp_path):
    from rekipedia.orchestrator.agent_hints import write_mcp_json
    write_mcp_json(tmp_path)
    result = write_mcp_json(tmp_path)
    assert result is False  # already exists


def test_write_mcp_json_merges_existing(tmp_path):
    from rekipedia.orchestrator.agent_hints import write_mcp_json
    existing = {"mcpServers": {"other-tool": {"command": "other"}}}
    (tmp_path / ".mcp.json").write_text(json.dumps(existing))
    write_mcp_json(tmp_path)
    data = json.loads((tmp_path / ".mcp.json").read_text())
    assert "other-tool" in data["mcpServers"]  # preserved
    assert "rekipedia" in data["mcpServers"]   # added
