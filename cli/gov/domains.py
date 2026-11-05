"""Domains, with the policies of their roles for them"""

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


@cli.command()
@click.option(
    "--circle",
    type=int,
    help="ID of the circle, with its roles' domains.",
    shell_complete=complete_circles,
)
@click.option("--json", "as_json", is_flag=True)
def domains(circle, as_json):
    """The domains, grouped by circle and role, with their policies"""
    data = request("GET", "domains/", params={"circle_id": circle} if circle else {})
    if as_json:
        echo_json(data)
        return
    if not data:
        console.print("No domains.")
        return
    table = make_table("Domain…", "Policies")
    owner = None
    for domain in data:
        if domain["role_id"] != owner:
            owner = domain["role_id"]
            heading = (
                domain["role"]
                if domain["role_id"] == domain["circle_id"]
                else f"{domain['role']} ({domain['circle']})"
            )
            table.add_row(link(heading, domain["url"]), "", style="bold")
        table.add_row(
            f"  {domain['text']}",
            ", ".join(
                f"{policy['title']} ({policy['id']})" for policy in domain["policies"]
            ),
        )
    console.print(table)
