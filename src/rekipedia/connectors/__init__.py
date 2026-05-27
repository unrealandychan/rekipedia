"""External data connectors for rekipedia."""
from typing import Protocol, runtime_checkable

from rekipedia.connectors.github_connector import ExternalSource, GitHubConnector
from rekipedia.connectors.linear_connector import LinearConnector


@runtime_checkable
class BaseConnector(Protocol):
    def fetch_issues(self) -> list[ExternalSource]: ...
    def link_to_symbols(self, sources: list[ExternalSource], store) -> int: ...  # type: ignore[type-arg]


__all__ = ["BaseConnector", "ExternalSource", "GitHubConnector", "LinearConnector"]
