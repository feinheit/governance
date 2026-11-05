#!/bin/sh
set -ex
uv run coverage erase
# The end-to-end tests need the production bundle in static/
mise exec -- yarn rspack build --mode production
PYTHONWARNINGS=all uv run coverage run ./manage.py test -v 2 --keepdb $*

if [ $# -eq 0 ]; then
  uv run coverage report
fi
