"""The whole current governance as one Markdown document, or as JSON"""

import json

import click

from gov.core import cli, request


@cli.command()
@click.option(
    "--with-people",
    is_flag=True,
    help="Include who holds the roles (personal data).",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="As JSON: the active roles by ID with everything belonging to them.",
)
@click.option(
    "-o",
    "--output",
    type=click.File("w", encoding="utf-8"),
    default="-",
    help="Write to this file instead of stdout.",
)
def export(with_people, as_json, output):
    """The whole current governance as Markdown: circles, roles, their texts
    and policies (and who holds the roles, if asked for); as JSON also the
    metrics, checklist items and links"""
    params = {"people": "true"} if with_people else {}
    if as_json:
        data = request("GET", "export/json/", params=params)
        output.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        return
    output.write(request("GET", "export/", params=params)["markdown"])
