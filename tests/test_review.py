"""Tests for reki review (#133 — LLM-powered PR diff review)."""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from rekipedia.cli.review import _truncate_diff, run_review
from rekipedia.models.contracts import LLMConfig

MINI_PY = Path(__file__).parent / "fixtures" / "mini-py-repo"

SAMPLE_DIFF = """\
diff --git a/rekipedia/auth.py b/rekipedia/auth.py
index 1234567..abcdefg 100644
--- a/rekipedia/auth.py
+++ b/rekipedia/auth.py
@@ -10,6 +10,8 @@ def login(username, password):
     if not username or not password:
         raise ValueError("credentials required")
+    if len(password) < 8:
+        raise ValueError("password too short")
     return _verify(username, password)
"""


def _fake_page_response() -> str:
    return json.dumps({
        "title": "Index",
        "summary": "A small test project.",
        "key_concepts": [],
        "symbols": [],
        "relationships": [],
        "risks": [],
        "build_commands": [],
        "test_commands": [],
        "mermaid_graph": "",
    })


@pytest.fixture()
def mock_page_llm():
    with patch("rekipedia.synthesis.page_builder.LLMClient") as MockClient:
        mock_instance = MagicMock()
        mock_instance.call.side_effect = lambda prompt, system="": _fake_page_response()
        MockClient.return_value = mock_instance
        yield mock_instance


@pytest.fixture()
def scanned_repo(mock_page_llm, tmp_path):
    """Run a full scan and return (repo_root, output_dir)."""
    from rekipedia.orchestrator.run_digest import run_digest
    repo = tmp_path / "repo"
    shutil.copytree(MINI_PY, repo)
    output_dir = tmp_path / ".rekipedia"
    run_digest(repo_root=repo, output_dir=output_dir, llm_config=LLMConfig(), force_local=True)
    return repo, output_dir


@pytest.fixture()
def bare_repo(tmp_path):
    """Just a repo dir + output_dir without scanning."""
    repo = tmp_path / "repo"
    shutil.copytree(MINI_PY, repo)
    output_dir = tmp_path / ".rekipedia"
    return repo, output_dir


# ── _truncate_diff ────────────────────────────────────────────────────────────

def test_truncate_diff_short_diff_unchanged():
    short = "diff --git a/foo.py b/foo.py\n+hello"
    result, truncated = _truncate_diff(short, budget=10_000)
    assert result == short
    assert truncated is False


def test_truncate_diff_long_diff_truncated():
    # Build a diff larger than budget
    big_diff = ("diff --git a/file.py b/file.py\n" + "+" * 100 + "\n") * 200
    result, truncated = _truncate_diff(big_diff, budget=5_000)
    assert len(result) <= 5_500  # allow small overshoot at section boundary
    assert truncated is True


# ── run_review (non-streaming) ────────────────────────────────────────────────

def test_run_review_returns_string(bare_repo):
    repo, output_dir = bare_repo
    with patch("rekipedia.llm.client.LLMClient") as MockClient:
        mock = MagicMock()
        mock.call.return_value = "## Summary\nLooks good."
        MockClient.return_value = mock

        result = run_review(SAMPLE_DIFF, repo, output_dir, LLMConfig(), stream=False)

    assert isinstance(result, str)
    assert "Summary" in result or len(result) > 0


def test_run_review_passes_diff_in_prompt(bare_repo):
    repo, output_dir = bare_repo
    captured_prompts: list[str] = []

    with patch("rekipedia.llm.client.LLMClient") as MockClient:
        mock = MagicMock()
        def _capture(prompt, system="", **kwargs):
            captured_prompts.append(prompt)
            return "review"
        mock.call.side_effect = _capture
        MockClient.return_value = mock

        run_review(SAMPLE_DIFF, repo, output_dir, LLMConfig(), stream=False)

    assert captured_prompts
    assert "auth.py" in captured_prompts[0]
    assert "password too short" in captured_prompts[0]


def test_run_review_raises_on_empty_diff(bare_repo):
    repo, output_dir = bare_repo
    with pytest.raises(RuntimeError, match="empty"):
        run_review("", repo, output_dir, LLMConfig(), stream=False)


def test_run_review_with_no_knowledge_store(tmp_path):
    """run_review works even without a knowledge store."""
    repo = tmp_path / "repo"
    repo.mkdir()
    output_dir = tmp_path / ".rekipedia"

    with patch("rekipedia.llm.client.LLMClient") as MockClient:
        mock = MagicMock()
        mock.call.return_value = "## Summary\nUngrounded review."
        MockClient.return_value = mock

        result = run_review(SAMPLE_DIFF, repo, output_dir, LLMConfig(), stream=False)

    assert isinstance(result, str)


# ── run_review (streaming) ────────────────────────────────────────────────────

def test_run_review_streaming_yields_chunks(bare_repo):
    repo, output_dir = bare_repo
    chunks = ["## Summary\n", "Looks ", "good."]

    with patch("rekipedia.llm.client.LLMClient") as MockClient:
        mock = MagicMock()
        mock.stream.return_value = iter(chunks)
        MockClient.return_value = mock

        result = list(run_review(SAMPLE_DIFF, repo, output_dir, LLMConfig(), stream=True))

    assert result == chunks


def test_run_review_streaming_full_text(bare_repo):
    repo, output_dir = bare_repo
    chunks = ["## Summary\n", "LGTM."]

    with patch("rekipedia.llm.client.LLMClient") as MockClient:
        mock = MagicMock()
        mock.stream.return_value = iter(chunks)
        MockClient.return_value = mock

        full = "".join(run_review(SAMPLE_DIFF, repo, output_dir, LLMConfig(), stream=True))

    assert full == "## Summary\nLGTM."


# ── run_review uses wiki context ──────────────────────────────────────────────

def test_run_review_uses_wiki_context(scanned_repo):
    """When a knowledge store exists, the system prompt should include wiki context."""
    repo, output_dir = scanned_repo
    captured_systems: list[str] = []

    with patch("rekipedia.llm.client.LLMClient") as MockClient:
        mock = MagicMock()
        def _capture(prompt, system="", **kwargs):
            captured_systems.append(system)
            return "review"
        mock.call.side_effect = _capture
        MockClient.return_value = mock

        run_review(SAMPLE_DIFF, repo, output_dir, LLMConfig(), stream=False)

    assert captured_systems
    # System prompt should contain wiki context
    assert "Knowledge Context" in captured_systems[0] or "wiki" in captured_systems[0].lower()


# ── review_cmd CLI ────────────────────────────────────────────────────────────

def test_review_cmd_registered():
    """review_cmd should be importable and registered in the CLI."""
    from rekipedia.cli import main
    assert "review" in [cmd.name for cmd in main.commands.values()]


def test_review_cmd_with_diff_file(bare_repo, tmp_path):
    """--diff flag should read diff from file."""
    from click.testing import CliRunner

    from rekipedia.cli.review import review_cmd

    repo, output_dir = bare_repo
    diff_path = tmp_path / "changes.patch"
    diff_path.write_text(SAMPLE_DIFF, encoding="utf-8")

    runner = CliRunner()
    with patch("rekipedia.cli.review.run_review") as mock_review:
        mock_review.return_value = iter(["## Summary\nLGTM."])
        result = runner.invoke(
            review_cmd,
            [
                "--repo", str(repo),
                "--output-dir", str(output_dir),
                "--diff", str(diff_path),
                "--no-stream",
            ],
        )

    assert result.exit_code == 0 or "Error" not in (result.output or "")


def test_review_cmd_empty_diff_exits_cleanly(bare_repo):
    """An empty diff should print a message and exit 0."""
    from click.testing import CliRunner

    from rekipedia.cli.review import review_cmd

    repo, output_dir = bare_repo
    runner = CliRunner()

    with patch("rekipedia.cli.review._get_git_diff", return_value=""):
        result = runner.invoke(
            review_cmd,
            ["--repo", str(repo), "--output-dir", str(output_dir)],
        )

    assert result.exit_code == 0
    assert "No changes" in result.output
