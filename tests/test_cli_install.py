"""Tests for reki install skill installer command."""
from __future__ import annotations

from pathlib import Path
from click.testing import CliRunner
import pytest

from rekipedia.cli import main
from rekipedia.cli.install_cmd import install_skill_files


def test_install_skill_files_pi_project(tmp_path: Path):
    written = install_skill_files(platform="pi", project=True, repo_root=tmp_path)
    assert len(written) == 1
    skill_file = written[0]
    assert skill_file.exists()
    assert skill_file == tmp_path / ".pi" / "agent" / "skills" / "rekipedia" / "SKILL.md"
    content = skill_file.read_text(encoding="utf-8")
    assert "rekipedia" in content
    assert "reki explain" in content


def test_install_skill_files_claude_project(tmp_path: Path):
    written = install_skill_files(platform="claude", project=True, repo_root=tmp_path)
    assert len(written) == 1
    skill_file = written[0]
    assert skill_file == tmp_path / ".claude" / "skills" / "rekipedia" / "SKILL.md"


def test_install_skill_files_cursor_project(tmp_path: Path):
    written = install_skill_files(platform="cursor", project=True, repo_root=tmp_path)
    assert len(written) == 1
    rule_file = written[0]
    assert rule_file == tmp_path / ".cursor" / "rules" / "rekipedia.mdc"


def test_cli_install_command_invocation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(main, ["install", "--platform", "pi", "--project"])
    assert result.exit_code == 0
    assert "Successfully installed" in result.output
    assert (tmp_path / ".pi" / "agent" / "skills" / "rekipedia" / "SKILL.md").exists()
