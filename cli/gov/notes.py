"""Notes of roles and circles: what helps doing the role's work, in
Markdown"""

import click
from rich.markdown import Markdown

from gov.core import cli, complete_roles, console, echo_json, link, request


def _print(notes):
    if not notes:
        console.print("No notes.")
        return
    for note in notes:
        console.print(
            f"[bold]{link(note['title'], note['url'])}[/bold] ({note['id']})",
            highlight=False,
        )
        if note["body"]:
            console.print(Markdown(note["body"]))
        console.print()


def _body(body, file):
    if file is not None:
        if body is not None:
            raise click.UsageError("Either --body or --file, not both.")
        return file.read()
    return body


@cli.group()
def notes():
    """Notes of roles and circles; anybody changes them"""


@notes.command("list")
@click.argument("role", type=int, shell_complete=complete_roles)
@click.option("--json", "as_json", is_flag=True)
def list_(role, as_json):
    """The notes of the role or circle ROLE (its ID)"""
    data = request("GET", f"roles/{role}/")["notes"]
    if as_json:
        echo_json(data)
    else:
        _print(data)


@notes.command("add")
@click.argument("role", type=int, shell_complete=complete_roles)
@click.argument("title")
@click.option("--body", help="The text, in Markdown.")
@click.option(
    "--file", type=click.File(encoding="utf-8"), help="The text from a file, - stdin."
)
@click.option("--json", "as_json", is_flag=True)
def add(role, title, body, file, as_json):
    """Add a note to the role or circle ROLE (its ID), after its links and
    notes"""
    data = request(
        "POST",
        f"roles/{role}/notes/",
        json={"title": title, "body": _body(body, file) or ""},
    )
    echo_json(data) if as_json else _print([data])


@notes.command("update")
@click.argument("id", type=int)
@click.option("--title")
@click.option("--body", help="The text, in Markdown.")
@click.option(
    "--file", type=click.File(encoding="utf-8"), help="The text from a file, - stdin."
)
@click.option("--json", "as_json", is_flag=True)
def update(id, title, body, file, as_json):
    """Change the note ID, only the given fields"""
    changes = {"title": title, "body": _body(body, file)}
    changes = {key: value for key, value in changes.items() if value is not None}
    if not changes:
        raise click.UsageError("Nothing to change: --title, --body or --file.")
    data = request("PATCH", f"notes/{id}/", json=changes)
    echo_json(data) if as_json else _print([data])


@notes.command("remove")
@click.argument("id", type=int)
def remove(id):
    """Delete the note ID"""
    data = request("DELETE", f"notes/{id}/")
    console.print(f"Removed {data['title']}.", highlight=False)
