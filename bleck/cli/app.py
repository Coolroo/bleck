"""Parser assembly and dispatch.

Knows nothing about individual commands — it collects them from
`commands.MODULES` and routes errors to a clean message.
"""

from __future__ import annotations

import argparse
import sys

from bleck.backends.disc import DiscError
from bleck.common import env
from bleck.common.errors import BleckError
from bleck.formats.lz77 import Lz77Error
from bleck.formats.u8 import U8Error

from . import commands, requirements
from . import shared as shared_flags

PROG = "bleck"
DESCRIPTION = "Super Paper Mario modding toolkit."

# Errors reported as a one-line message rather than a traceback.
HANDLED = (BleckError, DiscError, Lz77Error, U8Error)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=PROG, description=DESCRIPTION)
    sub = parser.add_subparsers(dest="command", required=True, metavar="<command>")

    # Shared flags go on each subcommand rather than the top level, so
    # `bleck pack dir out --force` works — the order people actually type.
    shared = shared_flags.shared_parent()

    def add(name: str, **kwargs) -> argparse.ArgumentParser:
        return sub.add_parser(name, parents=[shared], **kwargs)

    for module in commands.MODULES:
        module.register(add)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        # ⚠️ Applied before anything reads the registry. `--mods-dir` is a
        # property of *this invocation*, so it becomes the environment override
        # bleck already understands rather than a new threaded parameter.
        if getattr(args, "mods_dir", None):
            env.override(env.MODS_DIR, args.mods_dir)

        # ⚠️ Before dispatch: a command that cannot possibly finish says so up
        # front, naming every missing tool at once. Only *unconditional* needs
        # are declared -- `requirements` says why that distinction is the point.
        check = requirements.preflight(args)
        if not check.is_satisfied:
            print(f"{PROG}: {check.message()}", file=sys.stderr)
            return 1

        return args.func(args)
    except HANDLED as exc:
        print(f"{PROG}: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
