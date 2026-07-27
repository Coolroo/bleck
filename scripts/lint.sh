#!/usr/bin/env bash
# POSIX convenience wrapper. The real logic is in lint.py so Windows works too.
set -uo pipefail
cd "$(dirname "$0")/.."
if [[ -x .venv/bin/python ]]; then PY=.venv/bin/python; else PY=python3; fi
exec "$PY" scripts/lint.py "$@"
