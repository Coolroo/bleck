"""Inspection commands: info, verify, maps, items. None of them writes anything."""

from __future__ import annotations

import argparse
from pathlib import Path

from bleck.backends import disc, doors, maps
from bleck.cli.types import AddCommand
from bleck.common.errors import UserError
from bleck.common.fsio import read_bytes
from bleck.formats import detect, items, u8
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


def cmd_items(args) -> int:
    """List the game's items — the names an `item:` selector accepts.

    The sibling of `cmd_maps`, with one difference worth stating: every id and
    every internal name ships with `bleck` (D114, D119), so it answers on a
    machine that has never seen the game. Only the English column needs one --
    those words are the game's own and are read from `files/msg` under
    `BLECK_BASE_DIR` at run time (D194), so without a disc that column falls
    back to the internal name.
    """
    catalog = items.catalog()
    total = len(catalog.known)

    if not catalog:
        # Not an error: ids and constants live in `itemids.py`, so only the
        # English column is missing. Said up front because the listing below
        # would otherwise just look oddly bare.
        print(f"no item catalog beside bleck ({items.ITEM_CATALOG} is missing);")
        print("ids and ITEM_ID_* constants still resolve, English names do not.\n")

    if args.groups:
        print(f"{total} items, by ITEM_ID_* group:\n")
        for group in catalog.groups():
            print(f"  {group.describe()}")
        return 0

    if args.group:
        found = catalog.group(args.group)
        if not found:
            named = ", ".join(g.group for g in catalog.groups() if g.group)
            print(f"no group {args.group!r}; the game has {named}")
            return 1
    elif args.search:
        found = catalog.search(args.search)
    else:
        found = catalog.known

    if not found:
        print(f"nothing matching {args.search!r} in {total} items")
        # The same "did you mean" a manifest gets for the same typo, from the
        # same tiers — `bleck items fire-brust` and a mod.json saying
        # `item:fire-brust` should not disagree about what was probably meant.
        near = catalog.suggest(args.search)
        if near:
            print(f"  Did you mean {', '.join(repr(name) for name in near)}?")
        return 1

    for entry in found:
        # Hex, not decimal: `item:0x41` is how every id in this repo is
        # written, so a value can be copied straight into a selector. Decimal
        # appears only in generated C comments, which nobody types.
        name = entry.english or entry.name
        print(f"  0x{entry.id:03x}  {name:<26} {entry.constant}")
    print(f"\n{len(found)} of {total} items")
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

    p = add("items", help="list the game's items, for item: selectors")
    p.add_argument("--search", help="only show items whose name contains this")
    p.add_argument("--groups", action="store_true", help="summarise by group instead")
    p.add_argument("--group", metavar="NAME", help="only one group, e.g. CARD")
    p.set_defaults(func=cmd_items)

    d = add("doors", help="what doors a map has, for door: selectors")
    d.add_argument("map", nargs="?", help="map name, e.g. he1_01. Omit to list all")
    d.set_defaults(func=cmd_doors)


def cmd_doors(args: argparse.Namespace) -> int:
    """What doors a map registers, of both kinds.

    ⚠️ **Two tables, and only one is patchable** (D138). Listing only the
    scriptable ones would make a map with five visible doorways look empty; the
    zones are shown precisely so "this map has doors but none you can patch" is
    a readable answer rather than a confusing silence.
    """
    found = doors.catalog()
    if not found:
        raise UserError(
            "no door catalog shipped with this build\n"
            "  regenerate it with `uv run python scripts/dump_doors.py "
            "--out bleck/backends/doorcatalog.json`"
        )

    if not args.map:
        scriptable = found.scriptable
        print(f"{len(scriptable)} map(s) register a door a patch can reach:\n")
        for entry in scriptable:
            names = ", ".join(door.name or "?" for door in entry.doors)
            print(f"  {entry.map_name:<10} {len(entry.doors):>2}  {names}")
        total = sum(len(entry.doors) for entry in scriptable)
        zones = sum(len(entry.zones) for entry in found.maps)
        print(
            f"\n{total} scriptable door(s) in the whole game, and {zones} "
            f"loading zone(s) across {len(found.maps)} map(s)."
        )
        return 0

    entry = found.find(args.map)
    if entry is None:
        raise UserError(
            f"{args.map} registers no doors of either kind.\n"
            f"  `bleck doors` lists the maps that do."
        )

    print(f"{args.map}:")
    if entry.doors:
        print(f"  {len(entry.doors)} scriptable door(s) -- `door:{args.map}:<index>`")
        for door in entry.doors:
            print(f"    {door.describe()}")
    else:
        print("  no scriptable doors -- nothing here for a `door:` patch")
    if entry.zones:
        print(f"  {len(entry.zones)} loading zone(s), which carry a destination")
        print("  and no scripts, so they cannot be patched:")
        for zone in entry.zones:
            print(f"    {zone.describe()}")
    if entry.zone_events:
        print(
            f"  this map attaches {entry.zone_events} zone event(s) itself with "
            f"evt_door_set_event,\n"
            f"  so a loading zone can carry a script even though its descriptor "
            f"has no field for one"
        )
    return 0
