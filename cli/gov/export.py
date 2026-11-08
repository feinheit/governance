"""The whole governance as one Markdown document"""

import click

from gov.core import cli, request


@cli.command()
@click.option(
    "--with-people",
    is_flag=True,
    help="Include who holds the roles (personal data).",
)
@click.option(
    "-o",
    "--output",
    type=click.File("w", encoding="utf-8"),
    default="-",
    help="Write to this file instead of stdout.",
)
def export(with_people, output):
    """The whole current governance as Markdown: circles, roles, their texts,
    policies, metrics, checklist items and links (and who holds the roles,
    if asked for)"""
    data = request("GET", "export/", params={"people": "true"} if with_people else {})
    output.write(data["markdown"])
