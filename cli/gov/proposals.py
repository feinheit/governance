"""Proposals: reading them, preparing drafts and publishing them

Drafts take GlassFrog's instructions (see SPEC.md), e.g. written by an LLM
from a tension; the server checks them and lists the problems."""

import click
from rich.markdown import Markdown

from gov.core import (
    cli,
    console,
    echo_fields,
    echo_json,
    link,
    load,
    make_table,
    request,
    text_or_stdin,
)


STATUSES = ["draft", "published", "in_meeting", "adopted", "withdrawn"]
# The labels of changes are in the user's language, the actions aren't
ACTIONS = {"added": "+", "removed": "-", "changed": "~", "moved": "→", "elected": "*"}


def _day(value):
    return value[:10] if value else ""


def echo_proposal(proposal):
    echo_fields(
        proposal["title"],
        [
            ("ID", proposal["id"]),
            ("Circle", f"{proposal['circle']} ({proposal['circle_id']})"),
            ("Proposer", proposal["proposer"]),
            ("Status", proposal["status"]),
            ("Kind", proposal["kind"] if proposal["kind"] != "governance" else ""),
            ("Published", _day(proposal["published_at"])),
            (
                "Deadline",
                _day(proposal["deadline"]) if proposal["status"] == "published" else "",
            ),
            ("Decided", _day(proposal["decided_at"])),
            ("URL", proposal["url"]),
        ],
        url=proposal["url"],
    )
    if proposal["tension"]:
        console.print("\nTension", style="bold")
        console.print(Markdown(proposal["tension"]))
    if proposal["changes"]:
        console.print("\nChanges", style="bold")
        for change in proposal["changes"]:
            symbol = ACTIONS.get(change["action"], "·")
            console.print(
                f"{symbol} {change['label']}: {change['subject']}".rstrip(": ")
            )
            if change["old"]:
                console.print(f"    - {change['old']}", style="red")
            if change["new"]:
                console.print(f"    + {change['new']}", style="green")
            for label, text in change["details"]:
                console.print(f"    {label}: {text}")
    if proposal["problems"]:
        console.print("\nProblems", style="bold yellow")
        for problem in proposal["problems"]:
            console.print(f"- {problem}", style="yellow")


@cli.group(invoke_without_command=True)
@click.option("--circle", type=int, help="ID of the circle.")
@click.option("--status", type=click.Choice(STATUSES))
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def proposals(ctx, circle, status, as_json):
    """Proposals; without a command the newest 100, without others' drafts"""
    if ctx.invoked_subcommand is not None:
        return
    params = {"circle_id": circle, "status": status}
    data = request("GET", "proposals/", params={k: v for k, v in params.items() if v})
    if as_json:
        echo_json(data)
        return
    if not data:
        console.print("No proposals.")
        return
    table = make_table("ID>", "Proposal…", "Circle", "Proposer", "Status")
    for proposal in data:
        table.add_row(
            link(proposal["id"], proposal["url"]),
            link(proposal["title"], proposal["url"]),
            proposal["circle"],
            proposal["proposer"] or "",
            proposal["status"],
        )
    console.print(table)


@proposals.command("show")
@click.argument("id", type=int)
@click.option("--json", "as_json", is_flag=True)
def show(id, as_json):
    """A proposal with its tension and changes (and its problems if it's
    your draft)"""
    proposal = request("GET", f"proposals/{id}/")
    echo_json(proposal) if as_json else echo_proposal(proposal)


def _instructions(path):
    """Instructions from a YAML or JSON file (- for stdin): a list, or a
    mapping with them in ``instructions``"""
    data = load(click.open_file(path))
    if isinstance(data, dict):
        data = data.get("instructions")
    if not isinstance(data, list):
        raise click.BadParameter(
            "expected a list of instructions", param_hint="--instructions"
        )
    return data


@proposals.command("create")
@click.option("--circle", type=int, required=True, help="ID of the circle.")
@click.option(
    "--role",
    type=int,
    required=True,
    help="ID of your role with the tension, see `gov me`.",
)
@click.option("--tension", required=True, help="The tension, Markdown; - for stdin.")
@click.option(
    "--instructions",
    type=click.Path(allow_dash=True),
    help="YAML or JSON file with the instructions; - for stdin.",
)
@click.option("--json", "as_json", is_flag=True)
def create(circle, role, tension, instructions, as_json):
    """Create a draft (without instructions it's a tension)"""
    proposal = request(
        "POST",
        "proposals/",
        json={
            "circle_id": circle,
            "role_id": role,
            "tension": text_or_stdin(tension),
            "instructions": _instructions(instructions) if instructions else [],
        },
    )
    echo_json(proposal) if as_json else echo_proposal(proposal)


@proposals.command("update")
@click.argument("id", type=int)
@click.option("--tension", help="The tension, Markdown; - for stdin.")
@click.option(
    "--instructions",
    type=click.Path(allow_dash=True),
    help="YAML or JSON file with the instructions, replacing the draft's; - for stdin.",
)
@click.option("--json", "as_json", is_flag=True)
def update(id, tension, instructions, as_json):
    """Change your draft's tension or instructions"""
    data = {}
    if tension is not None:
        data["tension"] = text_or_stdin(tension)
    if instructions:
        data["instructions"] = _instructions(instructions)
    if not data:
        raise click.UsageError("Nothing to change, use --tension or --instructions.")
    proposal = request("PATCH", f"proposals/{id}/", json=data)
    echo_json(proposal) if as_json else echo_proposal(proposal)


@proposals.command("publish")
@click.argument("id", type=int)
def publish(id):
    """Publish your draft for the async process; the circle's members get a
    mail"""
    proposal = request("POST", f"proposals/{id}/publish/")
    if proposal["status"] == "adopted":
        # Nobody else is in the circle
        console.print("Adopted:", link(proposal["url"], proposal["url"]))
    else:
        console.print("Published:", link(proposal["url"], proposal["url"]))
