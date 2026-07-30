"""Flags every command takes, in one place.

⚠️ **Nested subcommands do not inherit the top-level parent.** `bleck mod build`
is a subparser of a subparser, so the `parents=[shared]` that `cli.app` applies
reaches `mod` and stops -- which is why `--force` was already written out by
hand in `commands/mods.py` and `commands/symbols.py`.

`--mods-dir` made that duplication a correctness problem rather than a style
one: a flag that works on `bleck mod list` but not `bleck mod build` is worse
than one that exists nowhere. So both live here, and every parser that wants
them calls `add_shared_flags`.
"""

from __future__ import annotations

import argparse


def add_shared_flags(parser: argparse.ArgumentParser) -> None:
    """Attach the flags any command may take."""
    parser.add_argument("--force", action="store_true", help="overwrite existing output")
    parser.add_argument(
        "--mods-dir",
        metavar="DIR",
        help=(
            "where mods live, overriding BLECK_MODS_DIR for this command -- "
            "e.g. --mods-dir example-mods"
        ),
    )


def shared_parent() -> argparse.ArgumentParser:
    """A parser carrying only those flags, for use as a `parents=` entry."""
    parent = argparse.ArgumentParser(add_help=False)
    add_shared_flags(parent)
    return parent
