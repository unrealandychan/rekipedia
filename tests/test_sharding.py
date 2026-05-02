"""Tests for the sharding module."""
from __future__ import annotations

from rekipedia.models.contracts import FileManifest, LLMConfig
from rekipedia.orchestrator.sharding import ShardPlanner

_MINI_FILES = [
    FileManifest(path="src/a.py", sha256="aa" * 16, size_bytes=1000),
    FileManifest(path="src/b.py", sha256="bb" * 16, size_bytes=1000),
    FileManifest(path="tests/test_a.py", sha256="cc" * 16, size_bytes=500),
    FileManifest(path="README.md", sha256="dd" * 16, size_bytes=200),
]


def test_empty_files():
    planner = ShardPlanner()
    assert planner.plan([]) == []


def test_single_file_produces_one_shard():
    planner = ShardPlanner()
    shards = planner.plan([_MINI_FILES[0]])
    assert len(shards) == 1
    assert shards[0].files == [_MINI_FILES[0]]


def test_groups_by_top_dir():
    planner = ShardPlanner(token_budget=100_000)
    shards = planner.plan(_MINI_FILES)
    # src/, tests/, and "." (for README)
    group_roots = {s.root for s in shards}
    assert "src" in group_roots
    assert "tests" in group_roots


def test_splits_on_token_budget():
    # Each file is 4000 bytes → 1000 tokens.  Budget = 1500 → each file = own shard
    big_files = [
        FileManifest(path=f"src/big{i}.py", sha256=f"{i:02x}" * 16, size_bytes=6000)
        for i in range(3)
    ]
    planner = ShardPlanner(token_budget=1000)
    shards = planner.plan(big_files)
    # Three files each >budget → 3 shards
    assert len(shards) == 3


def test_shard_ids_unique():
    planner = ShardPlanner(token_budget=500)
    files = [
        FileManifest(path=f"src/f{i}.py", sha256=f"{i:02x}" * 16, size_bytes=3000)
        for i in range(5)
    ]
    shards = planner.plan(files)
    ids = [s.shard_id for s in shards]
    assert len(ids) == len(set(ids))


def test_llm_config_propagated():
    cfg = LLMConfig(model="custom/model")
    planner = ShardPlanner()
    shards = planner.plan([_MINI_FILES[0]], cfg)
    assert shards[0].llm.model == "custom/model"
