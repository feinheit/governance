"""Roles, also circles"""

import click
from rich.markdown import Markdown

from gov.core import (
    cli,
    complete_roles,
    console,
    echo_fields,
    echo_json,
    link,
    make_table,
    request,
)


def show_role(id, *, as_json):
    role = request("GET", f"roles/{id}/")
    if as_json:
        echo_json(role)
        return
    echo_fields(
        role["name"],
        [
            ("ID", role["id"]),
            ("Kind", "circle" if role["is_circle"] else role["core_role"] or "role"),
            ("Circle", role["circle_id"]),
            ("Earlier names", ", ".join(role["other_names"])),
            ("URL", role["url"]),
        ],
        url=role["url"],
    )
    for title, text in [("Purpose", role["purpose"]), ("Strategy", role["strategy"])]:
        if text:
            console.print(f"\n{title}", style="bold")
            console.print(Markdown(text))
    for title, items in [
        ("Domains", role["domains"]),
        ("Accountabilities", role["accountabilities"]),
    ]:
        if items:
            console.print(f"\n{title}", style="bold")
            for item in items:
                console.print(f"- {item['text']}")
    if role["policies"]:
        table = make_table("ID>", "Policy", title="Policies")
        for policy in role["policies"]:
            table.add_row(
                link(policy["id"], policy["url"]), link(policy["title"], policy["url"])
            )
        console.print(table)
    if role["holders"]:
        table = make_table("Holder", "Focus", "Elected until", title="Holders")
        for holder in role["holders"]:
            table.add_row(
                link(holder["name"], holder["url"]),
                holder["focus"],
                holder["elected_until"] or "",
            )
        console.print(table)
    if role["roles"]:
        table = make_table("ID>", "Role", "Kind", title="Roles")
        for sub in role["roles"]:
            kind = "circle" if sub["is_circle"] else sub["core_role"] or ""
            table.add_row(
                link(sub["id"], sub["url"]), link(sub["name"], sub["url"]), kind
            )
        console.print(table)


@cli.group()
def roles():
    """Roles and circles"""


@roles.command("show")
@click.argument("id", type=int, shell_complete=complete_roles)
@click.option("--json", "as_json", is_flag=True)
def show(id, as_json):
    """A role with its purpose, accountabilities, domains, policies and
    holders"""
    show_role(id, as_json=as_json)
