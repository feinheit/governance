"""The Holacracy Constitution the app follows"""

import click

from gov.core import cli, request


@cli.command()
@click.option(
    "--language",
    type=click.Choice(["en", "de"]),
    default="en",
    show_default=True,
    help="English or the German translation.",
)
@click.option(
    "-o",
    "--output",
    type=click.File("w", encoding="utf-8"),
    default="-",
    help="Write to this file instead of stdout.",
)
def constitution(language, output):
    """The Holacracy Constitution 5.0 as Markdown"""
    data = request("GET", "constitution/", params={"language": language})
    output.write(data["markdown"])
