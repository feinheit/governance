"""Policies, a circle's own and those of roles for their domains"""

import click
from rich.markdown import Markdown

from gov.core import (
    cli,
    complete_circles,
    complete_policies,
    console,
    echo_fields,
    echo_json,
    link,
    make_table,
    request,
)


@cli.group(invoke_without_command=True)
@click.option(
    "--circle",
    type=int,
    help="ID of the circle, with its roles' policies.",
    shell_complete=complete_circles,
)
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def policies(ctx, circle, as_json):
    """The active policies, grouped by circle (or role, for its domains)"""
    if ctx.invoked_subcommand is not None:
        return
    data = request("GET", "policies/", params={"circle_id": circle} if circle else {})
    if as_json:
        echo_json(data)
        return
    if not data:
        console.print("No policies.")
        return
    table = make_table("ID>", "Policy…")
    owner = None
    for policy in data:
        if policy["role_id"] != owner:
            owner = policy["role_id"]
            heading = (
                policy["role"]
                if policy["role_id"] == policy["circle_id"]
                else f"{policy['role']} ({policy['circle']})"
            )
            table.add_row("", heading, style="bold")
        table.add_row(link(policy["id"], policy["url"]), f"  {policy['title']}")
    console.print(table)


@policies.command("show")
@click.argument("id", type=int, shell_complete=complete_policies)
@click.option("--json", "as_json", is_flag=True)
def show(id, as_json):
    """A policy with its text"""
    policy = request("GET", f"policies/{id}/")
    if as_json:
        echo_json(policy)
        return
    echo_fields(
        policy["title"],
        [
            ("ID", policy["id"]),
            ("Circle", policy["circle"]),
            (
                "Role",
                policy["role"] if policy["role_id"] != policy["circle_id"] else "",
            ),
            ("Domain", policy["domain"]),
            ("URL", policy["url"]),
        ],
        url=policy["url"],
    )
    if policy["body"]:
        console.print()
        console.print(Markdown(policy["body"]))
