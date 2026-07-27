"""Parser assembly and dispatch.

Knows nothing about individual commands — it collects them from
`commands.MODULES` and routes errors to a clean message.
"""

from __future__ import annotations

import argparse
import sys

from ..backends.disc import DiscError
from ..common.errors import BleckError
from ..formats.lz77 import Lz77Error
from ..formats.u8 import U8Error
from . import commands

PROG = "bleck"
DESCRIPTION = "Super Paper Mario modding toolkit."

# Errors reported as a one-line message rather than a traceback.
HANDLED = (BleckError, DiscError, Lz77Error, U8Error)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=PROG, description=DESCRIPTION)
    sub = parser.add_subparsers(dest="command", required=True, metavar="<command>")

    # Shared flags go on each subcommand rather than the top level, so
    # `bleck pack dir out --force` works — the order people actually type.
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument(
        "--force", action="store_true", help="overwrite existing output"
    )

    def add(name: str, **kwargs) -> argparse.ArgumentParser:
        return sub.add_parser(name, parents=[shared], **kwargs)

    for module in commands.MODULES:
        module.register(add)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except HANDLED as exc:
        print(f"{PROG}: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
