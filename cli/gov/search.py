"""Searching the governance like the search field of the web interface"""

import click

from gov.core import cli, console, echo_json, link, make_table, request


@cli.command()
@click.argument("terms", nargs=-1, required=True)
@click.option("--json", "as_json", is_flag=True)
def search(terms, as_json):
    """People, roles, accountabilities, domains, policies and links
    containing all TERMS (ignoring case and accents)"""
    data = request("GET", "search/", params={"q": " ".join(terms)})
    if as_json:
        echo_json(data)
        return
    if not any(data.values()):
        console.print("Nothing found.")
        return
    if data.get("people"):
        table = make_table("ID>", "Name", "Circles", title="People")
        for person in data["people"]:
            table.add_row(
                link(person["id"], person["url"]),
                link(person["name"], person["url"]),
                ", ".join(circle["name"] for circle in person["circles"]),
            )
        console.print(table)
    if data["roles"]:
        table = make_table("ID>", "Role", title="Roles")
        for role in data["roles"]:
            table.add_row(
                link(role["id"], role["url"]), link(role["name"], role["url"])
            )
        console.print(table)
    for key, title in [
        ("accountabilities", "Accountabilities"),
        ("domains", "Domains"),
    ]:
        if data[key]:
            table = make_table("Text", "Role", title=title)
            for item in data[key]:
                table.add_row(item["text"], link(item["role"], item["url"]))
            console.print(table)
    if data["policies"]:
        table = make_table("ID>", "Policy", "Role>", title="Policies")
        for policy in data["policies"]:
            table.add_row(
                link(policy["id"], policy["url"]),
                link(policy["title"], policy["url"]),
                str(policy["role_id"]),
            )
        console.print(table)
    # Missing in the answers of older servers
    if data.get("links"):
        table = make_table("Link", "Description", "Role", title="Links")
        for item in data["links"]:
            table.add_row(
                link(item["title"], item["url"]),
                item["description"],
                link(item["role"], item["role_url"]),
            )
        console.print(table)
