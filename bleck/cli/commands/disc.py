"""Disc-level commands: extract, build.

Thin wrappers over the `wit`/`dolphin-tool` backend — the knowledge worth owning
here is the defaults, not the disc I/O itself.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from ...backends import disc
from ...common.fsio import guard_overwrite, require_dir

CATEGORY = "discs"


def cmd_extract(args: argparse.Namespace) -> int:
    image = Path(args.disc)
    dest = Path(args.dest) if args.dest else Path("extracted") / image.stem
    guard_overwrite(dest, args.force)
    disc.extract(image, dest, keep_iso=args.keep_iso)
    print(f"extracted {image.name} -> {dest}/")
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    src = require_dir(Path(args.dir))
    out = Path(args.out)
    guard_overwrite(out, args.force)
    disc.build(src, out)
    print(f"built {out}  ({out.stat().st_size:,} bytes)")
    return 0


def register(add) -> None:
    p = add("extract", help="disc image -> extracted filesystem")
    p.add_argument("disc")
    p.add_argument("dest", nargs="?")
    p.add_argument(
        "--keep-iso",
        action="store_true",
        help="keep the ISO converted from an RVZ (conversion costs ~70s)",
    )
    p.set_defaults(func=cmd_extract)

    p = add("build", help="extracted filesystem -> ISO")
    p.add_argument("dir")
    p.add_argument("out")
    p.set_defaults(func=cmd_build)
