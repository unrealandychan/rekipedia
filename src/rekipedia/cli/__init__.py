"""rekipedia CLI entry point."""
from __future__ import annotations

import click

from rekipedia.cli.ask import ask_cmd
from rekipedia.cli.embed import embed_cmd
from rekipedia.cli.export import export_cmd
from rekipedia.cli.init import init_cmd
from rekipedia.cli.scan import scan_cmd
from rekipedia.cli.serve import serve_cmd
from rekipedia.cli.update import update_cmd


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
