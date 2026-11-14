"""Meetings: reading them, e.g. to turn a tactical meeting's outcomes into
tasks in the task management tool"""

import click
from rich.markdown import Markdown

from gov.core import (
    cli,
    complete_circles,
    console,
    echo_fields,
    echo_json,
    link,
    make_table,
    request,
)


KINDS = ["governance", "tactical", "ad_hoc"]


def _day(value):
    return value[:10] if value else ""


def _person(person):
    return f"{person['name']} <{person['email']}>" if person else ""


@cli.group(invoke_without_command=True)
@click.option(
    "--circle",
    type=int,
    help="ID of the circle or role: its meetings and those it was invited to.",
    shell_complete=complete_circles,
)
@click.option("--kind", type=click.Choice(KINDS))
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def meetings(ctx, circle, kind, as_json):
    """Meetings; without a command the newest 20"""
    if ctx.invoked_subcommand is not None:
        return
    params = {"circle_id": circle, "kind": kind}
    data = request("GET", "meetings/", params={k: v for k, v in params.items() if v})
    if as_json:
        echo_json(data)
        return
    if not data:
        console.print("No meetings.")
        return
    table = make_table("ID>", "Meeting…", "Started", "Ended", "Outcomes>")
    for meeting in data:
        table.add_row(
            link(meeting["id"], meeting["url"]),
            link(meeting["title"], meeting["url"]),
            _day(meeting["started_at"]),
            "running" if meeting["is_running"] else _day(meeting["ended_at"]),
            str(meeting["outcomes"]),
        )
    console.print(table)


@meetings.command("show")
@click.argument("id", type=int)
@click.option("--json", "as_json", is_flag=True)
def show(id, as_json):
    """A meeting with its agenda items, their outcomes and links, the roles
    the outcomes mention with their Role Leads, the links of the circle and
    the invited roles, and its outputs"""
    meeting = request("GET", f"meetings/{id}/")
    if as_json:
        echo_json(meeting)
        return
    echo_fields(
        meeting["title"],
        [
            ("ID", meeting["id"]),
            ("Started", _day(meeting["started_at"])),
            (
                "Ended",
                "running" if meeting["is_running"] else _day(meeting["ended_at"]),
            ),
            ("Secretary", meeting["secretary"] or ""),
            ("Attendees", ", ".join(p["name"] for p in meeting["attendees"])),
            ("Invited", ", ".join(r["title"] for r in meeting["invited_roles"])),
            ("URL", meeting["url"]),
        ],
        url=meeting["url"],
    )
    if meeting["items"]:
        console.print("\nAgenda", style="bold")
        for item in meeting["items"]:
            owner = f" ({item['owner']['name']})" if item["owner"] else ""
            console.print(f"* {item['label']}{owner}", highlight=False)
            if item["outcome_plain"]:
                console.print(f"  {item['outcome_plain']}", highlight=False)
            for role in item["roles"]:
                leads = ", ".join(_person(p) for p in role["role_leads"]) or "unfilled"
                console.print(f"  @{role['name']}: {leads}", highlight=False)
            if item["link"]:
                console.print(f"  {item['link']}", highlight=False)
    if meeting["links"]:
        console.print("\nLinks", style="bold")
        for item in meeting["links"]:
            console.print(
                f"* {item['role']}: {link(item['title'], item['url'])} {item['url']}",
                highlight=False,
            )
    for key, label in [("adopted", "Adopted"), ("withdrawn", "Withdrawn")]:
        if meeting[key]:
            console.print(f"\n{label}", style="bold")
            for proposal in meeting[key]:
                console.print(f"* {proposal['title']} ({proposal['id']})")
    if meeting["elections"]:
        console.print("\nElections", style="bold")
        for election in meeting["elections"]:
            who = election["person"] or "nobody"
            until = f" until {election['term_ends_on']}" if election["person"] else ""
            console.print(f"* {election['role']}: {who}{until}", highlight=False)
    if meeting["minutes"]:
        console.print("\nNotes", style="bold")
        console.print(Markdown(meeting["minutes"]))
