#!/usr/bin/env python3
"""Run every check, on any platform.

    python scripts/lint.py          check only
    python scripts/lint.py --fix    apply what can be applied, then check

Every check runs even when an earlier one fails, so one pass shows every
problem. This is the real entry point; `lint.sh` / `lint.ps1` are wrappers.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TARGETS = ["bleck", "tests", "lint_plugins"]

# Colour only where it will render; Windows consoles without ANSI get plain text.
_COLOUR = sys.stdout.isatty() and (os.name != "nt" or "WT_SESSION" in os.environ)


def _paint(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _COLOUR else text


@dataclass
class Check:
    label: str
    args: list[str]


def _python() -> str:
    """Locate the interpreter with the dev tools installed.

    Project venv first (both POSIX and Windows layouts), else this interpreter.
    """
    candidates = [
        REPO / ".venv" / "bin" / "python",
        REPO / ".venv" / "Scripts" / "python.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return sys.executable


def _has_module(python: str, module: str) -> bool:
    return (
        subprocess.run(
            [python, "-c", f"import {module}"],
            capture_output=True,
            check=False,
        ).returncode
        == 0
    )


def build_checks(python: str, fix: bool) -> list[Check]:
    checks: list[Check] = []
    if _has_module(python, "ruff"):
        if fix:
            checks.append(Check("ruff format", [python, "-m", "ruff", "format", *TARGETS]))
            checks.append(
                Check("ruff check --fix", [python, "-m", "ruff", "check", "--fix", *TARGETS])
            )
        else:
            checks.append(
                Check(
                    "ruff format --check",
                    [python, "-m", "ruff", "format", "--check", *TARGETS],
                )
            )
            checks.append(Check("ruff check", [python, "-m", "ruff", "check", *TARGETS]))
    else:
        print(_paint('ruff is not installed — pip install -e ".[dev]"', "33"))

    if _has_module(python, "pylint"):
        # pylint carries the project rules: no dict/tuple returns, env access.
        checks.append(Check("pylint", [python, "-m", "pylint", *TARGETS]))
    else:
        print(_paint('pylint is not installed — pip install -e ".[dev]"', "33"))

    return checks


def main(argv: list[str]) -> int:
    fix = "--fix" in argv
    python = _python()

    # Plugins are imported by pylint from the repo root.
    environment = dict(os.environ)
    existing = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = (
        f"{REPO}{os.pathsep}{existing}" if existing else str(REPO)
    )

    checks = build_checks(python, fix)
    failed = not checks and not _has_module(python, "ruff")

    for check in checks:
        print(_paint(f"\n== {check.label} ==", "1"))
        result = subprocess.run(check.args, cwd=REPO, env=environment, check=False)
        if result.returncode == 0:
            print(_paint("ok", "32"))
        else:
            print(_paint("FAILED", "31"))
            failed = True

    print()
    print(_paint("lint failed", "31") if failed else _paint("all checks passed", "32"))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
