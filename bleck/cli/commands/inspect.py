"""Inspection commands: info, verify. Neither writes anything."""

from __future__ import annotations

import argparse
from pathlib import Path

from bleck.backends import disc, maps
from bleck.cli.types import AddCommand
from bleck.common.errors import UserError
from bleck.common.fsio import read_bytes
from bleck.formats import detect, u8
from bleck.mods import registry

from .archive import unwrap

CATEGORY = "inspection"

DISC_SUFFIXES = {".iso", ".wbfs", ".rvz"}


def cmd_info(args: argparse.Namespace) -> int:
    path = Path(args.file)
    if not path.is_file():
        raise UserError(f"no such file: {path}")
    print(f"{path.name}  {path.stat().st_size:,} bytes")

    if path.suffix.lower() in DISC_SUFFIXES:
        info = disc.identify(path)
        if not info.is_empty:
            for field in info.describe():
                print(f"  {field.label}: {field.value}")
            return 0
        # Disc images are far too large to slurp for format sniffing.
        print("  (unrecognised disc image; is wit or dolphin-tool installed?)")
        return 0

    data = read_bytes(path)
    for line in detect.render(detect.identify(data), indent=1):
        print(line)
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    target = Path(args.path)
    files = sorted(target.glob("*.bin")) if target.is_dir() else [target]
    if not files:
        raise UserError(f"no .bin files under {target}")

    ok = bad = skipped = 0
    for path in files:
        raw = unwrap(read_bytes(path)).data
        if not u8.is_u8(raw):
            skipped += 1
            continue
        if u8.write(u8.read_all(raw)) == raw:
            ok += 1
        else:
            bad += 1
            print(f"  MISMATCH {path.name}")

    print(f"{len(files)} files: {ok} identical, {bad} differing, {skipped} skipped")
    return 1 if bad else 0


def cmd_maps(args) -> int:
    """List the disc's map names — the exact strings `code.maps` needs."""
    index = maps.load(registry.base_root())

    if args.areas:
        print(f"{len(index.entries)} maps, in the game's own order:\n")
        for area in index.areas():
            print(f"  {area.describe()}")
        return 0

    if args.chapter:
        found = index.chapter(args.chapter)
        if not found:
            print(f"no chapter {args.chapter}; the game has 1-8")
            return 1
    elif args.search:
        found = index.search(args.search)
    else:
        found = index.entries

    if not found:
        print(f"nothing matching {args.search!r} in {len(index.entries)} maps")
        return 1

    for entry in found:
        ident = f"{entry.map_id:>3}" if entry.map_id >= 0 else "  ?"
        print(f"  {ident}  {entry.name:<10} {entry.where}")
    print(f"\n{len(found)} of {len(index.entries)} maps")
    return 0


def register(add: AddCommand) -> None:
    p = add("info", help="identify a file and its nested formats")
    p.add_argument("file")
    p.set_defaults(func=cmd_info)

    p = add("verify", help="round-trip check; writes nothing")
    p.add_argument("path")
    p.set_defaults(func=cmd_verify)

    p = add("maps", help="list the game's map names, for code.maps")
    p.add_argument("--search", help="only show maps whose name contains this")
    p.add_argument("--areas", action="store_true", help="summarise by area instead")
    p.add_argument("--chapter", type=int, metavar="N", help="only chapter N (1-8)")
    p.set_defaults(func=cmd_maps)
