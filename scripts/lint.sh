#!/usr/bin/env bash
# Run every check in one place.
#
#   scripts/lint.sh          check only
#   scripts/lint.sh --fix    apply what can be applied, then check
#
# Runs all checks even if an early one fails, so a single pass shows every
# problem rather than making you re-run after each fix.

set -uo pipefail
cd "$(dirname "$0")/.."

FIX=0
[[ "${1:-}" == "--fix" ]] && FIX=1

# Prefer the venv, fall back to whatever is on PATH.
if [[ -x .venv/bin/python ]]; then
    PY=.venv/bin/python
else
    PY=python3
fi

# Plugins are imported by pylint from the repo root.
export PYTHONPATH="${PYTHONPATH:+$PYTHONPATH:}."

TARGETS=(bleck tests lint_plugins)
status=0

run() {
    local label="$1"; shift
    printf '\n\033[1m== %s ==\033[0m\n' "$label"
    if "$@"; then
        printf '\033[32mok\033[0m\n'
    else
        printf '\033[31mFAILED\033[0m\n'
        status=1
    fi
}

missing() {
    "$PY" -c "import $1" 2>/dev/null && return 1
    printf '\n\033[33m%s is not installed — pip install -e ".[dev]"\033[0m\n' "$1"
    status=1
    return 0
}

if (( FIX )); then
    missing ruff || run "ruff format"     "$PY" -m ruff format "${TARGETS[@]}"
    missing ruff || run "ruff check --fix" "$PY" -m ruff check --fix "${TARGETS[@]}"
else
    missing ruff || run "ruff format --check" "$PY" -m ruff format --check "${TARGETS[@]}"
    missing ruff || run "ruff check"          "$PY" -m ruff check "${TARGETS[@]}"
fi

# pylint carries the project rule: no dict/tuple return types.
missing pylint || run "pylint" "$PY" -m pylint "${TARGETS[@]}"

printf '\n'
if (( status )); then
    printf '\033[31mlint failed\033[0m\n'
else
    printf '\033[32mall checks passed\033[0m\n'
fi
exit "$status"
