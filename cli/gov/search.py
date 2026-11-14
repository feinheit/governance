"""Searching the governance like the search field of the web interface"""

import click

from gov.core import cli, console, echo_json, link, make_table, request


def _archived(name, item):
    """With the date of archiving or "inactive" (``--archived``)"""
    if item.get("archived_on"):
        return f"{name} (archived on {item['archived_on']})"
    if item.get("is_active") is False:
        return f"{name} (inactive)"
    return name


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
            link(_archived(person["name"], person), person["url"]),
            ", ".join(circle["name"] for circle in person["circles"]),
        ),
    ),
    (
        "roles",
        "Roles",
        ["ID>", "Role"],
        lambda role: (
            link(role["id"], role["url"]),
            link(_archived(role["name"], role), role["url"]),
        ),
    ),
    ("accountabilities", "Accountabilities", ["Text", "Role"], _text),
    ("domains", "Domains", ["Text", "Role"], _text),
    (
        "policies",
        "Policies",
        ["ID>", "Policy", "Role>"],
        lambda policy: (
            link(policy["id"], policy["url"]),
            link(_archived(policy["title"], policy), policy["url"]),
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
    *(
        (
            key,
            title,
            ["ID>", "Description", "Role"],
            lambda item: (str(item["id"]), item["description"], item["role"]),
        )
        for key, title in [
            ("checklist_items", "Checklist items"),
            ("metrics", "Metrics"),
        ]
    ),
]


@cli.command()
@click.argument("terms", nargs=-1, required=True)
@click.option(
    "--archived",
    is_flag=True,
    help="Also archived roles (with their texts, links, notes, checklist"
    " items and metrics), archived policies and inactive people",
)
@click.option("--json", "as_json", is_flag=True)
def search(terms, archived, as_json):
    """People, roles, accountabilities, domains, policies, links, notes,
    checklist items and metrics containing all TERMS (ignoring case and
    accents)"""
    params = {"q": " ".join(terms)}
    if archived:
        params["archived"] = "true"
    data = request("GET", "search/", params=params)
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
