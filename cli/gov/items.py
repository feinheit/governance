"""Metrics and checklist items of roles and circles, reported in tactical
meetings: by the role in its circle's (a sub-circle too), a circle's own by
the whole circle in its own"""

import click

from gov.core import cli, complete_roles, console, echo_json, make_table, request


FREQUENCIES = ["weekly", "monthly", "quarterly", "yearly", ""]


def _print(items, empty):
    if not items:
        console.print(empty)
        return
    table = make_table("ID>", "Description", "Frequency", "Reported by", "Link")
    for item in items:
        table.add_row(
            str(item["id"]),
            item["description"],
            item["frequency"],
            f"{item['role']} (whole circle)" if item["whole_circle"] else item["role"],
            item["link"],
        )
    console.print(table)


def _group(name, kind, field, singular, plural, *, who):
    @cli.group(name, help=f"{plural.capitalize()} of roles and circles; {who}")
    def group():
        pass

    @group.command("list")
    @click.argument("role", type=int, shell_complete=complete_roles)
    @click.option("--json", "as_json", is_flag=True)
    def list_(role, as_json):
        data = request("GET", f"roles/{role}/")[field]
        echo_json(data) if as_json else _print(data, f"No {plural}.")

    list_.help = f"The {plural} of the role or circle ROLE (its ID)"

    @group.command("add")
    @click.argument("role", type=int, shell_complete=complete_roles)
    @click.argument("description")
    @click.option("--frequency", type=click.Choice(FREQUENCIES), default="")
    @click.option("--link", default="")
    @click.option(
        "--whole-circle",
        is_flag=True,
        help="A circle's own, reported in its own tactical meetings.",
    )
    @click.option("--json", "as_json", is_flag=True)
    def add(role, description, frequency, link, whole_circle, as_json):
        data = request(
            "POST",
            f"roles/{role}/{kind}/",
            json={
                "description": description,
                "frequency": frequency,
                "link": link,
                "whole_circle": whole_circle,
            },
        )
        echo_json(data) if as_json else _print([data], "")

    add.help = (
        f"Add a {singular} to the role or circle ROLE (its ID), reported by it"
        " in its circle's tactical meetings, or with --whole-circle in its own"
    )

    @group.command("update")
    @click.argument("id", type=int)
    @click.option("--description")
    @click.option("--frequency", type=click.Choice(FREQUENCIES))
    @click.option("--link")
    @click.option(
        "--role",
        type=int,
        shell_complete=complete_roles,
        help="Another role reports it (its ID).",
    )
    @click.option(
        "--whole-circle/--not-whole-circle",
        default=None,
        help="A circle's own, or reported by the circle in its super-circle.",
    )
    @click.option("--json", "as_json", is_flag=True)
    def update(id, description, frequency, link, role, whole_circle, as_json):
        changes = {
            "description": description,
            "frequency": frequency,
            "link": link,
            "role_id": role,
            "whole_circle": whole_circle,
        }
        changes = {key: value for key, value in changes.items() if value is not None}
        if not changes:
            raise click.UsageError(
                "Nothing to change: --description, --frequency, --link, --role"
                " or --whole-circle."
            )
        data = request("PATCH", f"items/{kind}/{id}/", json=changes)
        echo_json(data) if as_json else _print([data], "")

    update.help = f"Change the {singular} ID, only the given fields"

    @group.command("remove")
    @click.argument("id", type=int)
    def remove(id):
        data = request("DELETE", f"items/{kind}/{id}/")
        console.print(f"Removed {data['description']}.", highlight=False)

    remove.help = f"Delete the {singular} ID"
    return group


metrics = _group(
    "metrics",
    "metrics",
    "metrics",
    "metric",
    "metrics",
    who="the Circle Leads of the circle reviewing them change them",
)
checklist = _group(
    "checklist",
    "checklist",
    "checklist_items",
    "checklist item",
    "checklist items",
    who="anybody changes them",
)
