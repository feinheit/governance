"""The circles' tension inboxes: tensions for the circle's next meeting,
its members see them; their owners or the secretary put them on the agenda
in the meeting"""

import click
from rich.markdown import Markdown
from rich.style import Style
from rich.text import Text

from gov.core import cli, complete_circles, console, echo_json, request


def _title(tension):
    # gov's console has no markup: the title as Text, linked and bold
    return Text(tension["title"], style=Style(bold=True, link=tension["url"]))


def _description(description, file):
    if file is not None:
        if description is not None:
            raise click.UsageError("Either --description or --file, not both.")
        return file.read()
    return description


@cli.group()
def tensions():
    """The circles' tension inboxes, for their members (private tensions
    only for their owners)"""


@tensions.command("list")
@click.argument("circle", type=int, shell_complete=complete_circles)
@click.option("--json", "as_json", is_flag=True)
def list_(circle, as_json):
    """The tensions in the inbox of CIRCLE (its ID)"""
    data = request("GET", f"roles/{circle}/tensions/")
    if as_json:
        echo_json(data)
        return
    if not data:
        console.print("The inbox is empty.")
        return
    for tension in data:
        console.print(
            Text.assemble(
                _title(tension),
                f" – {tension['owner']['name']} ({tension['id']})",
                " private" if tension["is_private"] else "",
            )
        )
        if tension["description"]:
            console.print(Markdown(tension["description"]))
        console.print()


@tensions.command("add")
@click.argument("circle", type=int, shell_complete=complete_circles)
@click.argument("title")
@click.option("--description", help="What it's about, in Markdown.")
@click.option(
    "--file",
    type=click.File(encoding="utf-8"),
    help="The description from a file, - stdin.",
)
@click.option(
    "--private", is_flag=True, help="Only you see it, you put it on the agenda."
)
@click.option("--json", "as_json", is_flag=True)
def add(circle, title, description, file, private, as_json):
    """Add a tension of yours to the inbox of CIRCLE (its ID); TITLE in a
    few words, like on the agenda"""
    data = request(
        "POST",
        f"roles/{circle}/tensions/",
        json={
            "title": title,
            "description": _description(description, file) or "",
            "is_private": private,
        },
    )
    if as_json:
        echo_json(data)
    else:
        console.print(Text.assemble(f"Added tension {data['id']} ", _title(data), "."))


@tensions.command("update")
@click.argument("id", type=int)
@click.option("--title")
@click.option("--description", help="What it's about, in Markdown.")
@click.option(
    "--file",
    type=click.File(encoding="utf-8"),
    help="The description from a file, - stdin.",
)
@click.option(
    "--private/--public",
    default=None,
    help="Only you see it, or the circle's members.",
)
@click.option("--json", "as_json", is_flag=True)
def update(id, title, description, file, private, as_json):
    """Change your tension ID while it's in the inbox, only the given
    fields"""
    changes = {
        "title": title,
        "description": _description(description, file),
        "is_private": private,
    }
    changes = {key: value for key, value in changes.items() if value is not None}
    if not changes:
        raise click.UsageError(
            "Nothing to change: --title, --description, --file or --private."
        )
    data = request("PATCH", f"tensions/{id}/", json=changes)
    if as_json:
        echo_json(data)
    else:
        console.print(
            Text.assemble(f"Changed tension {data['id']} ", _title(data), ".")
        )


@tensions.command("remove")
@click.argument("id", type=int)
def remove(id):
    """Delete your tension ID while it's in the inbox"""
    data = request("DELETE", f"tensions/{id}/")
    console.print(f"Removed {data['title']}.", highlight=False)
