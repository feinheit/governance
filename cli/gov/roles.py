"""Roles, also circles"""

import click
from rich.markdown import Markdown
from rich.text import Text

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
    if role["role_leads"]:
        table = make_table("Role Lead", "Focus", "Elected until", title="Role Leads")
        for lead in role["role_leads"]:
            table.add_row(
                link(lead["name"], lead["url"]),
                lead["focus"],
                lead["elected_until"] or "",
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
    Role Leads"""
    show_role(id, as_json=as_json)


def _policy_line(policy, indent=""):
    return Text.assemble(
        f"{indent}- Policy ", link(policy["title"], policy["url"]), f" ({policy['id']})"
    )


def _domain_lines(domain, indent=""):
    yield f"{indent}- Domain: {domain['text']}"
    for policy in domain["policies"]:
        yield _policy_line(policy, indent + "  ")


@roles.command("context")
@click.argument("id", type=int, shell_complete=complete_roles)
@click.option("--json", "as_json", is_flag=True)
def context(id, as_json):
    """The domains and policies affecting a role or circle from outside:
    per circle containing it, outermost first (--json with the policies'
    texts)"""
    circles = request("GET", f"roles/{id}/context/")
    if as_json:
        echo_json(circles)
        return
    for index, circle in enumerate(circles):
        if index:
            console.print()
        console.print(
            Text.assemble(link(circle["name"], circle["url"]), f" ({circle['id']})"),
            style="bold",
        )
        lines = []
        for domain in circle["domains"]:
            lines.extend(_domain_lines(domain))
        lines.extend(_policy_line(policy) for policy in circle["policies"])
        for other in circle["roles"]:
            lines.append(
                Text.assemble(link(other["name"], other["url"]), f" ({other['id']})")
            )
            lines.extend(f"  - Domain: {text}" for text in other["core_domains"])
            for domain in other["domains"]:
                lines.extend(_domain_lines(domain, "  "))
        for line in lines or ["No domains and policies."]:
            console.print(line, highlight=False)
