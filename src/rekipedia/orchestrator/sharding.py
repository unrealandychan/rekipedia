"""Shard planner: partition FileManifest lists into token-budget shards."""
from __future__ import annotations

from pathlib import Path

from rekipedia.models.contracts import FileManifest, LLMConfig, Shard

# Rough tokens-per-byte ratio (4 chars ≈ 1 token for code)
_BYTES_PER_TOKEN = 4
# Max tokens per shard before a new shard is started
_DEFAULT_TOKEN_BUDGET = 12_000


class ShardPlanner:
    """Group files into shards that fit within a token budget.

    Files are first grouped by top-level directory.  If a group exceeds the
    budget it is split into consecutive sub-groups.
    """

    def __init__(self, token_budget: int = _DEFAULT_TOKEN_BUDGET) -> None:
        self._budget = token_budget

    def plan(
        self,
        files: list[FileManifest],
        llm: LLMConfig | None = None,
    ) -> list[Shard]:
        if not files:
            return []

        llm = llm or LLMConfig()

        # Group by top-level directory (or "." for root files)
        groups: dict[str, list[FileManifest]] = {}
        for f in files:
            top = Path(f.path).parts[0] if "/" in f.path or "\\" in f.path else "."
            groups.setdefault(top, []).append(f)

        shards: list[Shard] = []
        for group_dir, group_files in groups.items():
            shards.extend(self._split_group(group_dir, group_files, llm))

        return shards

    def _split_group(
        self,
        group_dir: str,
        files: list[FileManifest],
        llm: LLMConfig,
    ) -> list[Shard]:
        shards: list[Shard] = []
        bucket: list[FileManifest] = []
        bucket_tokens = 0
        bucket_idx = 0

        for f in files:
            file_tokens = max(1, f.size_bytes // _BYTES_PER_TOKEN)
            if bucket and bucket_tokens + file_tokens > self._budget:
                shards.append(_make_shard(group_dir, bucket_idx, bucket, llm))
                bucket = []
                bucket_tokens = 0
                bucket_idx += 1
            bucket.append(f)
            bucket_tokens += file_tokens

        if bucket:
            shards.append(_make_shard(group_dir, bucket_idx, bucket, llm))

        return shards


def _make_shard(
    group_dir: str, idx: int, files: list[FileManifest], llm: LLMConfig
) -> Shard:
    shard_id = group_dir if idx == 0 else f"{group_dir}#{idx}"
    return Shard(shard_id=shard_id, root=group_dir, files=files, llm=llm)
