"""Tests for reki note CLI commands."""
from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from rekipedia.cli import main


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def store_dir(tmp_path):
    db_dir = tmp_path / ".rekipedia"
    db_dir.mkdir()
    return tmp_path


def invoke(runner, args, store_dir):
    return runner.invoke(main, args, catch_exceptions=False,
                         obj={"repo_root": str(store_dir)})


def test_note_add(runner, store_dir):
    result = invoke(runner, ["note", "add", "Use Redis", "--tag", "ops"], store_dir)
    assert result.exit_code == 0
    assert "Note added" in result.output


def test_note_list_empty(runner, store_dir):
    result = invoke(runner, ["note", "list"], store_dir)
    assert result.exit_code == 0
    assert "No notes found" in result.output


def test_note_list_json(runner, store_dir):
    invoke(runner, ["note", "add", "Redis caching", "--tag", "arch"], store_dir)
    result = invoke(runner, ["note", "list", "--json"], store_dir)
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert len(data) == 1
    assert data[0]["content"] == "Redis caching"


def test_note_remove(runner, store_dir):
    add_result = invoke(runner, ["note", "add", "To be deleted"], store_dir)
    note_id = add_result.output.split(": ")[-1].strip()
    result = invoke(runner, ["note", "remove", note_id[:8]], store_dir)
    assert result.exit_code == 0
    assert "Deleted" in result.output


def test_note_remove_not_found(runner, store_dir):
    from click.testing import CliRunner
    r = CliRunner()
    result = r.invoke(main, ["note", "remove", "nonexistent"],
                      obj={"repo_root": str(store_dir)})
    assert result.exit_code != 0


def test_note_import_yaml(runner, store_dir, tmp_path):
    yaml_file = tmp_path / "notes.yaml"
    yaml_file.write_text(
        "- content: Redis for sessions\n  tags: [arch, redis]\n"
        "- content: No Friday deploys\n  tags: [ops]\n"
    )
    result = invoke(runner, ["note", "import", str(yaml_file)], store_dir)
    assert result.exit_code == 0
    assert "2" in result.output

    list_result = invoke(runner, ["note", "list", "--json"], store_dir)
    data = json.loads(list_result.output)
    assert len(data) == 2


def test_note_import_yaml_dry_run(runner, store_dir, tmp_path):
    yaml_file = tmp_path / "notes.yaml"
    yaml_file.write_text("- content: Test note\n  tags: [test]\n")
    result = invoke(runner, ["note", "import", "--dry-run", str(yaml_file)], store_dir)
    assert result.exit_code == 0
    assert "Would import" in result.output
    # Nothing was written
    list_result = invoke(runner, ["note", "list"], store_dir)
    assert "No notes found" in list_result.output


def test_note_import_dedup(runner, store_dir, tmp_path):
    yaml_file = tmp_path / "notes.yaml"
    yaml_file.write_text("- content: Duplicate note\n  tags: []\n")
    invoke(runner, ["note", "import", str(yaml_file)], store_dir)
    result = invoke(runner, ["note", "import", str(yaml_file)], store_dir)
    assert result.exit_code == 0
    assert "skipped 1" in result.output or "skipping 1" in result.output


def test_note_import_markdown(runner, store_dir, tmp_path):
    md_file = tmp_path / "notes.md"
    md_file.write_text("## Architecture\ntags: arch\nWe use microservices.\n\n## Ops\nNever deploy Fridays.\n")
    result = invoke(runner, ["note", "import", str(md_file)], store_dir)
    assert result.exit_code == 0
    list_result = invoke(runner, ["note", "list", "--json"], store_dir)
    data = json.loads(list_result.output)
    assert len(data) == 2
