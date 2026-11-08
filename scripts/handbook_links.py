#!/usr/bin/env python3
"""Points links to GlassFrog in a directory of texts (the handbook) to the app

    GOVERNANCE_URL=https://… GOVERNANCE_TOKEN=… handbook_links.py DIR

For the switchover (``SWITCHOVER.md``), after the final import: the app's
roles and policies come from ``/api/backup/`` (any token), found by their
``glassfrog_id``. Rewrites the ``.rst`` and ``.md`` files below ``DIR`` in
place (review with ``git diff``) and lists what needs a look: links to
roles and policies the app doesn't know, archived ones, and link texts
which don't contain the current name. Runs with ``python3 -I``, without
dependencies.
"""

import json
import os
import re
import sys
import urllib.request
from pathlib import Path


GLASSFROG = re.compile(
    r"https?://(?:app|de)\.glassfrog\.com/organizations/\d+/orgnav"
    r"(?:/(?P<kind>roles|policies)/(?P<id>\d+)(?:/overview)?)?/?"
)
# reStructuredText's `Text <URL>`__ and Markdown's [Text](URL)
LINK_TEXT = re.compile(r"`([^`<]*?)\s*<\s*%s\s*>`_|\[([^\]]*)\]\(%s\)")


def fetch():
    request = urllib.request.Request(
        os.environ["GOVERNANCE_URL"].rstrip("/") + "/api/backup/",
        headers={"Authorization": f"Bearer {os.environ['GOVERNANCE_TOKEN']}"},
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        files = json.load(response)
    return {
        "roles": {
            row["glassfrog_id"]: row
            for row in files["roles.json"]
            if row["glassfrog_id"]
        },
        "policies": {
            row["glassfrog_id"]: row
            for row in files["policies.json"]
            if row["glassfrog_id"]
        },
    }


def rewrite(text, objects, base):
    """The text with the links to GlassFrog replaced, and the notes about
    them (line number, message)"""
    base = base.rstrip("/")
    notes = []

    def replace(match):
        line = text.count("\n", 0, match.start()) + 1
        if not match["kind"]:
            return f"{base}/"
        obj = objects[match["kind"]].get(int(match["id"]))
        if obj is None:
            notes.append((line, f"unknown: {match[0]}"))
            return match[0]
        name = obj.get("name") or obj.get("title")
        if obj["archived_on"]:
            notes.append((line, f"archived on {obj['archived_on']}: {name}"))
        label = link_text(text, match)
        if label is not None:
            label = " ".join(label.split())
        if label is not None and name.casefold() not in label.casefold():
            notes.append((line, f"link text {label!r}, now called {name!r}"))
        return f"{base}/{match['kind']}/{obj['id']}/"

    return GLASSFROG.sub(replace, text), notes


def link_text(text, match):
    """The text of the link around the URL, if any"""
    url = re.escape(match[0])
    start = max(0, text.rfind("\n\n", 0, match.start()))
    pattern = re.compile(LINK_TEXT.pattern % (url, url))
    if found := pattern.search(text, start, match.end() + 3):
        return found[1] if found[1] is not None else found[2]
    return None


def main():
    directory = Path(sys.argv[1])
    objects = fetch()
    base = os.environ["GOVERNANCE_URL"]
    for path in sorted([*directory.rglob("*.rst"), *directory.rglob("*.md")]):
        text = path.read_text()
        new, notes = rewrite(text, objects, base)
        if new != text:
            path.write_text(new)
        for line, message in notes:
            print(f"{path}:{line}: {message}")


if __name__ == "__main__":
    main()
