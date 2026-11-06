#!/usr/bin/env python3
"""Daily JSON backup of Governance: fetches /api/backup/ and commits the files.

    GOVERNANCE_URL=https://… GOVERNANCE_TOKEN=… fetch_backup.py REPO

``REPO`` is a checkout of the backup repository. The token (read access
suffices) decides what the backup contains: everything its user sees. Like
``fetch_glassfrog.py``, files are only replaced when the request succeeded,
and nothing is committed when nothing changed.
"""

import datetime as dt
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path


def fetch():
    request = urllib.request.Request(
        os.environ["GOVERNANCE_URL"].rstrip("/") + "/api/backup/",
        headers={"Authorization": f"Bearer {os.environ['GOVERNANCE_TOKEN']}"},
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        return json.load(response)


def write(repo, files):
    for name, content in files.items():
        tmp = repo / f".{name}.tmp"
        tmp.write_text(
            json.dumps(content, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        )
        tmp.replace(repo / name)


def commit(repo, names):
    timestamp = dt.datetime.now(dt.UTC)
    env = os.environ | {
        "GIT_AUTHOR_DATE": timestamp.isoformat(),
        "GIT_COMMITTER_DATE": timestamp.isoformat(),
        "GIT_AUTHOR_NAME": "Feinheit",
        "GIT_AUTHOR_EMAIL": "team@feinheit.ch",
        "GIT_COMMITTER_NAME": "Feinheit",
        "GIT_COMMITTER_EMAIL": "team@feinheit.ch",
    }
    subprocess.run(["git", "add", *names], check=True, cwd=repo)
    unchanged = subprocess.run(
        ["git", "diff", "--cached", "--quiet"], check=False, cwd=repo
    )
    if unchanged.returncode == 0:
        return False
    subprocess.run(
        ["git", "commit", "-m", f"Backup from {timestamp.isoformat()}"],
        env=env,
        check=True,
        cwd=repo,
    )
    subprocess.run(["git", "push", "origin", "main"], env=env, check=True, cwd=repo)
    return True


def main():
    repo = Path(sys.argv[1])
    files = fetch()
    write(repo, files)
    commit(repo, sorted(files))


if __name__ == "__main__":
    main()
