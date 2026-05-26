"""Tests for `rekipedia refactor` CLI command."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from rekipedia.cli import main
from rekipedia.cli.refactor import (
    _apply_severity_filter,
    _build_static_report,
    _filter_llm_report,
    _static_walk,
)

# ---------------------------------------------------------------------------
# Help / registration smoke tests
# ---------------------------------------------------------------------------


def test_refactor_cmd_registered() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "refactor" in result.output


def test_refactor_help() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["refactor", "--help"])
    assert result.exit_code == 0
    assert "--no-llm" in result.output
    assert "--stdout" in result.output
    assert "--severity" in result.output
    assert "--json" in result.output


# ---------------------------------------------------------------------------
# _static_walk
# ---------------------------------------------------------------------------


def _make_repo(tmp_path: Path, files: dict[str, str]) -> Path:
    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return tmp_path


def test_static_walk_finds_todos(tmp_path: Path) -> None:
    _make_repo(tmp_path, {"src/main.py": "x = 1\n# TODO: refactor this\ny = 2\n"})
    findings = _static_walk(tmp_path)
    assert len(findings) == 1
    assert findings[0]["type"] == "TODO"
    assert findings[0]["severity"] == "medium"
    assert findings[0]["line"] == 2


def test_static_walk_finds_fixme(tmp_path: Path) -> None:
    _make_repo(tmp_path, {"main.go": "// FIXME: broken logic\nfunc foo() {}\n"})
    findings = _static_walk(tmp_path)
    assert len(findings) == 1
    assert findings[0]["type"] == "FIXME"
    assert findings[0]["severity"] == "high"


def test_static_walk_finds_multiple_annotations(tmp_path: Path) -> None:
    _make_repo(
        tmp_path,
        {
            "a.py": "# TODO: fix a\n# FIXME: urgent\n# HACK: workaround\n",
            "b.go": "// XXX: investigate\n",
        },
    )
    findings = _static_walk(tmp_path)
    assert len(findings) == 4


def test_static_walk_skips_dotgit(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "COMMIT_EDITMSG").write_text("# TODO: in git dir\n")
    _make_repo(tmp_path, {"src.py": "# TODO: real one\n"})
    findings = _static_walk(tmp_path)
    assert len(findings) == 1


def test_static_walk_skips_node_modules(tmp_path: Path) -> None:
    _make_repo(
        tmp_path,
        {
            "node_modules/lib.js": "// TODO: upstream fix\n",
            "src/app.js": "// FIXME: our bug\n",
        },
    )
    findings = _static_walk(tmp_path)
    assert all(f["file"].startswith("src") for f in findings)


def test_static_walk_empty_repo(tmp_path: Path) -> None:
    findings = _static_walk(tmp_path)
    assert findings == []


# ---------------------------------------------------------------------------
# _apply_severity_filter
# ---------------------------------------------------------------------------


def test_apply_severity_filter_all(tmp_path: Path) -> None:
    findings = [
        {"severity": "critical"},
        {"severity": "high"},
        {"severity": "medium"},
        {"severity": "low"},
    ]
    assert _apply_severity_filter(findings, "all") == findings
    assert _apply_severity_filter(findings, None) == findings


def test_apply_severity_filter_high() -> None:
    findings = [
        {"severity": "critical"},
        {"severity": "high"},
        {"severity": "medium"},
        {"severity": "low"},
    ]
    result = _apply_severity_filter(findings, "high")
    severities = [f["severity"] for f in result]
    assert "critical" in severities
    assert "high" in severities
    assert "medium" not in severities
    assert "low" not in severities


def test_apply_severity_filter_critical() -> None:
    findings = [{"severity": "critical"}, {"severity": "high"}, {"severity": "low"}]
    result = _apply_severity_filter(findings, "critical")
    assert len(result) == 1
    assert result[0]["severity"] == "critical"


# ---------------------------------------------------------------------------
# _build_static_report
# ---------------------------------------------------------------------------


def test_build_static_report_empty(tmp_path: Path) -> None:
    report = _build_static_report(tmp_path, [])
    assert "# REFACTOR.md" in report
    assert "No static annotations" in report


def test_build_static_report_with_findings(tmp_path: Path) -> None:
    findings = [
        {"type": "FIXME", "severity": "high", "file": "src/main.py", "line": 10, "description": "broken"},
        {"type": "TODO", "severity": "medium", "file": "src/util.py", "line": 5, "description": "add test"},
    ]
    report = _build_static_report(tmp_path, findings)
    assert "FIXME" in report
    assert "broken" in report
    assert "TODO" in report
    assert "add test" in report
    assert "🟠" in report  # high severity emoji
    assert "🟡" in report  # medium severity emoji


# ---------------------------------------------------------------------------
# _filter_llm_report
# ---------------------------------------------------------------------------


def test_filter_llm_report_all() -> None:
    content = "# Report\n\n| 🔴 Critical | issue |\n| 🟡 Medium | other |\n"
    assert _filter_llm_report(content, "all") == content


def test_filter_llm_report_high() -> None:
    content = "| 🔴 Critical | issue |\n| 🟠 High | item |\n| 🟡 Medium | skip |\n| 🟢 Low | also skip |\n"
    result = _filter_llm_report(content, "high")
    assert "🔴" in result
    assert "🟠" in result
    assert "🟡" not in result
    assert "🟢" not in result


# ---------------------------------------------------------------------------
# CLI integration — --no-llm
# ---------------------------------------------------------------------------


def test_refactor_no_llm_creates_file(tmp_path: Path) -> None:
    _make_repo(tmp_path, {"main.py": "# TODO: finish me\n"})
    runner = CliRunner()
    result = runner.invoke(main, ["refactor", str(tmp_path), "--no-llm"])
    assert result.exit_code == 0
    out_file = tmp_path / ".rekipedia" / "REFACTOR.md"
    assert out_file.exists()
    content = out_file.read_text()
    assert "TODO" in content


def test_refactor_no_llm_stdout(tmp_path: Path) -> None:
    _make_repo(tmp_path, {"main.py": "# FIXME: urgent\n"})
    runner = CliRunner()
    result = runner.invoke(main, ["refactor", str(tmp_path), "--no-llm", "--stdout"])
    assert result.exit_code == 0
    assert "FIXME" in result.output
    # No file should be written when --stdout is used
    assert not (tmp_path / ".rekipedia" / "REFACTOR.md").exists()


def test_refactor_no_llm_json(tmp_path: Path) -> None:
    _make_repo(tmp_path, {"main.go": "// TODO: something\n"})
    runner = CliRunner()
    result = runner.invoke(main, ["refactor", str(tmp_path), "--json"])
    assert result.exit_code == 0
    out_file = tmp_path / ".rekipedia" / "REFACTOR.json"
    assert out_file.exists()
    import json
    data = json.loads(out_file.read_text())
    assert "findings" in data
    assert any(f["type"] == "TODO" for f in data["findings"])


def test_refactor_no_llm_json_stdout(tmp_path: Path) -> None:
    _make_repo(tmp_path, {"main.go": "// FIXME: a bug\n"})
    runner = CliRunner()
    result = runner.invoke(main, ["refactor", str(tmp_path), "--json", "--stdout"])
    assert result.exit_code == 0
    import json
    data = json.loads(result.output)
    assert "findings" in data


def test_refactor_severity_filter(tmp_path: Path) -> None:
    _make_repo(
        tmp_path,
        {
            "a.py": "# FIXME: high prio\n",
            "b.py": "# TODO: low prio\n",
        },
    )
    runner = CliRunner()
    result = runner.invoke(main, ["refactor", str(tmp_path), "--no-llm", "--stdout", "--severity", "high"])
    assert result.exit_code == 0
    assert "FIXME" in result.output
    # TODO is medium severity — should be excluded
    assert "TODO" not in result.output


def test_refactor_custom_output_dir(tmp_path: Path) -> None:
    _make_repo(tmp_path, {"code.py": "# TODO: do stuff\n"})
    out_dir = tmp_path / "custom_out"
    runner = CliRunner()
    result = runner.invoke(
        main, ["refactor", str(tmp_path), "--no-llm", "--output-dir", str(out_dir)]
    )
    assert result.exit_code == 0
    assert (out_dir / "REFACTOR.md").exists()


# ---------------------------------------------------------------------------
# scan --with-refactor flag
# ---------------------------------------------------------------------------


def test_scan_has_with_refactor_flag() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["scan", "--help"])
    assert result.exit_code == 0
    assert "--with-refactor" in result.output


def test_scan_with_refactor_generates_file(tmp_path: Path) -> None:
    """scan --with-refactor should produce REFACTOR.md even when scan itself is patched."""
    _make_repo(tmp_path, {"main.py": "# FIXME: patch me\n"})
    runner = CliRunner()
    with patch("rekipedia.orchestrator.run_digest.run_digest"):
        result = runner.invoke(
            main,
            ["scan", str(tmp_path), "--no-docker", "--with-refactor"],
        )
    assert result.exit_code == 0
    assert (tmp_path / ".rekipedia" / "REFACTOR.md").exists()
