"""Tests for rekipedia.config.loader (issue #143 — 3-layer merge)."""
from __future__ import annotations

from pathlib import Path

import yaml

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(data))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_global_only(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    global_cfg = tmp_path / "xdg" / "rekipedia" / "config.yml"
    _write(global_cfg, {"llm": {"model": "openai/gpt-4o", "api_key": "sk-global"}})

    repo = tmp_path / "repo"
    repo.mkdir()

    from rekipedia.config.loader import load_config
    result = load_config(repo)
    assert result["llm"]["model"] == "openai/gpt-4o"
    assert result["llm"]["api_key"] == "sk-global"


def test_local_only(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    # no global config

    repo = tmp_path / "repo"
    local_cfg = repo / ".rekipedia" / "config.yml"
    _write(local_cfg, {"llm": {"model": "ollama/llama4"}, "languages": ["python"]})

    from rekipedia.config.loader import load_config
    result = load_config(repo)
    assert result["llm"]["model"] == "ollama/llama4"
    assert result["languages"] == ["python"]


def test_merge_deep(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    global_cfg = tmp_path / "xdg" / "rekipedia" / "config.yml"
    _write(global_cfg, {"llm": {"api_key": "sk-global", "model": "openai/gpt-4o"}})

    repo = tmp_path / "repo"
    local_cfg = repo / ".rekipedia" / "config.yml"
    _write(local_cfg, {"llm": {"model": "anthropic/claude-3"}, "languages": ["go"]})

    from rekipedia.config.loader import load_config
    result = load_config(repo)
    assert result["llm"]["api_key"] == "sk-global"       # from global
    assert result["llm"]["model"] == "anthropic/claude-3"  # local wins
    assert result["languages"] == ["go"]                  # from local


def test_local_wins_scalar(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    global_cfg = tmp_path / "xdg" / "rekipedia" / "config.yml"
    _write(global_cfg, {"version": 1, "debug": False})

    repo = tmp_path / "repo"
    local_cfg = repo / ".rekipedia" / "config.yml"
    _write(local_cfg, {"version": 2, "debug": True})

    from rekipedia.config.loader import load_config
    result = load_config(repo)
    assert result["version"] == 2
    assert result["debug"] is True


def test_lists_local_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    global_cfg = tmp_path / "xdg" / "rekipedia" / "config.yml"
    _write(global_cfg, {"ignore": [".git"]})

    repo = tmp_path / "repo"
    local_cfg = repo / ".rekipedia" / "config.yml"
    _write(local_cfg, {"ignore": ["node_modules"]})

    from rekipedia.config.loader import load_config
    result = load_config(repo)
    assert result["ignore"] == ["node_modules"]


def test_missing_both(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    repo = tmp_path / "repo"
    repo.mkdir()

    from rekipedia.config.loader import load_config
    result = load_config(repo)
    assert result == {}


def test_xdg_config_home(tmp_path, monkeypatch):
    custom_xdg = tmp_path / "custom_xdg"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(custom_xdg))
    global_cfg = custom_xdg / "rekipedia" / "config.yml"
    _write(global_cfg, {"llm": {"api_key": "xdg-key"}})

    repo = tmp_path / "repo"
    repo.mkdir()

    from rekipedia.config.loader import load_config
    result = load_config(repo)
    assert result["llm"]["api_key"] == "xdg-key"


def test_get_global_config_path(tmp_path, monkeypatch):
    # Without XDG_CONFIG_HOME
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    import importlib

    from rekipedia.config import loader
    importlib.reload(loader)
    path = loader.get_global_config_path()
    assert path == Path.home() / ".config" / "rekipedia" / "config.yml"

    # With XDG_CONFIG_HOME
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    path2 = loader.get_global_config_path()
    assert path2 == tmp_path / "xdg" / "rekipedia" / "config.yml"
