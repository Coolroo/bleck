#!/usr/bin/env python3
"""Run every check, on any platform.

    python scripts/lint.py          check what this branch changed
    python scripts/lint.py --full   check every file
    python scripts/lint.py --fix    apply what can be applied, then check

Every check runs even when an earlier one fails, so one pass shows every
problem. This is the real entry point; `lint.sh` / `lint.ps1` are wrappers.

⚠️ **The default is the branch's own changes**, which is fast enough to run on
every save. `--full` is what CI runs, and is what to use before concluding the
tree is clean -- a whole-file check catches what a per-file one cannot, notably
an import cycle between two files where only one of them changed.
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


def _git(*args: str) -> str:
    """Run git and return stdout, or `""` if git is unavailable or fails."""
    try:
        done = subprocess.run(
            ["git", *args], cwd=REPO, capture_output=True, text=True, check=False
        )
    except OSError:
        return ""
    return done.stdout if done.returncode == 0 else ""


def _base_commit() -> str:
    """What to diff against: where this branch left the default branch.

    On the default branch itself the merge base is HEAD, so the diff is just the
    uncommitted work -- which is the right answer there too.
    """
    for ref in ("origin/main", "main"):
        found = _git("merge-base", "HEAD", ref).strip()
        if found:
            return found
    return "HEAD"


def changed_targets() -> list[str]:
    """Python files this branch touched, committed or not, that still exist.

    ⚠️ Untracked files are included. A brand-new module is exactly the one most
    worth checking, and it appears in no diff.
    """
    # pylint: disable=container-return  # a list of paths is not a record
    base = _base_commit()
    names = set()
    for args in (
        ("diff", "--name-only", base, "--"),
        ("diff", "--name-only", "--cached", "--"),
        ("diff", "--name-only", "--"),
        ("ls-files", "--others", "--exclude-standard"),
    ):
        names.update(_git(*args).split())

    roots = tuple(f"{target}/" for target in TARGETS)
    return sorted(
        name
        for name in names
        if name.endswith(".py")
        and name.startswith(roots)
        and (REPO / name).exists()
    )


def _has_module(python: str, module: str) -> bool:
    return (
        subprocess.run(
            [python, "-c", f"import {module}"],
            capture_output=True,
            check=False,
        ).returncode
        == 0
    )


def build_checks(python: str, fix: bool, targets: list[str]) -> list[Check]:
    checks: list[Check] = []
    paths = list(targets)
    if _has_module(python, "ruff"):
        if fix:
            checks.append(Check("ruff format", [python, "-m", "ruff", "format", *paths]))
            checks.append(
                Check("ruff check --fix", [python, "-m", "ruff", "check", "--fix", *paths])
            )
        else:
            checks.append(
                Check(
                    "ruff format --check",
                    [python, "-m", "ruff", "format", "--check", *paths],
                )
            )
            checks.append(Check("ruff check", [python, "-m", "ruff", "check", *paths]))
    else:
        print(_paint('ruff is not installed — pip install -e ".[dev]"', "33"))

    if _has_module(python, "pylint"):
        # pylint carries the project rules: no dict/tuple returns, env access.
        checks.append(Check("pylint", [python, "-m", "pylint", *paths]))
    else:
        print(_paint('pylint is not installed — pip install -e ".[dev]"', "33"))

    return checks


def main(argv: list[str]) -> int:
    fix = "--fix" in argv
    full = "--full" in argv
    python = _python()

    targets = TARGETS if full else changed_targets()
    if not full and not targets:
        print(_paint("no changed Python files -- nothing to check", "32"))
        print(_paint("(use --full to check the whole tree)", "2"))
        return 0
    if not full:
        count = len(targets)
        print(_paint(f"checking {count} changed file(s); --full for all", "2"))

    # Plugins are imported by pylint from the repo root.
    environment = dict(os.environ)
    existing = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = (
        f"{REPO}{os.pathsep}{existing}" if existing else str(REPO)
    )

    checks = build_checks(python, fix, list(targets))
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
