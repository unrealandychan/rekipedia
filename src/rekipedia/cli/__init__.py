"""rekipedia CLI entry point."""
from __future__ import annotations

import click

from rekipedia.cli.affected import affected_cmd
from rekipedia.cli.connect import connect_cmd
from rekipedia.cli.ask import ask_cmd
from rekipedia.cli.context import context_cmd
from rekipedia.cli.diff import diff_cmd
from rekipedia.cli.domain import domain_cmd
from rekipedia.cli.embed import embed_cmd
from rekipedia.cli.export import export_cmd
from rekipedia.cli.hook import hook_cmd
from rekipedia.cli.impact import impact_cmd
from rekipedia.cli.init import init_cmd
from rekipedia.cli.mcp_cmd import mcp_cmd
from rekipedia.cli.note import note_cmd
from rekipedia.cli.onboard import onboard_cmd
from rekipedia.cli.refactor import refactor_cmd
from rekipedia.cli.review import review_cmd
from rekipedia.cli.scan import scan_cmd
from rekipedia.cli.search import search_cmd
from rekipedia.cli.serve import serve_cmd
from rekipedia.cli.setup import setup_cmd
from rekipedia.cli.tour import tour_cmd
from rekipedia.cli.update import update_cmd
from rekipedia.cli.watch import watch_cmd


@click.group()
@click.version_option(package_name="rekipedia")
def main() -> None:
    """rekipedia — agentic repo-to-wiki knowledge store."""


main.add_command(init_cmd)
main.add_command(scan_cmd)
main.add_command(update_cmd)
main.add_command(ask_cmd)
main.add_command(embed_cmd)
main.add_command(export_cmd)
main.add_command(serve_cmd)
main.add_command(hook_cmd, name="hook")
main.add_command(context_cmd)
main.add_command(diff_cmd)
main.add_command(impact_cmd)
main.add_command(affected_cmd)
main.add_command(mcp_cmd)
main.add_command(watch_cmd)
main.add_command(search_cmd)
main.add_command(refactor_cmd)
main.add_command(note_cmd)
main.add_command(review_cmd)
main.add_command(setup_cmd)
main.add_command(domain_cmd)
main.add_command(tour_cmd)
main.add_command(onboard_cmd)
main.add_command(connect_cmd)
