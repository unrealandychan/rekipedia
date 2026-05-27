"""Global + local config loader with deep-merge (issue #143).

Supported config keys include ``connectors.github`` for the GitHub connector:

.. code-block:: yaml

    connectors:
      github:
        token: ""          # or set REKIPEDIA_GITHUB_TOKEN env var
        repo: ""           # e.g. "owner/repo" — auto-detected from git remote if empty
        max_issues: 500    # cap
        max_prs: 200       # cap

Token read order (for ``reki connect github``):
  1. ``--token`` CLI flag
  2. ``REKIPEDIA_GITHUB_TOKEN`` environment variable
  3. ``connectors.github.token`` in config file

The token is NEVER written to sqlite or log output.
"""
from __future__ import annotations

import os
from pathlib import Path

import yaml


def get_global_config_path() -> Path:
    """Return the global rekipedia config path, respecting XDG_CONFIG_HOME."""
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        base = Path(xdg)
    else:
        base = Path.home() / ".config"
    return base / "rekipedia" / "config.yml"


def _deep_merge(base: dict, override: dict) -> dict:
    """Deep-merge override into base. Dicts merged recursively; scalars/lists: override wins."""
    result = dict(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result


def load_config(repo: Path) -> dict:
    """Load and deep-merge global + local config. Env vars are NOT applied here (CLI handles those)."""
    global_path = get_global_config_path()
    global_cfg: dict = {}
    if global_path.exists():
        global_cfg = yaml.safe_load(global_path.read_text()) or {}

    local_path = repo / ".rekipedia" / "config.yml"
    local_cfg: dict = {}
    if local_path.exists():
        local_cfg = yaml.safe_load(local_path.read_text()) or {}

    return _deep_merge(global_cfg, local_cfg)
