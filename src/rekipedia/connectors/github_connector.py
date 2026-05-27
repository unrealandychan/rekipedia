"""GitHub Issues & PR connector for rekipedia.

Fetches issues and pull requests from GitHub REST API using stdlib urllib only.
Token read order: CLI flag → REKIPEDIA_GITHUB_TOKEN env var → config file.
Token is NEVER written to sqlite or log output.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Callable


_GITHUB_API = "https://api.github.com"


@dataclass
class ExternalSource:
    """Represents an external source (GitHub Issue or PR)."""

    source_type: str          # "github_issue" | "github_pr"
    source_id: str            # e.g. "owner/repo#123"
    title: str
    body: str
    url: str
    state: str                # "open" | "closed"
    labels: list[str] = field(default_factory=list)
    date: str = ""            # ISO datetime
    files_changed: list[str] = field(default_factory=list)  # PRs only

    def to_dict(self) -> dict:
        return {
            "id": f"{self.source_type}:{self.source_id}",
            "source_type": self.source_type,
            "source_id": self.source_id,
            "title": self.title,
            "body": self.body,
            "url": self.url,
            "state": self.state,
            "labels": self.labels,
            "date": self.date,
            "files_changed": self.files_changed,
        }


def _detect_repo_from_git(cwd: str | None = None) -> str | None:
    """Auto-detect GitHub repo (owner/repo) from git remote origin URL."""
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=10,
        )
        if result.returncode != 0:
            return None
        url = result.stdout.strip()
        # Handle SSH: git@github.com:owner/repo.git
        m = re.match(r"git@github\.com[:/]+([^/]+/[^/]+?)(?:\.git)?$", url)
        if m:
            return m.group(1)
        # Handle HTTPS: https://github.com/owner/repo.git
        m = re.match(r"https?://(?:[^@]+@)?github\.com/([^/]+/[^/]+?)(?:\.git)?$", url)
        if m:
            return m.group(1)
    except Exception:
        pass
    return None


def _make_request(url: str, token: str | None) -> dict | list | None:
    """Make a GET request to the GitHub API. Returns parsed JSON or None on error."""
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        if e.code in (403, 429):
            raise RateLimitError(f"GitHub API rate limit hit (HTTP {e.code})")
        if e.code == 401:
            raise AuthError("GitHub API: unauthorized — check your token")
        if e.code == 404:
            raise RepoNotFoundError(f"Repository not found or no access: {url}")
        raise
    except Exception:
        raise


class RateLimitError(Exception):
    pass


class AuthError(Exception):
    pass


class RepoNotFoundError(Exception):
    pass


class GitHubConnector:
    """Fetches GitHub Issues and PRs and produces ExternalSource records."""

    def __init__(
        self,
        repo: str,
        token: str | None = None,
        max_issues: int = 500,
        max_prs: int = 200,
        progress_callback: Callable[[str, int, int], None] | None = None,
    ) -> None:
        self.repo = repo
        self.token = token
        self.max_issues = max_issues
        self.max_prs = max_prs
        self._progress = progress_callback or (lambda kind, cur, total: None)

    def _paginate(self, endpoint: str, cap: int) -> list[dict]:
        """Paginate a GitHub list endpoint up to *cap* items."""
        items: list[dict] = []
        page = 1
        while len(items) < cap:
            url = f"{_GITHUB_API}/repos/{self.repo}/{endpoint}?state=all&per_page=100&page={page}"
            batch = _make_request(url, self.token)
            if not batch:
                break
            items.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        return items[:cap]

    def fetch_issues(self) -> list[ExternalSource]:
        """Fetch issues (excludes PRs) from GitHub."""
        sources: list[ExternalSource] = []
        raw = self._paginate("issues", self.max_issues)
        for i, item in enumerate(raw):
            # GitHub issues endpoint returns PRs too; skip PRs
            if "pull_request" in item:
                continue
            number = item["number"]
            self._progress("issues", i + 1, len(raw))
            sources.append(
                ExternalSource(
                    source_type="github_issue",
                    source_id=f"{self.repo}#{number}",
                    title=item.get("title", ""),
                    body=item.get("body", "") or "",
                    url=item.get("html_url", ""),
                    state=item.get("state", ""),
                    labels=[lbl["name"] for lbl in item.get("labels", [])],
                    date=item.get("created_at", ""),
                )
            )
        return sources

    def fetch_prs(self) -> list[ExternalSource]:
        """Fetch pull requests from GitHub, including files changed."""
        sources: list[ExternalSource] = []
        raw = self._paginate("pulls", self.max_prs)
        for i, item in enumerate(raw):
            number = item["number"]
            self._progress("prs", i + 1, len(raw))
            # Fetch files changed
            files_changed: list[str] = []
            try:
                files_url = f"{_GITHUB_API}/repos/{self.repo}/pulls/{number}/files"
                files_data = _make_request(files_url, self.token)
                if files_data:
                    files_changed = [f["filename"] for f in files_data]
            except RateLimitError:
                raise
            except Exception:
                pass  # Best effort
            sources.append(
                ExternalSource(
                    source_type="github_pr",
                    source_id=f"{self.repo}#{number}",
                    title=item.get("title", ""),
                    body=item.get("body", "") or "",
                    url=item.get("html_url", ""),
                    state=item.get("state", ""),
                    labels=[lbl["name"] for lbl in item.get("labels", [])],
                    date=item.get("created_at", ""),
                    files_changed=files_changed,
                )
            )
        return sources

    def build_symbol_links(
        self,
        sources: list[ExternalSource],
        all_symbols: list[dict],
    ) -> list[dict]:
        """Build source_symbol_links from sources and symbol list.

        For PRs: match files_changed against symbols via file.
        For Issues: scan title+body for symbol names (substring match).

        Returns list of link dicts.
        """
        links: list[dict] = []

        # Build lookup: file -> [symbol_names]
        file_to_symbols: dict[str, list[str]] = {}
        for sym in all_symbols:
            f = sym.get("file", "")
            if f:
                file_to_symbols.setdefault(f, []).append(sym["name"])

        # All symbol names for issue body scanning
        all_symbol_names = [s["name"] for s in all_symbols if s.get("name")]

        for src in sources:
            src_id = f"{src.source_type}:{src.source_id}"
            if src.source_type == "github_pr":
                for fp in src.files_changed:
                    # Link as file_changed using file path as symbol_name
                    links.append({
                        "source_id": src_id,
                        "symbol_name": fp,
                        "link_type": "file_changed",
                    })
                    # Also link to symbols in those files
                    for sym_name in file_to_symbols.get(fp, []):
                        links.append({
                            "source_id": src_id,
                            "symbol_name": sym_name,
                            "link_type": "file_changed",
                        })
            elif src.source_type == "github_issue":
                text = f"{src.title} {src.body}"
                for sym_name in all_symbol_names:
                    if len(sym_name) >= 3 and sym_name in text:
                        links.append({
                            "source_id": src_id,
                            "symbol_name": sym_name,
                            "link_type": "mentioned",
                        })

        # Deduplicate
        seen: set[tuple] = set()
        unique_links: list[dict] = []
        for lnk in links:
            key = (lnk["source_id"], lnk["symbol_name"], lnk["link_type"])
            if key not in seen:
                seen.add(key)
                unique_links.append(lnk)

        return unique_links
