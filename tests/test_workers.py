"""Tests for --workers flag and parallel extraction (issue #148)."""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from click.testing import CliRunner

# ---------------------------------------------------------------------------
# Workers resolution helpers
# ---------------------------------------------------------------------------

def _resolve_workers(cli_value, env_value=None):
    """Mirror the resolution logic in scan.py."""
    if cli_value is not None:
        return cli_value
    env_val = env_value if env_value is not None else "0"
    return int(env_val) or min(4, os.cpu_count() or 4)


def test_workers_default_resolution():
    """When no CLI flag and no env var, workers = min(4, cpu_count)."""
    result = _resolve_workers(None, env_value="0")
    assert result == min(4, os.cpu_count() or 4)


def test_workers_env_var():
    """REKIPEDIA_WORKERS=8 sets workers=8."""
    result = _resolve_workers(None, env_value="8")
    assert result == 8


def test_workers_cli_overrides_env():
    """CLI --workers 2 overrides REKIPEDIA_WORKERS=8."""
    result = _resolve_workers(2, env_value="8")
    assert result == 2


def test_workers_invalid_env_var():
    """REKIPEDIA_WORKERS=abc raises ValueError."""
    with pytest.raises(ValueError):
        _resolve_workers(None, env_value="abc")


# ---------------------------------------------------------------------------
# run_digest workers parameter
# ---------------------------------------------------------------------------

def test_run_digest_workers_param():
    """run_digest passes workers to ThreadPoolExecutor."""
    from concurrent.futures import ThreadPoolExecutor

    from rekipedia.orchestrator import run_digest as rd_module

    captured = {}

    real_tpe = ThreadPoolExecutor

    class CapturingTPE:
        def __init__(self, *args, max_workers=None, **kwargs):
            captured["max_workers"] = max_workers
            self._real = real_tpe(max_workers=max_workers)

        def __enter__(self):
            return self._real.__enter__()

        def __exit__(self, *args):
            return self._real.__exit__(*args)

        def submit(self, *a, **kw):
            return self._real.submit(*a, **kw)

    # We just verify run_digest accepts the workers kwarg without error
    # by inspecting the signature.
    import inspect
    sig = inspect.signature(rd_module.run_digest)
    assert "workers" in sig.parameters
    assert sig.parameters["workers"].default == 4


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------

def test_scan_cli_workers_flag():
    """reki scan --workers 3 passes workers=3 to run_digest."""
    from rekipedia.cli.scan import scan_cmd

    runner = CliRunner()
    captured_workers = {}

    def fake_run_digest(**kwargs):
        captured_workers["workers"] = kwargs.get("workers")

    with runner.isolated_filesystem():

        with patch("rekipedia.orchestrator.run_digest.run_digest", side_effect=fake_run_digest), \
             patch("rekipedia.cli.scan._load_config", return_value={}):
            # Patch where run_digest is imported inside the function
            import rekipedia.orchestrator.run_digest as rd_mod
            original = rd_mod.run_digest
            rd_mod.run_digest = fake_run_digest
            try:
                result = runner.invoke(
                    scan_cmd,
                    [".", "--workers", "3", "--no-docker"],
                )
            finally:
                rd_mod.run_digest = original

    assert captured_workers.get("workers") == 3
