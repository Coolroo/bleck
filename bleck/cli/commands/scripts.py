"""Script commands: check, build, dump.

These operate on a single `.evt` file, outside any mod. Compiling a script is
much faster than building a 400 MB disc, so having a way to do just that is what
makes the language usable: most iterations are a syntax error or a mistyped
function name, and neither needs a disc to find.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from bleck.backends import toolchain
from bleck.common.errors import BleckError
from bleck.script import ScriptError, compile_source

CATEGORY = "scripting"


def _load(path: Path):
    """Compile a script file, reporting errors against the file the user wrote."""
    if not path.exists():
        raise BleckError(f"no such script: {path}")
    try:
        return compile_source(path.read_text(encoding="utf-8"), origin=path.name)
    except ScriptError as exc:
        raise BleckError(exc.render(str(path))) from exc


def cmd_check(args: argparse.Namespace) -> int:
    path = Path(args.script)
    compiled = _load(path)
    print(f"{path.name}: {compiled.summary()}")
    for name in compiled.program.called_symbols:
        print(f"  calls {name}")
    if not compiled.program.called_symbols:
        print("  calls no game functions")
    # Deliberately not resolved here: checking is meant to work without a
    # toolchain or a symbol list, so a bad function name surfaces at build time.
    print("  (function names are resolved when the module is built)")
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
        compiled.generated.text,
        workdir=out.parent / f".{out.stem}.build",
        target=args.target,
        module_id=args.module_id,
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
    built = action("build", cmd_build, "compile a script into a .rel module")
    built.add_argument("-o", "--output", help="where to write the module")
    _add_target_flags(built)
