"""Linear Issues connector for rekipedia.

Fetches issues from Linear GraphQL API using stdlib urllib only.
Token read order: CLI flag → REKIPEDIA_LINEAR_API_KEY env var → config file.
Token is NEVER written to sqlite or log output.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Callable

from rekipedia.connectors.github_connector import ExternalSource

_LINEAR_API = "https://api.linear.app/graphql"

_ISSUES_QUERY = """
query Issues($first: Int!, $after: String, $teamId: String) {
  issues(
    first: $first,
    after: $after,
    filter: { team: { id: { eq: $teamId } } }
  ) {
    nodes {
      id
      title
      description
      url
      state { name }
      labels { nodes { name } }
      createdAt
      attachments { nodes { url title } }
    }
    pageInfo { hasNextPage endCursor }
  }
}
"""

_ISSUES_QUERY_NO_FILTER = """
query Issues($first: Int!, $after: String) {
  issues(first: $first, after: $after) {
    nodes {
      id
      title
      description
      url
      state { name }
      labels { nodes { name } }
      createdAt
      attachments { nodes { url title } }
    }
    pageInfo { hasNextPage endCursor }
  }
}
"""


class LinearAPIError(Exception):
    pass


class LinearAuthError(LinearAPIError):
    pass


class LinearRateLimitError(LinearAPIError):
    pass


def _graphql_request(api_key: str, query: str, variables: dict) -> dict:
    """Execute a Linear GraphQL request. Returns the parsed JSON response."""
    payload = json.dumps({"query": query, "variables": variables}).encode()
    req = urllib.request.Request(
        _LINEAR_API,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": api_key,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
            if "errors" in data:
                msgs = "; ".join(e.get("message", "") for e in data["errors"])
                raise LinearAPIError(f"Linear GraphQL error: {msgs}")
            return data
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise LinearAuthError("Linear API: unauthorized — check your API key")
        if e.code == 429:
            raise LinearRateLimitError("Linear API rate limit hit (HTTP 429)")
        raise LinearAPIError(f"Linear API HTTP error {e.code}") from e


class LinearConnector:
    """Fetches Linear Issues and produces ExternalSource records."""

    def __init__(
        self,
        api_key: str,
        team_id: str | None = None,
        max_issues: int = 500,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> None:
        self.api_key = api_key
        self.team_id = team_id or None
        self.max_issues = max_issues
        self._progress = progress_callback or (lambda cur, total: None)

    def fetch_issues(self) -> list[ExternalSource]:
        """Fetch issues from Linear, paginating up to max_issues."""
        sources: list[ExternalSource] = []
        cursor: str | None = None
        page_size = 50

        while len(sources) < self.max_issues:
            batch_size = min(page_size, self.max_issues - len(sources))
            if self.team_id:
                variables: dict = {"first": batch_size, "after": cursor, "teamId": self.team_id}
                query = _ISSUES_QUERY
            else:
                variables = {"first": batch_size, "after": cursor}
                query = _ISSUES_QUERY_NO_FILTER

            resp = _graphql_request(self.api_key, query, variables)
            issues_data = resp.get("data", {}).get("issues", {})
            nodes = issues_data.get("nodes", [])
            page_info = issues_data.get("pageInfo", {})

            for issue in nodes:
                sources.append(self._map_issue(issue))
                self._progress(len(sources), self.max_issues)

            if not page_info.get("hasNextPage") or not nodes:
                break
            cursor = page_info.get("endCursor")

        return sources

    def _map_issue(self, issue: dict) -> ExternalSource:
        state = issue.get("state") or {}
        labels_data = issue.get("labels") or {}
        label_nodes = labels_data.get("nodes") or []
        return ExternalSource(
            source_type="linear_issue",
            source_id=f"linear:{issue['id']}",
            title=issue.get("title") or "",
            body=issue.get("description") or "",
            url=issue.get("url") or "",
            state=state.get("name") or "",
            labels=[lbl["name"] for lbl in label_nodes if lbl.get("name")],
            date=issue.get("createdAt") or "",
            files_changed=[],
        )

    def build_symbol_links(
        self,
        sources: list[ExternalSource],
        all_symbols: list[dict],
    ) -> list[dict]:
        """Scan title+body for symbol names, return link dicts."""
        all_symbol_names = [s["name"] for s in all_symbols if s.get("name")]
        links: list[dict] = []
        for src in sources:
            src_id = f"{src.source_type}:{src.source_id}"
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
        unique: list[dict] = []
        for lnk in links:
            key = (lnk["source_id"], lnk["symbol_name"], lnk["link_type"])
            if key not in seen:
                seen.add(key)
                unique.append(lnk)
        return unique

    def link_to_symbols(self, sources: list[ExternalSource], store) -> int:  # type: ignore[type-arg]
        """Build symbol links and persist them. Returns link count."""
        from rekipedia.storage.sqlite_store import SqliteStore
        all_symbols: list[dict] = []
        # store may or may not have get_latest_run_id — try best effort
        try:
            run_id = store.get_latest_run_id(None) if hasattr(store, "get_latest_run_id") else None
            if run_id:
                all_symbols = store.get_all_symbols(run_id)
        except Exception:
            pass
        links = self.build_symbol_links(sources, all_symbols)
        if links:
            store.store_source_symbol_links(links)
        return len(links)
