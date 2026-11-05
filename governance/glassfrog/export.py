"""Reading the GlassFrog export, a git repository with JSON files

``glassfrog.json`` (``GET /api/v3/circles?include=members``) has a history
since 2018-11-16, the other files since 2026-11-04. See ``SPEC.md``.
"""

import datetime as dt
import json
import re
import subprocess
import urllib.request
from pathlib import Path


FILES = [
    "glassfrog.json",
    "roles.json",
    "assignments.json",
    "policies.json",
    "proposals.json",
    "tensions.json",
    "governance_meetings.json",
    "tactical_meetings.json",
    "metrics.json",
    "checklist_items.json",
]


def without_empty(objects):
    """Every ``linked`` list of GlassFrog's responses contains one ``{}``"""
    return [obj for obj in objects or [] if obj]


class Export:
    """The checkout of the fetcher's repository, with the whole history"""

    incremental = False

    def __init__(self, path):
        self.path = Path(path)

    def load(self, name):
        """The current version of a file, ``None`` if it doesn't exist"""
        file = self.path / name
        if not file.exists():
            return None
        return json.loads(file.read_text(encoding="utf-8"))

    def snapshots(self):
        """Yields ``(date, data)`` of every day with a snapshot, oldest first

        Empty snapshots (failed fetches) are skipped, of several snapshots
        on one day the last one is used. The date comes from the commit
        message, the commit dates are wrong for some commits.
        """
        log = subprocess.run(
            [
                "git",
                "-C",
                self.path,
                "log",
                "--reverse",
                "--format=%H %s",
                "--",
                "glassfrog.json",
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.splitlines()
        commits = {}
        for line in log:
            sha, message = line.split(" ", 1)
            match = re.search(r"(\d{4}-\d{2}-\d{2})", message)
            if match:
                commits[dt.date.fromisoformat(match[1])] = sha  # Last one wins

        with subprocess.Popen(
            ["git", "-C", self.path, "cat-file", "--batch"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
        ) as process:
            for day, sha in commits.items():
                process.stdin.write(f"{sha}:glassfrog.json\n".encode())
                process.stdin.flush()
                header = process.stdout.readline().split()
                if header[-1] == b"missing":
                    continue
                content = process.stdout.read(int(header[2]))
                process.stdout.read(1)  # The newline after the content
                if len(content) < 1000:
                    continue  # Failed fetch
                yield day, json.loads(content)
            process.stdin.close()


API = "https://api.glassfrog.com/api/v3/"
# The export's files and the API endpoints they come from (like the fetcher)
ENDPOINTS = {
    "glassfrog.json": "circles?include=members",
    "roles.json": "roles",
    "assignments.json": "assignments",
    "policies.json": "policies",
    "proposals.json": "proposals",
    "tensions.json": "tensions",
    "governance_meetings.json": "governance_meetings",
    "tactical_meetings.json": "tactical_meetings",
    "metrics.json": "metrics",
    "checklist_items.json": "checklist_items",
}


def fetch_api(path, token):
    request = urllib.request.Request(
        API + path,
        headers={"X-Auth-Token": token, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.load(response)


class ApiExport:
    """Today's state, fetched from GlassFrog's API, without the history

    The import adds today to the history which is already in the database
    (see ``Importer`` and its incremental mode).
    """

    incremental = True

    def __init__(self, token, *, day=None, fetch=fetch_api):
        self.token = token
        self.day = day or dt.date.today()
        self.fetch = fetch
        self._cache = {}

    def load(self, name):
        if name not in self._cache:
            self._cache[name] = self.fetch(ENDPOINTS[name], self.token)
        return self._cache[name]

    def snapshots(self):
        yield self.day, self.load("glassfrog.json")
