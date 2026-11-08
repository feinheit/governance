"""The JSON backup: everything you see, organized by role"""

import json
from pathlib import Path

import click

from gov.core import cli, echo_json, request


def write(path, content):
    if not isinstance(content, str):
        content = json.dumps(content, indent=2, sort_keys=True, ensure_ascii=False)
        content += "\n"
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


@cli.command()
@click.argument(
    "directory",
    required=False,
    type=click.Path(file_okay=False, path_type=Path),
)
@click.option(
    "--with-people",
    is_flag=True,
    help="Include the people (personal data); else they're only IDs.",
)
def backup(directory, with_people):
    """Everything you see: the roles (archived ones too) with their texts,
    policies, Role Leads, metrics, checklist items, links, history and
    proposals and meetings, the ad hoc meetings (and the people). Printed,
    or written into DIRECTORY: roles/<ID>.json per role (by ID: renaming a
    role changes one line, git log shows its whole life), meetings.json,
    governance.md (the Markdown export, to read) and people.json. Each run
    replaces them: roles/ only has today's roles, people.json is removed
    without --with-people"""
    params = {"people": "true"} if with_people else {}
    data = request("GET", "backup/", params=params, timeout=300)
    if directory is None:
        echo_json(data)
        return
    # Without the date, which would change it every day
    markdown = request("GET", "export/", params=params | {"dated": "false"})["markdown"]
    roles = directory / "roles"
    roles.mkdir(parents=True, exist_ok=True)
    # Roles are archived, not deleted, but the directory has today's only
    for old in roles.glob("*.json"):
        old.unlink()
    for role in data["roles"]:
        write(roles / f"{role['id']}.json", role)
    write(directory / "meetings.json", data["meetings"])
    write(directory / "governance.md", markdown)
    people = directory / "people.json"
    if "people" in data:
        write(people, data["people"])
    elif people.exists():
        people.unlink()
