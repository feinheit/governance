"""The whole governance as one Markdown document"""

import click

from gov.core import cli, request


@cli.command()
@click.option(
    "--without-holders",
    is_flag=True,
    help="Leave out who holds the roles, e.g. to share it outside.",
)
@click.option(
    "-o",
    "--output",
    type=click.File("w", encoding="utf-8"),
    default="-",
    help="Write to this file instead of stdout.",
)
def export(without_holders, output):
    """The whole current governance as Markdown: circles, roles, policies
    (and who holds the roles)"""
    data = request(
        "GET", "export/", params={"holders": "false"} if without_holders else {}
    )
    output.write(data["markdown"])
