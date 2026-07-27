"""Stream-level commands: raw LZ77.

An escape hatch for working one layer at a time, below the archive commands.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from ...common.fsio import guard_overwrite, read_bytes
from ...formats import lz77

CATEGORY = "streams"


def cmd_lz(args: argparse.Namespace) -> int:
    data = read_bytes(Path(args.input))
    if args.action == "decompress":
        result = lz77.decompress(data)
    elif args.store:
        result = lz77.compress_literals(data)
    else:
        result = lz77.compress(data)

    if args.output:
        out = Path(args.output)
        guard_overwrite(out, args.force)
        out.write_bytes(result)
        print(f"{len(data):,} -> {len(result):,} bytes  ({out})")
    else:
        print(f"{len(data):,} -> {len(result):,} bytes")
    return 0


def register(add) -> None:
    p = add("lz", help="raw LZ77 compression")
    p.add_argument("action", choices=["compress", "decompress"])
    p.add_argument("input")
    p.add_argument("output", nargs="?")
    p.add_argument(
        "--store",
        action="store_true",
        help="all-literals encoding: instant, ~1.125x",
    )
    p.set_defaults(func=cmd_lz)
