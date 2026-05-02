"""Config / manifest extractor for package.json, pyproject.toml, Dockerfile, CI yml."""
from __future__ import annotations

import json
import re
from pathlib import Path

from rekipedia.extractors.base import BaseExtractor
from rekipedia.models.contracts import AnalysisResult

_CONFIG_NAMES = {
    "package.json",
    "pyproject.toml",
    "dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    ".env.sample",
    ".env.example",
}
_CI_PATTERNS = re.compile(r"\.github/workflows/.*\.ya?ml$|\.gitlab-ci\.ya?ml$|Jenkinsfile|\.circleci/config\.ya?ml$")


class ConfigExtractor(BaseExtractor):
    def can_handle(self, path: Path) -> bool:
        name_lower = path.name.lower()
        return name_lower in _CONFIG_NAMES or bool(_CI_PATTERNS.search(str(path)))

    def extract(self, path: Path, repo_root: Path) -> AnalysisResult:
        rel = str(path.relative_to(repo_root))
        name_lower = path.name.lower()

        build_commands: list[str] = []
        test_commands: list[str] = []
        risks: list[str] = []
        evidence: dict[str, str] = {}

        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return AnalysisResult(shard_id=rel, files_seen=[rel], entry_points=[])

        if name_lower == "package.json":
            _parse_package_json(text, build_commands, test_commands, evidence)
        elif name_lower == "pyproject.toml":
            _parse_pyproject_toml(text, build_commands, test_commands, evidence)
        elif name_lower == "dockerfile":
            _parse_dockerfile(text, build_commands, risks, evidence)
        elif _CI_PATTERNS.search(rel):
            _parse_ci_yml(text, build_commands, test_commands, evidence)

        return AnalysisResult(
            shard_id=rel,
            files_seen=[rel],
            entry_points=[],
            build_commands=build_commands,
            test_commands=test_commands,
            risks=risks,
            evidence=evidence,
        )


# ── parsers ──────────────────────────────────────────────────────────

def _parse_package_json(
    text: str,
    build: list[str],
    test: list[str],
    evidence: dict[str, str],
) -> None:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return
    scripts = data.get("scripts", {})
    if "build" in scripts:
        build.append(f"npm run build  # {scripts['build']}")
    if "start" in scripts:
        build.append(f"npm start  # {scripts['start']}")
    for k, v in scripts.items():
        if "test" in k:
            test.append(f"npm run {k}  # {v}")
    if "name" in data:
        evidence["npm_name"] = data["name"]
    if "version" in data:
        evidence["npm_version"] = data["version"]
    deps = list(data.get("dependencies", {}).keys())
    if deps:
        evidence["npm_deps"] = ", ".join(deps[:20])


def _parse_pyproject_toml(
    text: str,
    build: list[str],
    test: list[str],
    evidence: dict[str, str],
) -> None:
    # Basic regex parsing (no tomllib dep for max compat)
    if m := re.search(r'name\s*=\s*"([^"]+)"', text):
        evidence["py_name"] = m.group(1)
    if m := re.search(r'version\s*=\s*"([^"]+)"', text):
        evidence["py_version"] = m.group(1)
    if "pytest" in text:
        test.append("pytest")
    if "uv" in text:
        build.append("uv build")
    if re.search(r"scripts.*=", text):
        build.append("python -m build")
    # entry points
    for m in re.finditer(r'\[project\.scripts\](.*?)(?=\[|\Z)', text, re.DOTALL):
        evidence["entry_points"] = m.group(1).strip()


def _parse_dockerfile(
    text: str,
    build: list[str],
    risks: list[str],
    evidence: dict[str, str],
) -> None:
    lines = text.splitlines()
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("FROM"):
            evidence["docker_base"] = stripped
        if stripped.startswith("EXPOSE"):
            evidence["docker_expose"] = stripped
        if "ADD" in stripped and ("http://" in stripped or "https://" in stripped):
            risks.append("Dockerfile uses ADD with remote URL — prefer COPY + explicit fetch")
        if re.search(r"apt-get install.*-y", stripped) and "--no-install-recommends" not in stripped:
            risks.append("apt-get install without --no-install-recommends inflates image size")
    build.append("docker build .")


def _parse_ci_yml(
    text: str,
    build: list[str],
    test: list[str],
    evidence: dict[str, str],
) -> None:
    # Extract run: lines
    for m in re.finditer(r"run:\s*\|?\s*(.+)", text):
        cmd = m.group(1).strip()
        if any(t in cmd for t in ["pytest", "jest", "vitest", "cargo test", "go test", "npm test"]):
            test.append(cmd)
        elif any(b in cmd for b in ["build", "compile", "package", "make "]):
            build.append(cmd)
    if "on:" in text:
        evidence["ci_triggers"] = re.search(r"on:\s*(.+?)(?=\n\w|\Z)", text, re.DOTALL).group(1)[:200] if re.search(r"on:\s*(.+?)(?=\n\w|\Z)", text, re.DOTALL) else ""
