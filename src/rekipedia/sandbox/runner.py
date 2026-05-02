"""Sandbox runners: DockerSandboxRunner and LocalRunner fallback."""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path

from rekipedia.models.contracts import AnalysisResult, Shard

_SANDBOX_IMAGE = "rekipedia-sandbox:latest"
_ANALYZE_SCRIPT = Path(__file__).parent / "tasks" / "analyze_shard.py"


class BaseRunner(ABC):
    @abstractmethod
    def run(self, shard: Shard, repo_root: Path) -> AnalysisResult:
        """Run extraction for a shard and return an AnalysisResult."""


class LocalRunner(BaseRunner):
    """Run extractors in-process (no Docker required)."""

    def run(self, shard: Shard, repo_root: Path) -> AnalysisResult:
        from rekipedia.extractors import ALL_EXTRACTORS  # noqa: PLC0415

        merged = AnalysisResult(
            shard_id=shard.shard_id,
            files_seen=[],
            entry_points=[],
        )

        for file_info in shard.files:
            abs_path = repo_root / file_info.path

            if not abs_path.exists():
                merged.risks.append(f"missing: {file_info.path}")
                continue

            handled = False
            for extractor in ALL_EXTRACTORS:
                if extractor.can_handle(abs_path):
                    try:
                        result = extractor.extract(abs_path, repo_root)
                        _merge(merged, result)
                        handled = True
                        break
                    except Exception as exc:  # noqa: BLE001
                        merged.risks.append(f"extractor error on {file_info.path}: {exc}")
                        break

            if not handled:
                merged.files_seen.append(file_info.path)

        return merged


class DockerSandboxRunner(BaseRunner):
    """Run extractors inside an isolated Docker container.

    The container runs with `--network none` so no outbound network calls
    can be made by untrusted code.  The repository is mounted read-only.
    LLM calls happen on the HOST after extraction completes.
    """

    def __init__(self, image: str = _SANDBOX_IMAGE, timeout: int = 120) -> None:
        self._image = image
        self._timeout = timeout

    def run(self, shard: Shard, repo_root: Path) -> AnalysisResult:
        with tempfile.TemporaryDirectory(prefix="rekipedia-sandbox-") as tmpdir:
            tmp = Path(tmpdir)
            shard_file = tmp / "shard.json"
            output_file = tmp / "result.json"

            # Write shard descriptor with root pointing to /repo (container path)
            shard_dict = shard.model_dump(by_alias=True)
            shard_dict["root"] = "/repo"
            shard_file.write_text(json.dumps(shard_dict))

            cmd = [
                "docker", "run", "--rm",
                "--network", "none",
                "--read-only",
                "--tmpfs", "/tmp",
                "-v", f"{repo_root}:/repo:ro",
                "-v", f"{tmp}:/work",
                self._image,
                # Dockerfile.sandbox sets ENTRYPOINT to analyze_shard.py,
                # so only pass the two file-path arguments here.
                "/work/shard.json", "/work/result.json",
            ]

            result = subprocess.run(
                cmd,
                timeout=self._timeout,
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                raise RuntimeError(
                    f"Docker sandbox failed (exit {result.returncode}):\n{result.stderr[:2000]}"
                )

            raw = json.loads(output_file.read_text())
            return AnalysisResult.model_validate(raw)


def get_runner(force_local: bool = False) -> BaseRunner:
    """Return DockerSandboxRunner if Docker is available and image exists, otherwise LocalRunner."""
    if force_local:
        return LocalRunner()
    if _docker_image_available():
        return DockerSandboxRunner()
    return LocalRunner()


def _docker_available() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


def _docker_image_available() -> bool:
    """Return True only if Docker is running AND the sandbox image exists locally."""
    if not _docker_available():
        return False
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", _SANDBOX_IMAGE],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


def _merge(target: AnalysisResult, src: AnalysisResult) -> None:
    target.files_seen.extend(src.files_seen)
    target.entry_points.extend(src.entry_points)
    target.symbols.extend(src.symbols)
    target.relationships.extend(src.relationships)
    target.build_commands.extend(src.build_commands)
    target.test_commands.extend(src.test_commands)
    target.risks.extend(src.risks)
    target.evidence.update(src.evidence)
