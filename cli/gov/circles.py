"""Circles, in the organization's order"""

import click

from gov.core import (
    cli,
    complete_circles,
    console,
    echo_json,
    link,
    make_table,
    request,
)
from gov.roles import show_role


@cli.group(invoke_without_command=True)
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def circles(ctx, as_json):
    """The circles; without a command, all of them as a tree"""
    if ctx.invoked_subcommand is not None:
        return
    data = request("GET", "circles/")
    if as_json:
        echo_json(data)
        return
    table = make_table("ID>", "Circle", "Purpose…")
    for circle in data:
        purpose = " ".join(circle["purpose"].split())
        table.add_row(
            link(circle["id"], circle["url"]),
            link("  " * circle["depth"] + circle["name"], circle["url"]),
            purpose,
        )
    console.print(table)


@circles.command("show")
@click.argument("id", type=int, shell_complete=complete_circles)
@click.option("--json", "as_json", is_flag=True)
def show(id, as_json):
    """A circle with its purpose, accountabilities, domains, policies and
    roles"""
    show_role(id, as_json=as_json)
