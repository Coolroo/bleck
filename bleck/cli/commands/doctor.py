"""`bleck doctor` — is this machine set up, and what does each gap cost?

Answers without making the user run a real command and read a stack trace, and
answers about **every** tool in one pass rather than stopping at the first
problem. Each tool is located, executed with a cheap argument, and reported
alongside the commands it gates.
"""

from __future__ import annotations

import argparse

from bleck.backends import doctor
from bleck.backends.doctor import Diagnosis, ToolStatus
from bleck.cli import requirements
from bleck.cli.types import AddCommand
from bleck.common import env
from bleck.platforms import ToolKey

CATEGORY = "diagnostics"

#: Width of the leading tool-name column, wide enough for `dolphin-tool`.
_NAME = 14

ABSENCE_IS_FINE = (
    "Absent is not an error: a tool gates only the commands that use it, so a "
    "machine\nwith no cross-compiler is correctly set up for asset work. "
    "bleck exits non-zero\nonly for misconfiguration -- an override pointing "
    "nowhere, or a tool that will not run."
)


def cmd_doctor(args: argparse.Namespace) -> int:
    """Report every external tool, and exit non-zero only for misconfiguration.

    ⚠️ **Absent and broken are different answers.** A user doing asset work with
    no PowerPC cross-compiler is correctly configured for what they do, so
    absence is informational and exits 0. An override variable pointing at a
    path that does not exist, or a tool that is present and will not execute,
    is somebody's mistake and exits 1.
    """
    found = doctor.check_all(run=not args.no_run)

    print(f"external tools on {found.platform}\n")
    for status in found.tools:
        for line in _describe(status):
            print(line)
        print()

    _print_environment()
    return _summarise(found)


def _describe(status: ToolStatus) -> list[str]:
    """One tool as a block: what it is, where it came from, and what it gates."""
    lines = [f"{status.key!s:<{_NAME}} {status.state.value}"]
    if status.path:
        lines.append(_row("path", status.path))
    if status.where:
        lines.append(_row("found via", status.where))
    lines += [_row("", line) for line in status.detail.splitlines()]
    lines += [_row("", line) for line in status.remedy.splitlines()]
    lines += _gates(status.key)
    return lines


def _row(label: str, text: str) -> str:
    return f"{'':<{_NAME}} {label:<12} {text}" if label else f"{'':<{_NAME}} {text}"


def _gates(key: ToolKey) -> list[str]:
    """What this tool costs when it is missing, as finished rows."""
    role = requirements.role(key)
    rows: list[str] = []
    if role.required_by:
        rows.append(_row("required by", ", ".join(role.required_by)))
    if role.optional_for:
        rows.append(_row("used by", ", ".join(role.optional_for)))
    if role.when:
        rows.append(_row("", f"only for {role.when}"))
    if not rows:
        rows.append(_row("", "nothing in bleck reaches for this yet"))
    return rows


def _print_environment() -> None:
    """Which declared variables are set, and to what.

    A path in `.env` that has gone stale is the exact failure `doctor` exists
    for, so the file that supplied it is named too.
    """
    source = env.dotenv_path()
    print(f"environment  ({source if source else 'no .env found'})\n")
    for setting in env.describe_all():
        marker = "set" if setting.is_set else "default"
        value = setting.value or "(unset)"
        print(f"  {setting.variable.name:<22} {marker:<8} {value}")
    print()


def _summarise(found: Diagnosis) -> int:
    counts = [
        f"{len(found.working)} working",
        f"{len(found.absent)} absent",
        f"{len(found.problems)} misconfigured",
    ]
    print(", ".join(counts) + ".")
    if not found.is_misconfigured:
        print(ABSENCE_IS_FINE)
        return 0

    print("\nFix these -- each is a setting or an install that did not take:")
    for status in found.problems:
        print(f"  {status.key}: {status.state.value}")
    return 1


def register(add: AddCommand) -> None:
    p = add("doctor", help="check every external tool bleck needs")
    p.add_argument(
        "--no-run",
        action="store_true",
        help=(
            "report what was found without executing it. ⚠️ Presence is not "
            "usability -- macOS kills unsigned binaries silently -- so this "
            "hides the failure the check exists to catch"
        ),
    )
    p.set_defaults(func=cmd_doctor)
