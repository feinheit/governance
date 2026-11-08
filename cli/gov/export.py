"""The whole governance as one Markdown document, or the JSON backup"""

import json

import click

from gov.core import cli, request


@cli.command()
@click.option(
    "--with-holders",
    is_flag=True,
    help="Include who holds the roles (personal data).",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="The JSON backup instead: everything you see, one key per file,"
    " also the people.",
)
@click.option(
    "-o",
    "--output",
    type=click.File("w", encoding="utf-8"),
    default="-",
    help="Write to this file instead of stdout.",
)
def export(with_holders, as_json, output):
    """The whole current governance as Markdown: circles, roles, policies
    (and who holds the roles, if asked for); with --json everything, also
    the people, proposals, meetings and the history"""
    if as_json:
        if with_holders:
            raise click.UsageError("The JSON backup always has the holders.")
        files = request("GET", "backup/", timeout=300)
        output.write(json.dumps(files, indent=2, ensure_ascii=False) + "\n")
        return
    data = request("GET", "export/", params={"holders": "true"} if with_holders else {})
    output.write(data["markdown"])
