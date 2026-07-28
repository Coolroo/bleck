"""`symbols` commands: what the game's functions are called, and where they live.

Two sources: `spm.<version>.lst`, which `elf2rel` consumes, and `spm-decomp`'s
larger `symbols.txt`, which also carries types and sizes.

⚠️ `spm-decomp` states no licence (D54), so nothing from it ships here. Point
`BLECK_DECOMP` at your own clone; without it these work against the lst alone.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from bleck.backends import symbols, toolchain
from bleck.common import env
from bleck.common.errors import BleckError

CATEGORY = "inspection"

#: Inside a spm-decomp clone. Region directories are upper case there.
DECOMP_SYMBOLS = "config/{version}/symbols.txt"


def _lst(version: str) -> Path:
    return toolchain.symbols_file(version)


def _decomp(version: str) -> Path | None:
    """The decomp's table for this version, if a clone is configured."""
    root = env.path(env.DECOMP_DIR)
    if root is None:
        return None
    path = root / DECOMP_SYMBOLS.format(version=version.upper())
    if not path.is_file():
        raise BleckError(
            f"no symbol table at {path}\n"
            f"  BLECK_DECOMP points at {root}, which does not look like a "
            f"spm-decomp clone"
        )
    return path


def _load(version: str) -> symbols.SymbolTable:
    """The best table available: merged when a decomp clone is configured."""
    lst = symbols.read(_lst(version))
    decomp_path = _decomp(version)
    if decomp_path is None:
        return lst
    return symbols.merge(lst, symbols.read(decomp_path))


def cmd_list(args: argparse.Namespace) -> int:
    table = _load(args.target)
    found = table.search(args.search) if args.search else table.named
    if args.functions:
        found = [symbol for symbol in found if symbol.is_function]

    for symbol in found[: args.limit]:
        print(f"  {symbol.describe()}")
    if len(found) > args.limit:
        print(f"  ... {len(found) - args.limit} more (use --limit)")
    print(f"\n{len(found)} of {table.summary()}")
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    """Where the two sources disagree — one of them sends a call astray."""
    decomp_path = _decomp(args.target)
    if decomp_path is None:
        raise BleckError("comparing needs a spm-decomp clone; set BLECK_DECOMP to one")

    lst = symbols.read(_lst(args.target))
    decomp = symbols.read(decomp_path)
    shared = sum(1 for s in lst.symbols if decomp.find(s.name))
    disagreements = symbols.compare(lst, decomp)

    print(f"lst    : {lst.summary()}")
    print(f"decomp : {decomp.summary()}")
    print(f"\n{shared} shared name(s), {len(disagreements)} disagreement(s)")
    for item in disagreements:
        print(f"  {item.describe()}")
        # Name what actually lives at the disputed address.
        other = [s.name for s in decomp.symbols if s.address == item.lst_address]
        if other:
            print(f"      the decomp calls {item.lst_address:08X} {', '.join(other)}")
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    """Write a merged table in the format `elf2rel` reads."""
    decomp_path = _decomp(args.target)
    if decomp_path is None:
        raise BleckError("exporting needs a spm-decomp clone; set BLECK_DECOMP")

    lst = symbols.read(_lst(args.target))
    decomp = symbols.read(decomp_path)
    merged = symbols.merge(lst, decomp)

    disagreements = symbols.compare(lst, decomp)
    for item in disagreements:
        print(f"warning: {item.describe()} — using the decomp's (D60)")

    out = Path(args.output)
    if out.exists() and not args.force:
        raise BleckError(f"{out} exists; pass --force to overwrite")
    written = symbols.write_lst(
        merged, out, note=f"{lst.source.name} + {decomp_path} — {merged.summary()}"
    )
    print(f"wrote {written} symbols to {out}  (lst alone has {len(lst.symbols)})")
    return 0


def register(add) -> None:
    parser = add("symbols", help="the game's function names and addresses")
    sub = parser.add_subparsers(dest="symbols_command", required=True)

    def target(child):
        child.add_argument("--target", default="eu0", help="game version (default: eu0)")
        return child

    listing = target(sub.add_parser("list", help="list or search symbols"))
    listing.add_argument("--search", help="only names containing this")
    listing.add_argument(
        "--functions", action="store_true", help="only functions, not data"
    )
    listing.add_argument("--limit", type=int, default=40)
    listing.set_defaults(func=cmd_list)

    checked = target(sub.add_parser("compare", help="where the two sources disagree"))
    checked.set_defaults(func=cmd_compare)

    export = target(sub.add_parser("export", help="write a merged .lst"))
    export.add_argument("output", help="where to write it")
    # Nested subparsers do not inherit the shared --force from .
    export.add_argument("--force", action="store_true", help="overwrite an existing file")
    export.set_defaults(func=cmd_export)
