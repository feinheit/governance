#!/usr/bin/env python3
"""GlassFrog's projects as to-do lists, one Markdown file per circle.

    python3 -I scripts/export_glassfrog_projects.py EXPORT OUTPUT [--done]

``EXPORT`` is the GlassFrog export (``projects.json``), ``OUTPUT`` a new
directory. The app doesn't take over projects (see SPEC.md); the files are
a copy to read and to import into a task management tool: most to-do list
imports take Markdown, bullets become to-dos and checked ones completed.
They carry no assignees, so the person, the status and the note are part
of each to-do's text. Projects are grouped by role, those without a role
(GlassFrog's individual actions) last. Done projects only with ``--done``.

GlassFrog's API has no actions and no archived projects; copy those by
hand.
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path


STATUSES = ["Current", "Waiting", "Future", "Done"]


def one_line(text):
    return " ".join((text or "").split())


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "circle"


def todo(project, people):
    parts = [one_line(project["description"]) or "(no description)"]
    details = []
    if person := people.get(project["links"]["person"]):
        details.append(person)
    if project["status"] not in {"Current", "Done"}:
        details.append(project["status"])
    if details:
        parts.append(f"({', '.join(details)})")
    if note := one_line(project.get("note")):
        parts.append(f"– {note}")
    if link := one_line(project.get("link")):
        parts.append(f"– {link}")
    check = "x" if project["status"] == "Done" else " "
    return f"- [{check}] {' '.join(parts)}"


def circle_markdown(circle, projects, roles, people):
    by_role = defaultdict(list)
    for project in projects:
        by_role[project["links"]["role"]].append(project)
    lines = [f"# {circle}", ""]
    # By name, those without a role last
    for role in sorted(
        by_role, key=lambda role: (role is None, roles.get(role, "").lower())
    ):
        title = (
            "Without a role"
            if role is None
            else roles.get(role, f"Role {role} (removed)")
        )
        lines += [f"## {title}", ""]
        lines += [
            todo(project, people)
            for project in sorted(
                by_role[role],
                key=lambda p: (STATUSES.index(p["status"]), p["created_at"]),
            )
        ]
        lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("export", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--done", action="store_true", help="include done projects")
    args = parser.parse_args()

    data = json.loads((args.export / "projects.json").read_text())
    linked = data["linked"]
    circles = {circle["id"]: circle["name"] for circle in linked["circles"]}
    roles = {role["id"]: role["name"] for role in linked["roles"]}
    people = {person["id"]: person["name"] for person in linked["people"]}

    by_circle = defaultdict(list)
    for project in data["projects"]:
        if project["status"] == "Done" and not args.done:
            continue
        by_circle[project["links"]["circle"]].append(project)

    args.output.mkdir(parents=True, exist_ok=False)
    for circle_id, projects in sorted(
        by_circle.items(), key=lambda item: circles.get(item[0], "").lower()
    ):
        name = circles.get(circle_id, f"Circle {circle_id}")
        path = args.output / f"{slug(name)}-{circle_id}.md"
        path.write_text(circle_markdown(name, projects, roles, people))
        print(f"{path}: {len(projects)} projects", file=sys.stderr)


if __name__ == "__main__":
    main()
