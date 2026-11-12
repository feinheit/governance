"""Searching the governance like the search field of the web interface"""

import click

from gov.core import cli, console, echo_json, link, make_table, request


def _text(item):
    return item["text"], link(item["role"], item["url"])


# Key, title, columns and the row of an item
TABLES = [
    (
        "people",
        "People",
        ["ID>", "Name", "Circles"],
        lambda person: (
            link(person["id"], person["url"]),
            link(person["name"], person["url"]),
            ", ".join(circle["name"] for circle in person["circles"]),
        ),
    ),
    (
        "roles",
        "Roles",
        ["ID>", "Role"],
        lambda role: (link(role["id"], role["url"]), link(role["name"], role["url"])),
    ),
    ("accountabilities", "Accountabilities", ["Text", "Role"], _text),
    ("domains", "Domains", ["Text", "Role"], _text),
    (
        "policies",
        "Policies",
        ["ID>", "Policy", "Role>"],
        lambda policy: (
            link(policy["id"], policy["url"]),
            link(policy["title"], policy["url"]),
            str(policy["role_id"]),
        ),
    ),
    (
        "links",
        "Links",
        ["Link", "Description", "Role"],
        lambda item: (
            link(item["title"], item["url"]),
            item["description"],
            link(item["role"], item["role_url"]),
        ),
    ),
    (
        "notes",
        "Notes",
        ["Note", "Role"],
        lambda note: (link(note["title"], note["url"]), note["role"]),
    ),
]


@cli.command()
@click.argument("terms", nargs=-1, required=True)
@click.option("--json", "as_json", is_flag=True)
def search(terms, as_json):
    """People, roles, accountabilities, domains, policies, links and notes
    containing all TERMS (ignoring case and accents)"""
    data = request("GET", "search/", params={"q": " ".join(terms)})
    if as_json:
        echo_json(data)
        return
    if not any(data.values()):
        console.print("Nothing found.")
        return
    for key, title, columns, row in TABLES:
        # .get(): older servers miss some
        if data.get(key):
            table = make_table(*columns, title=title)
            for item in data[key]:
                table.add_row(*row(item))
            console.print(table)
