"""`setup` commands: what enemies and items a map places, and where."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

from pydantic import ValidationError

from bleck import api
from bleck.backends import maps
from bleck.cli import shared as shared_flags
from bleck.cli.types import AddCommand
from bleck.common.errors import BleckError
from bleck.formats import setup
from bleck.mods import manifest, registry

CATEGORY = "inspection"

#: Where the standalone copies live, relative to an extracted build.
SETUP_DIR = "files/setup"


def _path(name: str):
    """The setup file for a map, by map name."""
    base = registry.base_root()
    path = base / SETUP_DIR / f"{name}.dat"
    if path.exists():
        return path
    # A map with no setup file is normal (383 maps, 227 setup files), so say
    # which case this is.
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

    if args.json:
        return _emit(_as_json(args.map, data))

    print(f"{args.map}: {data.summary()}")
    if data.version != setup.DOCUMENTED_VERSION:
        print(
            f"  version {data.version} entry fields are undocumented, so only "
            f"the container is readable"
        )

    names = setup.load_names()
    for enemy in data.enemies if args.all else data.used:
        line = enemy.describe()
        if names and enemy.documented and not enemy.is_empty:
            species = names.lookup(enemy.template)
            if species is not None:
                line += f"  {species.describe()}"
        print(f"  {line}")

    for item in data.items:
        print(f"  item: {item.describe()}")

    # ⛔ This said the reverse until now, citing D13/D53: "the game reads the
    # copy inside files/map/<map>.bin, not this one". D62 measured the opposite
    # and the project instructions call it the single most-copied wrong fact
    # in this repo -- which it proved by surviving here, in user-facing output,
    # long after every doc was corrected.
    #
    # ASCII only: the Windows console is cp1252 by default.
    print(
        f"\nNote: this is the copy the game reads. A second, byte-identical copy "
        f"is embedded in files/map/{args.map}.bin and is ignored; `bleck` writes "
        f"both so neither can drift."
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


def register(add: AddCommand) -> None:
    parser = add("setup", help="what enemies and items a map places")
    sub = parser.add_subparsers(dest="setup_command", required=True)

    shown = sub.add_parser("show", help="list one map's placements")
    shown.add_argument("map", help="map name, e.g. he1_01")
    shown.add_argument("--all", action="store_true", help="include the empty slots too")
    shown.add_argument(
        "--json",
        action="store_true",
        help="emit machine-readable JSON instead, for another tool to consume",
    )
    shown.set_defaults(func=cmd_show)

    listing = sub.add_parser("list", help="every map that places something")
    listing.add_argument(
        "--min-enemies", type=int, default=0, metavar="N", help="only maps with N+"
    )
    listing.set_defaults(func=cmd_list)

    register_editing(sub)


def _emit(model) -> int:
    """Print a pydantic model as JSON and nothing else, so `jq` can read it."""
    print(model.model_dump_json(indent=2, exclude_none=True))
    return 0


def _read_json(source: str) -> str:
    """JSON from a file, or from stdin when the path is `-`."""
    if source == "-":
        return sys.stdin.read()
    path = Path(source)
    if not path.exists():
        raise BleckError(f"no such file: {path}")
    return path.read_text(encoding="utf-8")


def _as_json(map_name: str, data: setup.SetupFile) -> api.MapPlacements:
    # Entry *fields* are only decoded for version 6; other versions parse as a
    # container and nothing more.
    documented = data.version == setup.DOCUMENTED_VERSION
    names = setup.load_names()
    enemies = []
    for slot, enemy in enumerate(data.enemies):
        species = (
            names.lookup(enemy.template)
            if names and documented and not enemy.is_empty
            else None
        )
        enemies.append(
            api.EnemyPlacement.of(slot, enemy, species.describe() if species else "")
        )
    return api.MapPlacements(
        map=map_name,
        version=data.version,
        documented=documented,
        enemies=enemies,
    )


def cmd_edits(args: argparse.Namespace) -> int:
    """What one mod declares inline, as JSON. The read half of the editing loop.

    ⚠️ **The inline `setup` block only.** A mod may also declare placements in
    CSV tables (D124), which are files rather than manifest content; this
    document is what `setup apply` writes back, so including them would mean
    writing them somewhere they did not come from. They are named rather than
    passed over in silence -- `bleck mod export` carries the declaration.
    """
    mod = registry.load().require(args.name)
    edits = api.SetupEdits.of(mod.manifest.setup)
    if args.json:
        return _emit(edits)
    if not edits.setup and not edits.coins and not mod.manifest.tables:
        print(f"{mod.name} declares no placement changes")
        return 0
    for map_name in dict.fromkeys([*edits.setup, *edits.coins]):
        print(f"  {map_name}")
        for edit in edits.setup.get(map_name, []):
            print(f"    enemy  {edit.model_dump_json(exclude_none=True)}")
        for coin in edits.coins.get(map_name, []):
            print(f"    coin   {coin.model_dump_json(exclude_none=True)}")
    _note_tables(mod)
    return 0


def _note_tables(mod) -> None:
    """Say which tables exist but are not part of this document."""
    for ref in mod.manifest.tables:
        bound = f" (map {ref.map_name})" if ref.is_bound else ""
        print(f"  {ref.path}{bound} also declares placements; not part of this document")


def cmd_apply(args: argparse.Namespace) -> int:
    """Write declared edits into a mod's `mod.json`, from JSON.

    ⚠️ Replaces the mod's `setup` block rather than merging: an omitted map has
    no unsurprising meaning. An editor holds the whole document.

    ⚠️ **CSV tables are left alone** (D124) -- they are files, and this writes
    `mod.json`. A slot now declared in both is refused at build time rather than
    resolved here, so the two never silently disagree.
    """
    mod = registry.load().require(args.name)
    try:
        incoming = api.SetupEdits.model_validate_json(_read_json(args.json))
    except ValidationError as exc:
        raise BleckError(f"{args.json}: {exc}") from exc

    updated = replace(mod.manifest, setup=incoming.to_manifest())
    manifest.write(mod.root, updated)

    changed = sum(len(edits) for edits in incoming.setup.values())
    print(
        f"{mod.name}: wrote {changed} edit(s) across "
        f"{len(incoming.setup)} map(s) to {mod.root / manifest.MANIFEST_NAME}"
    )
    _note_tables(mod)
    return 0


def cmd_schema(args: argparse.Namespace) -> int:
    """The JSON Schema for these documents, so other tools can validate."""
    model = api.MapPlacements if args.of == "map" else api.SetupEdits
    print(json.dumps(model.model_json_schema(), indent=2))
    return 0


def register_editing(sub) -> None:
    """The JSON half: read a mod's edits, write them back, publish the schema."""
    # ⚠️ These two take a mod NAME, so they read the registry and need the
    # shared `--mods-dir`. `show`/`list`/`schema` read the base disc or nothing
    # and are left alone.
    edits = sub.add_parser("edits", help="what a mod declares, as JSON")
    shared_flags.add_shared_flags(edits)
    edits.add_argument("name", help="mod name")
    edits.add_argument("--json", action="store_true", help="machine-readable output")
    edits.set_defaults(func=cmd_edits)

    apply_ = sub.add_parser("apply", help="write declared edits into a mod.json")
    shared_flags.add_shared_flags(apply_)
    apply_.add_argument("name", help="mod name")
    apply_.add_argument(
        "--json", required=True, metavar="FILE", help="JSON document, or - for stdin"
    )
    apply_.set_defaults(func=cmd_apply)

    schema = sub.add_parser("schema", help="JSON Schema for these documents")
    schema.add_argument(
        "--of",
        choices=("map", "edits"),
        default="edits",
        help="which document (default: edits)",
    )
    schema.set_defaults(func=cmd_schema)
