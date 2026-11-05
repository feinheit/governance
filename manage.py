#!/usr/bin/env python3
import os
import sys
from pathlib import Path

from speckenv import read_speckenv


if __name__ == "__main__":
    read_speckenv(Path(__file__).parent / ".env")
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "governance.settings")

    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)
