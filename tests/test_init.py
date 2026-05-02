"""Tests for `rekipedia init` command."""
from __future__ import annotations

from pathlib import Path

import yaml
from click.testing import CliRunner

from rekipedia.cli import main


def test_init_creates_config_and_gitignore(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["init", str(tmp_path)])
    assert result.exit_code == 0, result.output

    config_path = tmp_path / ".rekipedia" / "config.yml"
    assert config_path.exists()

    config = yaml.safe_load(config_path.read_text())
    assert config["version"] == 1
    assert "llm" in config
    assert "model" in config["llm"]

    gitignore = (tmp_path / ".gitignore").read_text()
    assert ".rekipedia/store.db" in gitignore


def test_init_is_idempotent(tmp_path: Path) -> None:
    runner = CliRunner()
    # Run twice — should not raise or duplicate .gitignore entries
    runner.invoke(main, ["init", str(tmp_path)])
    result = runner.invoke(main, ["init", str(tmp_path)])
    assert result.exit_code == 0

    gitignore = (tmp_path / ".gitignore").read_text()
    count = gitignore.count(".rekipedia/store.db")
    assert count == 1, f"Expected 1 entry, got {count}"


def test_init_default_directory(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(main, ["init"])
    assert result.exit_code == 0
    assert (tmp_path / ".rekipedia" / "config.yml").exists()
