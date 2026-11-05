#!/usr/bin/env python3
"""Daily GlassFrog snapshot: fetches the API and commits the JSON files.

Run from the directory containing the ``glassfrog/`` checkout, with the API
token in ``GLASSFROG_TOKEN``. Files are only replaced when every request
succeeded, so a failed fetch doesn't commit empty files.
"""

import datetime as dt
import json
import os
import subprocess
import urllib.request
from pathlib import Path


REPO = Path("glassfrog")
API = "https://api.glassfrog.com/api/v3/"
ENDPOINTS = {
    # The original snapshot, kept under its old name.
    "glassfrog.json": "circles?include=members",
    # Roles with the texts of accountabilities and domains.
    "roles.json": "roles",
    "assignments.json": "assignments",
    "policies.json": "policies",
    # Governance history: proposals with their instructions, tensions,
    # meetings and their agenda items.
    "proposals.json": "proposals",
    "tensions.json": "tensions",
    "governance_meetings.json": "governance_meetings",
    "tactical_meetings.json": "tactical_meetings",
    # Operational data, only kept for the record.
    "projects.json": "projects",
    "metrics.json": "metrics",
    "checklist_items.json": "checklist_items",
}


def fetch(path):
    request = urllib.request.Request(
        API + path,
        headers={
            "X-Auth-Token": os.environ["GLASSFROG_TOKEN"],
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.load(response)


def main():
    # Fetch everything first, write only if all requests succeeded.
    data = {name: fetch(path) for name, path in ENDPOINTS.items()}
    for name, content in data.items():
        tmp = REPO / f".{name}.tmp"
        tmp.write_text(
            json.dumps(content, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        )
        tmp.replace(REPO / name)

    timestamp = dt.datetime.now(dt.UTC)
    env = os.environ | {
        "GIT_AUTHOR_DATE": timestamp.isoformat(),
        "GIT_COMMITTER_DATE": timestamp.isoformat(),
        "GIT_AUTHOR_NAME": "Feinheit",
        "GIT_AUTHOR_EMAIL": "team@feinheit.ch",
        "GIT_COMMITTER_NAME": "Feinheit",
        "GIT_COMMITTER_EMAIL": "team@feinheit.ch",
    }
    subprocess.run(["git", "add", *ENDPOINTS], check=True, cwd=REPO)
    if (
        subprocess.run(
            ["git", "diff", "--cached", "--quiet"], check=False, cwd=REPO
        ).returncode
        == 0
    ):
        return  # Nothing changed
    subprocess.run(
        ["git", "commit", "-m", f"Update data snapshot from {timestamp.isoformat()}"],
        env=env,
        check=True,
        cwd=REPO,
    )
    subprocess.run(
        ["git", "push", "origin", "main"],
        env=env | {"GIT_SSH_COMMAND": "ssh -i ../id_rsa"},
        check=True,
        cwd=REPO,
    )


if __name__ == "__main__":
    main()
