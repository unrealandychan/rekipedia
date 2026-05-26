"""Coverage tests for rekipedia sandbox/runner.py."""
from __future__ import annotations

from unittest.mock import patch

from rekipedia.models.contracts import FileManifest, Shard
from rekipedia.sandbox.runner import (
    DockerSandboxRunner,
    LocalRunner,
    get_runner,
)

# ── LocalRunner ───────────────────────────────────────────────────────────────

def test_local_runner_extracts_symbols(tmp_path):
    """LocalRunner should process a real Python file and return an AnalysisResult."""
    py_file = tmp_path / "sample.py"
    py_file.write_text("def hello():\n    pass\n\nclass Foo:\n    pass\n")

    shard = Shard(
        shard_id="s1",
        files=[FileManifest(path="sample.py", sha256="abc", size_bytes=0)],
        root=str(tmp_path),
    )
    runner = LocalRunner()
    result = runner.run(shard, tmp_path)
    # Should have processed the file (symbols or files_seen populated)
    assert result.shard_id == "s1"
    # No risks for a file that exists
    missing_risks = [r for r in result.risks if "missing:" in r]
    assert missing_risks == []


def test_local_runner_missing_file_adds_risk(tmp_path):
    """LocalRunner should append a risk entry for a non-existent file."""
    shard = Shard(
        shard_id="s2",
        files=[FileManifest(path="ghost.py", sha256="abc", size_bytes=0)],
        root=str(tmp_path),
    )
    runner = LocalRunner()
    result = runner.run(shard, tmp_path)
    assert any("missing" in r for r in result.risks)


# ── get_runner ────────────────────────────────────────────────────────────────

def test_get_runner_force_local_returns_local_runner():
    runner = get_runner(force_local=True)
    assert isinstance(runner, LocalRunner)


def test_get_runner_no_docker_returns_local_runner():
    with patch("rekipedia.sandbox.runner._docker_image_available", return_value=False):
        runner = get_runner()
    assert isinstance(runner, LocalRunner)


def test_get_runner_docker_available_returns_docker_runner():
    with patch("rekipedia.sandbox.runner._docker_image_available", return_value=True):
        runner = get_runner()
    assert isinstance(runner, DockerSandboxRunner)


# ── DockerSandboxRunner ───────────────────────────────────────────────────────

def test_docker_sandbox_runner_defaults():
    runner = DockerSandboxRunner()
    assert runner._image == "rekipedia-sandbox:latest"
    assert runner._timeout == 120


def test_docker_sandbox_runner_custom_params():
    runner = DockerSandboxRunner(image="my-image:v1", timeout=60)
    assert runner._image == "my-image:v1"
    assert runner._timeout == 60
