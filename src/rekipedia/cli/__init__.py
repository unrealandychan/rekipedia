"""rekipedia CLI entry point."""
from __future__ import annotations

import click

from rekipedia.cli.affected import affected_cmd
from rekipedia.cli.ask import ask_cmd
from rekipedia.cli.context import context_cmd
from rekipedia.cli.diff import diff_cmd
from rekipedia.cli.domain import domain_cmd
from rekipedia.cli.embed import embed_cmd
from rekipedia.cli.explain_cmd import explain_cmd
from rekipedia.cli.export import export_cmd
from rekipedia.cli.hook import hook_cmd
from rekipedia.cli.hotspots import hotspots_cmd
from rekipedia.cli.path_cmd import path_cmd
from rekipedia.cli.surprises import surprises_cmd
from rekipedia.cli.git_history import git_history_cmd
from rekipedia.cli.impact import impact_cmd
from rekipedia.cli.init import init_cmd
from rekipedia.cli.install_cmd import install_cmd
from rekipedia.cli.mcp_cmd import mcp_cmd
from rekipedia.cli.merge_cmd import merge_cmd
from rekipedia.cli.merge_driver_cmd import merge_driver_cmd
from rekipedia.cli.note import note_cmd
from rekipedia.cli.onboard import onboard_cmd
from rekipedia.cli.publish import publish_cmd
from rekipedia.cli.pull_cmd import pull_cmd
from rekipedia.cli.refactor import refactor_cmd
from rekipedia.cli.review import review_cmd
from rekipedia.cli.scan import scan_cmd
from rekipedia.cli.search import search_cmd
from rekipedia.cli.serve import serve_cmd
from rekipedia.cli.setup import setup_cmd
from rekipedia.cli.tour import tour_cmd
from rekipedia.cli.update import update_cmd
from rekipedia.cli.watch import watch_cmd


SECTIONS = [
    ("Core", ["scan", "ask", "mcp", "serve"]),
    ("Analysis", ["explain", "path", "hotspots", "surprises", "git-history", "diff", "impact", "refactor", "review"]),
    ("Team sync", ["publish", "export", "merge", "pull", "watch"]),
    ("Setup", ["init", "install", "hook", "embed"]),
]


class SectionedGroup(click.Group):
    """A Click Group that displays commands grouped into named sections."""

    def format_commands(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        # Build a map of command name -> help line
        commands = {}
        for name in self.list_commands(ctx):
            cmd = self.get_command(ctx, name)
            if cmd is None or cmd.hidden:
                continue
            help_text = cmd.get_short_help_str(limit=formatter.width or 80)
            commands[name] = help_text

        # Collect all commands that appear in sections
        sectioned: set[str] = set()
        for _, names in SECTIONS:
            sectioned.update(names)

        # Build section rows
        section_data = []
        for section_name, names in SECTIONS:
            rows = []
            for name in names:
                if name in commands:
                    rows.append((name, commands[name]))
            if rows:
                section_data.append((section_name, rows))

        # Other commands not in any section
        other_rows = [(name, help_text) for name, help_text in commands.items() if name not in sectioned]

        all_sections = section_data
        if other_rows:
            all_sections = all_sections + [("Other", other_rows)]

        for section_name, rows in all_sections:
            with formatter.section(section_name):
                formatter.write_dl(rows)


@click.group(cls=SectionedGroup)
@click.version_option(package_name="rekipedia")
def main() -> None:
    """rekipedia — agentic repo-to-wiki knowledge store."""


main.add_command(init_cmd)
main.add_command(install_cmd)
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
main.add_command(publish_cmd)
main.add_command(merge_cmd)
main.add_command(pull_cmd)
main.add_command(merge_driver_cmd)
main.add_command(hotspots_cmd)
main.add_command(surprises_cmd)
main.add_command(explain_cmd)
main.add_command(path_cmd)
main.add_command(git_history_cmd, name="git-history")
