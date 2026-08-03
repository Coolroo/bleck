"""Which external tools a command needs, checked before it starts.

A command declares its needs with `set_defaults(requires=[...])` and `cli.app`
checks them all at once, so a user with two tools missing hears about both
rather than fixing one and running again.

⚠️ **Only an *unconditional* need belongs in `requires`.** `bleck mod build`
may compile C and may write a disc image, and does neither when the mod has no C
sources and `--output none` is passed -- declaring `wit` or a compiler for it
would refuse work that succeeds today. A conditional need stays lazy, and
`find_tool` reports it in a sentence at the point it is genuinely required.

`ROLES` is the other half: what each tool gates, including the conditional
cases, so `bleck doctor` can say what an absent tool costs. The `required_by`
column is checked against the parser by `tests/test_doctor.py`, so the two
cannot drift.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field

from bleck.backends.disc import ToolSearch, locate
from bleck.platforms import ToolKey

#: The `set_defaults` keys `needs` writes. `INVOCATION` carries argparse's own
#: `prog`, so a nested command reports as `bleck script build` rather than as
#: the bare `script` its top-level dest holds.
REQUIRES = "requires"
INVOCATION = "requires_for"

DOCTOR_HINT = "`bleck doctor` checks every tool at once and says what each one gates."


@dataclass(frozen=True)
class ToolRole:
    """What one tool is for, in terms of the commands a user types."""

    key: ToolKey

    required_by: list[str] = field(default_factory=list)
    """Commands that cannot start without it. Mirrors their `requires`."""

    optional_for: list[str] = field(default_factory=list)
    """Commands that need it only sometimes; `when` says when."""

    when: str = ""
    """The condition under which `optional_for` actually reaches for it."""


ROLES: list[ToolRole] = [
    ToolRole(
        key=ToolKey.WIT,
        required_by=["extract", "build"],
        optional_for=["mod build"],
        when="any build that writes a disc image, so not `--output none`",
    ),
    ToolRole(
        key=ToolKey.DOLPHIN_TOOL,
        optional_for=["extract", "info", "build --format rvz", "mod build"],
        when="RVZ images; wit reads .iso and .wbfs natively",
    ),
    ToolRole(key=ToolKey.DOLPHIN, required_by=["launch"]),
    ToolRole(
        key=ToolKey.WSTRT,
        optional_for=["mod build"],
        when="embedding the Gecko loader; without it a code mod still builds",
    ),
    ToolRole(
        key=ToolKey.PPC_GCC,
        required_by=["script build"],
        optional_for=["mod build"],
        when="mods with C or C++ sources, or a compiled script",
    ),
]


def role(key: ToolKey) -> ToolRole:
    """What `key` gates. Every member has a row; the fallback keeps that honest."""
    return next((found for found in ROLES if found.key is key), ToolRole(key=key))


def needs(parser: argparse.ArgumentParser, *keys: ToolKey) -> None:
    """Declare the tools a command cannot start without.

    Takes the parser rather than a name so the command reports itself exactly
    as it is typed -- argparse has already built `bleck script build` out of
    its parents, and a hand-written string would be one rename from lying.
    """
    parser.set_defaults(**{REQUIRES: list(keys), INVOCATION: parser.prog})


@dataclass(frozen=True)
class Preflight:
    """A command's unconditional tool needs, weighed before it runs."""

    invocation: str
    missing: list[ToolSearch] = field(default_factory=list)

    @property
    def is_satisfied(self) -> bool:
        return not self.missing

    def message(self) -> str:
        """Every unmet need at once, each with the platform's own hint."""
        needed = ", ".join(str(search.key) for search in self.missing)
        lines = [f"`{self.invocation}` needs {needed}, and cannot run without it:"]
        for search in self.missing:
            lines += ["", *(f"  {line}" for line in search.problem.splitlines())]
        return "\n".join([*lines, "", DOCTOR_HINT])


def declared(args: argparse.Namespace) -> list[ToolKey]:
    """The tools this invocation's command declared. Empty for most commands."""
    return list(getattr(args, REQUIRES, ()) or ())


def preflight(args: argparse.Namespace) -> Preflight:
    """Check every declared tool, reporting all the failures rather than the first."""
    invocation = getattr(args, INVOCATION, "") or "bleck"
    searches = [locate(key) for key in declared(args)]
    return Preflight(invocation, [found for found in searches if not found.found])
