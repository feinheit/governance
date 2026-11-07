#!/usr/bin/env python3
"""Daily JSON backup of Governance: ``gov backup`` and a commit.

    GOVERNANCE_URL=https://… GOVERNANCE_TOKEN=… fetch_backup.py REPO

``REPO`` is a checkout of the backup repository, ``gov`` must be installed.
The token (read access suffices) decides what the backup contains:
everything its user sees, the people included. Files are only replaced
when the request succeeded, and nothing is committed when nothing changed.
"""

import datetime as dt
import os
import subprocess
import sys
from pathlib import Path


def fetch(repo):
    """``gov backup`` writes the files, the people included; GOVERNANCE_URL
    and GOVERNANCE_TOKEN select the installation"""
    subprocess.run(["gov", "backup", str(repo), "--with-people"], check=True)


def commit(repo):
    timestamp = dt.datetime.now(dt.UTC)
    env = os.environ | {
        "GIT_AUTHOR_DATE": timestamp.isoformat(),
        "GIT_COMMITTER_DATE": timestamp.isoformat(),
        "GIT_AUTHOR_NAME": "Feinheit",
        "GIT_AUTHOR_EMAIL": "team@feinheit.ch",
        "GIT_COMMITTER_NAME": "Feinheit",
        "GIT_COMMITTER_EMAIL": "team@feinheit.ch",
    }
    # Also roles renamed (a new file name) since the last backup
    subprocess.run(["git", "add", "--all", "."], check=True, cwd=repo)
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
    fetch(repo)
    commit(repo)


if __name__ == "__main__":
    main()
