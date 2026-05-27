"""`reki connect` command — connect external data sources to rekipedia."""
from __future__ import annotations

import os
from pathlib import Path

import click
from rich.console import Console

from rekipedia.config.loader import load_config
from rekipedia.connectors.github_connector import (
    AuthError,
    GitHubConnector,
    RateLimitError,
    RepoNotFoundError,
    _detect_repo_from_git,
)
from rekipedia.connectors.linear_connector import (
    LinearAuthError,
    LinearAPIError,
    LinearConnector,
    LinearRateLimitError,
)
from rekipedia.storage.sqlite_store import SqliteStore

console = Console()


@click.group("connect")
def connect_cmd() -> None:
    """Connect external data sources (GitHub, Jira, etc.) to rekipedia."""


@connect_cmd.command("github")
@click.argument("repo_path", default=".", type=click.Path(exists=True, file_okay=False))
@click.option("--repo", default=None, help="GitHub repo in owner/repo format.")
@click.option("--token", default=None, help="GitHub personal access token (not saved to config).")
@click.option("--max-issues", default=None, type=int, help="Max issues to fetch.")
@click.option("--max-prs", default=None, type=int, help="Max PRs to fetch.")
def github_cmd(
    repo_path: str,
    repo: str | None,
    token: str | None,
    max_issues: int | None,
    max_prs: int | None,
) -> None:
    """Index GitHub Issues and PR comments for the current repo.

    Token read order: --token flag → REKIPEDIA_GITHUB_TOKEN env var → config file.
    Token is never stored in the database or displayed in logs.

    Examples:

    \b
        reki connect github
        reki connect github --repo owner/repo
        reki connect github --token ghp_xxx
        reki connect github --max-issues 200
    """
    root = Path(repo_path).resolve()
    output_dir = root / ".rekipedia"
    db_path = output_dir / "store.db"

    # Load config
    cfg = load_config(root)
    github_cfg = cfg.get("connectors", {}).get("github", {})

    # Token resolution: flag > env var > config
    resolved_token = token or os.environ.get("REKIPEDIA_GITHUB_TOKEN") or github_cfg.get("token") or None
    if resolved_token == "":
        resolved_token = None

    # Repo resolution: flag > config > git remote
    resolved_repo = repo or github_cfg.get("repo") or ""
    if not resolved_repo:
        resolved_repo = _detect_repo_from_git(str(root)) or ""

    if not resolved_repo:
        console.print(
            "[red]✗[/red] Could not determine GitHub repo. "
            "Pass --repo owner/repo or set [connectors.github] repo in config."
        )
        raise SystemExit(1)

    # Cap resolution
    resolved_max_issues = max_issues or github_cfg.get("max_issues", 500)
    resolved_max_prs = max_prs or github_cfg.get("max_prs", 200)

    connector = GitHubConnector(
        repo=resolved_repo,
        token=resolved_token,
        max_issues=resolved_max_issues,
        max_prs=resolved_max_prs,
    )

    # ------------------------------------------------------------------
    # Fetch issues
    # ------------------------------------------------------------------
    issues: list = []
    with console.status(f"🔗 Fetching GitHub issues… (0/{resolved_max_issues})") as status:
        def _issue_progress(kind: str, cur: int, total: int) -> None:
            status.update(f"🔗 Fetching GitHub issues… ({cur}/{total})")

        connector._progress = _issue_progress  # type: ignore[assignment]
        try:
            issues = connector.fetch_issues()
        except RateLimitError as exc:
            console.print(f"[yellow]⚠[/yellow]  Rate limit hit while fetching issues: {exc}")
            console.print("[yellow]⚠[/yellow]  Continuing with partial results.")
        except RepoNotFoundError as exc:
            console.print(f"[red]✗[/red] {exc}")
            if not resolved_token:
                console.print(
                    "[red]✗[/red] This may be a private repo — set REKIPEDIA_GITHUB_TOKEN or pass --token."
                )
            raise SystemExit(1)
        except AuthError as exc:
            console.print(f"[red]✗[/red] {exc}")
            raise SystemExit(1)

    # ------------------------------------------------------------------
    # Fetch PRs
    # ------------------------------------------------------------------
    prs: list = []
    with console.status(f"🔗 Fetching GitHub PRs… (0/{resolved_max_prs})") as status:
        def _pr_progress(kind: str, cur: int, total: int) -> None:
            status.update(f"🔗 Fetching GitHub PRs… ({cur}/{total})")

        connector._progress = _pr_progress  # type: ignore[assignment]
        try:
            prs = connector.fetch_prs()
        except RateLimitError as exc:
            console.print(f"[yellow]⚠[/yellow]  Rate limit hit while fetching PRs: {exc}")
            console.print("[yellow]⚠[/yellow]  Continuing with partial results.")
        except RepoNotFoundError as exc:
            console.print(f"[red]✗[/red] {exc}")
            if not resolved_token:
                console.print(
                    "[red]✗[/red] This may be a private repo — set REKIPEDIA_GITHUB_TOKEN or pass --token."
                )
            raise SystemExit(1)
        except AuthError as exc:
            console.print(f"[red]✗[/red] {exc}")
            raise SystemExit(1)

    all_sources = issues + prs

    # ------------------------------------------------------------------
    # Store sources
    # ------------------------------------------------------------------
    with console.status("🔗 Cross-referencing symbols… "):
        with SqliteStore(db_path) as store:
            # Get all symbols for cross-referencing
            run_id = store.get_latest_run_id(str(root))
            all_symbols: list[dict] = []
            if run_id:
                all_symbols = store.get_all_symbols(run_id)

            # Store sources
            store.store_external_sources([s.to_dict() for s in all_sources])

            # Build & store symbol links
            links = connector.build_symbol_links(all_sources, all_symbols)
            if links:
                store.store_source_symbol_links(links)

    console.print(
        f"[green]✓[/green] Indexed {len(issues)} issues, {len(prs)} PRs "
        f"— {len(links)} symbol links created"
    )


@connect_cmd.command("linear")
@click.argument("repo_path", default=".", type=click.Path(exists=True, file_okay=False))
@click.option("--api-key", default=None, help="Linear API key (not saved to config).")
@click.option("--team-id", default=None, help="Linear team ID to filter issues.")
@click.option("--max-issues", default=None, type=int, help="Max issues to fetch.")
def linear_cmd(
    repo_path: str,
    api_key: str | None,
    team_id: str | None,
    max_issues: int | None,
) -> None:
    """Index Linear issues for the current repo.

    Token read order: --api-key flag → REKIPEDIA_LINEAR_API_KEY env var → config file.
    API key is never stored in the database or displayed in logs.

    Examples:

    \\b
        reki connect linear
        reki connect linear --api-key lin_api_xxx
        reki connect linear --team-id TEAM_ID
        reki connect linear --max-issues 200
    """
    root = Path(repo_path).resolve()
    output_dir = root / ".rekipedia"
    db_path = output_dir / "store.db"

    cfg = load_config(root)
    linear_cfg = cfg.get("connectors", {}).get("linear", {})

    # Token resolution: flag > env var > config
    resolved_key = api_key or os.environ.get("REKIPEDIA_LINEAR_API_KEY") or linear_cfg.get("api_key") or None
    if resolved_key == "":
        resolved_key = None

    if not resolved_key:
        console.print(
            "[red]✗[/red] No Linear API key found. "
            "Pass --api-key or set REKIPEDIA_LINEAR_API_KEY."
        )
        raise SystemExit(1)

    resolved_team_id = team_id or linear_cfg.get("team_id") or None
    if resolved_team_id == "":
        resolved_team_id = None

    resolved_max = max_issues or linear_cfg.get("max_issues", 500)

    connector = LinearConnector(
        api_key=resolved_key,
        team_id=resolved_team_id,
        max_issues=resolved_max,
    )

    issues: list = []
    with console.status(f"🔗 Fetching Linear issues… (0/{resolved_max})") as status:
        def _progress(cur: int, total: int) -> None:
            status.update(f"🔗 Fetching Linear issues… ({cur}/{total})")

        connector._progress = _progress  # type: ignore[assignment]
        try:
            issues = connector.fetch_issues()
        except LinearRateLimitError as exc:
            console.print(f"[yellow]⚠[/yellow]  Rate limit hit: {exc}")
            console.print("[yellow]⚠[/yellow]  Continuing with partial results.")
        except LinearAuthError as exc:
            console.print(f"[red]✗[/red] {exc}")
            raise SystemExit(1)
        except LinearAPIError as exc:
            console.print(f"[red]✗[/red] {exc}")
            raise SystemExit(1)

    link_count = 0
    with console.status("🔗 Cross-referencing symbols… "):
        with SqliteStore(db_path) as store:
            run_id = store.get_latest_run_id(str(root))
            all_symbols: list[dict] = []
            if run_id:
                all_symbols = store.get_all_symbols(run_id)

            store.store_external_sources([s.to_dict() for s in issues])
            links = connector.build_symbol_links(issues, all_symbols)
            if links:
                store.store_source_symbol_links(links)
            link_count = len(links)

    console.print(
        f"[green]✓[/green] Indexed {len(issues)} Linear issues "
        f"— {link_count} symbol links created"
    )
