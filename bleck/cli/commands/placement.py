"""`setup` commands: what enemies and items a map places, and where.

After textures, this is the most obviously moddable thing on the disc. Reading
it needs no emulator and no build, so the loop is fast: look at what a map
places, change one thing, build, boot.
"""

from __future__ import annotations

import argparse

from bleck.backends import maps
from bleck.common.errors import BleckError
from bleck.formats import setup
from bleck.mods import registry

CATEGORY = "inspection"

#: Where the standalone copies live, relative to an extracted build.
SETUP_DIR = "files/setup"


def _path(name: str):
    """The setup file for a map, by map name."""
    base = registry.base_root()
    path = base / SETUP_DIR / f"{name}.dat"
    if path.exists():
        return path
    # A map with no setup file is normal -- 383 maps, 227 setup files -- so say
    # which case this is rather than just failing to open something.
    index = maps.load(base)
    if index.find(name) is None:
        near = index.search(name)
        hint = f"  Did you mean {near[0].name}?" if near else "  Try: bleck maps"
        raise BleckError(f"no map called {name!r}\n{hint}")
    raise BleckError(
        f"{name} places no enemies or items (it has no setup file).\n"
        f"  {len(index.entries)} maps exist; 227 have one."
    )


def cmd_show(args: argparse.Namespace) -> int:
    path = _path(args.map)
    data = setup.read(path)

    print(f"{args.map}: {data.summary()}")
    if data.version != setup.DOCUMENTED_VERSION:
        print(
            f"  version {data.version} entry fields are undocumented, so only "
            f"the container is readable"
        )

    for enemy in data.enemies if args.all else data.used:
        print(f"  {enemy.describe()}")

    for item in data.items:
        print(f"  item: {item.describe()}")

    # The trap this whole area has: editing the wrong copy silently does
    # nothing (D53). Say it where someone is about to go and edit something.
    #
    # Plain ASCII deliberately: the Windows console is cp1252 by default, and a
    # warning that crashes the command instead of printing is worse than none.
    print(
        f"\nNote: the game reads the copy inside files/map/{args.map}.bin, "
        f"not this one (D13)."
    )
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    base = registry.base_root()
    directory = base / SETUP_DIR
    if not directory.is_dir():
        raise BleckError(f"no setup directory at {directory}")

    rows = []
    for path in sorted(directory.glob("*.dat")):
        data = setup.read(path)
        if args.min_enemies and len(data.used) < args.min_enemies:
            continue
        rows.append((path.stem, data))

    for name, data in rows:
        items = f"  {len(data.items):>3} items" if data.items else ""
        print(f"  {name:<10} v{data.version}  {len(data.used):>3} enemies{items}")
    print(f"\n{len(rows)} map(s)")
    return 0


def register(add) -> None:
    parser = add("setup", help="what enemies and items a map places")
    sub = parser.add_subparsers(dest="setup_command", required=True)

    shown = sub.add_parser("show", help="list one map's placements")
    shown.add_argument("map", help="map name, e.g. he1_01")
    shown.add_argument("--all", action="store_true", help="include the empty slots too")
    shown.set_defaults(func=cmd_show)

    listing = sub.add_parser("list", help="every map that places something")
    listing.add_argument(
        "--min-enemies", type=int, default=0, metavar="N", help="only maps with N+"
    )
    listing.set_defaults(func=cmd_list)
