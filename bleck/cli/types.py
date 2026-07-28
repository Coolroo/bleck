"""Types for the CLI's own plumbing.

⚠️ Scoped to this package on purpose. `bleck` has no shared `types` module: a
domain type lives in the layer that owns it, so `emit.HookMode` says where hook
modes come from where `types.HookMode` would not (D98). This file is the
exception the rule allows -- a protocol for how `cli.app` talks to the command
modules, used by nine files inside `bleck/cli/` and by nothing outside it.
"""

from __future__ import annotations

import argparse
from typing import Protocol


class AddCommand(Protocol):
    """The subparser factory `cli.app.build_parser` hands each command module.

    Not `argparse`'s own `add_parser`: this one has the shared flags already
    attached as a parent, which is why a command module is given the closure
    rather than the subparsers action.

    ⚠️ Only `help` is declared, because only `help` is passed. Widening this to
    match everything `add_parser` accepts would make it describe argparse rather
    than describe what the CLI does -- add a keyword here when a command needs
    one, so the addition is deliberate and visible in one place.
    """

    # `help` shadows the builtin, and has to: a keyword-only parameter's NAME is
    # the contract, and every caller writes `add("pack", help=...)`. Renaming it
    # would stop the protocol describing the thing it exists to describe.
    # pylint: disable=redefined-builtin
    def __call__(self, name: str, *, help: str = "") -> argparse.ArgumentParser: ...
