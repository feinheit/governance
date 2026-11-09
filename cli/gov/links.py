"""Links of roles and circles to external tools, e.g. where the projects
are managed"""

import click

from gov.core import cli, complete_roles, console, echo_json, link, make_table, request


def _print(links):
    if not links:
        console.print("No links.")
        return
    table = make_table("ID>", "Title", "URL", "Description")
    for item in links:
        table.add_row(
            str(item["id"]),
            link(item["title"], item["url"]),
            item["url"],
            item["description"],
        )
    console.print(table)


@cli.group()
def links():
    """Links of roles and circles to other tools; anybody changes them"""


@links.command("list")
@click.argument("role", type=int, shell_complete=complete_roles)
@click.option("--json", "as_json", is_flag=True)
def list_(role, as_json):
    """The links of the role or circle ROLE (its ID)"""
    data = request("GET", f"roles/{role}/")["links"]
    if as_json:
        echo_json(data)
    else:
        _print(data)


@links.command("add")
@click.argument("role", type=int, shell_complete=complete_roles)
@click.argument("title")
@click.argument("url")
@click.option("--description", default="")
@click.option("--json", "as_json", is_flag=True)
def add(role, title, url, description, as_json):
    """Add a link to the role or circle ROLE (its ID), after its others"""
    data = request(
        "POST",
        f"roles/{role}/links/",
        json={"title": title, "url": url, "description": description},
    )
    echo_json(data) if as_json else _print([data])


@links.command("update")
@click.argument("id", type=int)
@click.option("--title")
@click.option("--url")
@click.option("--description")
@click.option("--json", "as_json", is_flag=True)
def update(id, title, url, description, as_json):
    """Change the link ID, only the given fields"""
    changes = {"title": title, "url": url, "description": description}
    changes = {key: value for key, value in changes.items() if value is not None}
    if not changes:
        raise click.UsageError("Nothing to change: --title, --url or --description.")
    data = request("PATCH", f"links/{id}/", json=changes)
    echo_json(data) if as_json else _print([data])


@links.command("remove")
@click.argument("id", type=int)
def remove(id):
    """Delete the link ID"""
    data = request("DELETE", f"links/{id}/")
    console.print(f"Removed {data['title']} ({data['url']}).", highlight=False)
