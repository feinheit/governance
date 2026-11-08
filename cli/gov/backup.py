"""The JSON backup: everything you see, organized by role"""

import json
import re
import unicodedata
from pathlib import Path

import click

from gov.core import cli, echo_json, request


def slug(name):
    ascii = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii.lower()).strip("-") or "role"


def write(path, content):
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(
        json.dumps(content, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
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
    or written into DIRECTORY: a file per role in roles/, meetings.json
    (and people.json)"""
    data = request(
        "GET", "backup/", params={"people": "true"} if with_people else {}, timeout=300
    )
    if directory is None:
        echo_json(data)
        return
    roles = directory / "roles"
    roles.mkdir(parents=True, exist_ok=True)
    # Renamed roles get a new file name: the directory has today's only
    for old in roles.glob("*.json"):
        old.unlink()
    for role in data["roles"]:
        write(roles / f"{role['id']}-{slug(role['name'])}.json", role)
    write(directory / "meetings.json", data["meetings"])
    people = directory / "people.json"
    if "people" in data:
        write(people, data["people"])
    elif people.exists():
        people.unlink()
