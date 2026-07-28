"""Script commands, operating on a single `.evt` file outside any mod."""

from __future__ import annotations

import argparse
from pathlib import Path

from bleck.backends import toolchain
from bleck.common.errors import BleckError
from bleck.script import ScriptError, compile_source, emit
from bleck.script import catalog as builtin_catalog

CATEGORY = "scripting"


def _load(path: Path, require_entry: bool = True):
    """Compile a script file, reporting errors against the file the user wrote.

    `require_entry` is off for `check`: needing a `main` is a rule about how a
    *mod* starts things, not about whether the file is valid.
    """
    if not path.exists():
        raise BleckError(f"no such script: {path}")
    try:
        return compile_source(
            path.read_text(encoding="utf-8"),
            origin=path.name,
            scaffolding=emit.Scaffolding(require_entry=require_entry),
        )
    except ScriptError as exc:
        raise BleckError(exc.render(str(path))) from exc


def cmd_check(args: argparse.Namespace) -> int:
    path = Path(args.script)
    compiled = _load(path, require_entry=False)
    print(f"{path.name}: {compiled.summary()}")
    catalog = builtin_catalog.load()
    for name in compiled.program.called_symbols:
        known = catalog.find(name)
        print(f"  calls {known.describe() if known else name}")
    if not compiled.program.called_symbols:
        print("  calls no game functions")
    # The compiler already checked names and argument counts; only address
    # resolution is left, and that needs a symbol list at build time.
    print("  (addresses are resolved when the module is built)")
    return 0


def cmd_dump(args: argparse.Namespace) -> int:
    compiled = _load(Path(args.script))
    print(compiled.generated.text)
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    path = Path(args.script)
    compiled = _load(path)
    out = Path(args.output) if args.output else path.with_suffix(".rel")

    result = toolchain.build_rel(
        toolchain.BuildRequest(
            source=compiled.generated.text,
            workdir=out.parent / f".{out.stem}.build",
            target=args.target,
            module_id=args.module_id,
        )
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(result.rel)

    print(f"{path.name}: {compiled.summary()}")
    print(f"  {result.toolchain}, symbols from {result.symbols_file.name}")
    print(f"wrote {out}  ({result.size} bytes, module {result.module_id})")
    return 0


def _add_target_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--target",
        default="eu0",
        help=(
            "game version to resolve function names against (default: eu0, "
            "which has by far the most symbols documented)"
        ),
    )
    parser.add_argument(
        "--module-id",
        type=int,
        default=toolchain.DEFAULT_MODULE_ID,
        help="REL module id; the game's own REL is 1 (default: 2)",
    )


def cmd_builtins(args: argparse.Namespace) -> int:
    """What can a script actually call?"""
    catalog = builtin_catalog.load()
    if not catalog.builtins:
        raise BleckError(
            "no builtin catalog is present.\n"
            "  Generate one:  bleck script index <path-to-spm-headers/include>"
        )

    found = catalog.search(args.search) if args.search else catalog.builtins
    if not found:
        print(f"nothing matching {args.search!r} in {len(catalog.builtins)} builtins")
        return 0

    module = ""
    for builtin in sorted(found, key=lambda b: (b.module, b.name)):
        if builtin.module != module:
            module = builtin.module
            print(f"\n{module}")
        print(f"  {builtin.describe()}")

    print(f"\n{len(found)} of {len(catalog.builtins)} builtins")
    return 0


def cmd_index(args: argparse.Namespace) -> int:
    """Regenerate the builtin catalog from a spm-headers checkout."""
    include = Path(args.include)
    if not include.is_dir():
        raise BleckError(f"not a directory: {include}")

    try:
        catalog = builtin_catalog.build_catalog(include)
    except FileNotFoundError as exc:
        raise BleckError(
            f"{exc}\n  Point this at spm-headers' `include` directory"
        ) from exc

    documented = sum(1 for b in catalog.builtins if b.is_documented)
    builtin_catalog.CATALOG_FILE.write_text(catalog.to_json(), encoding="utf-8")
    print(f"wrote {builtin_catalog.CATALOG_FILE}")
    print(
        f"  {len(catalog.builtins)} builtins, {documented} with a known "
        f"argument count ({catalog.source})"
    )
    return 0


def register(add) -> None:
    parser = add("script", help="compile scripts into game code")
    sub = parser.add_subparsers(dest="script_command", required=True)

    def action(name: str, func, help_text: str) -> argparse.ArgumentParser:
        child = sub.add_parser(name, help=help_text)
        child.add_argument("script", help="path to a .evt script")
        child.set_defaults(func=func)
        return child

    action("check", cmd_check, "parse and compile a script without writing anything")
    action("dump", cmd_dump, "print the C that a script compiles to")
    listing = sub.add_parser("builtins", help="list the game functions a script can call")
    listing.add_argument("--search", help="only show builtins matching this text")
    listing.set_defaults(func=cmd_builtins)

    indexer = sub.add_parser("index", help="regenerate the builtin catalog")
    indexer.add_argument("include", help="path to spm-headers/include")
    indexer.set_defaults(func=cmd_index)

    built = action("build", cmd_build, "compile a script into a .rel module")
    built.add_argument("-o", "--output", help="where to write the module")
    _add_target_flags(built)
