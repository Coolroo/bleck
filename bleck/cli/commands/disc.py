"""Disc-level commands: extract, build.

Thin wrappers over the `wit`/`dolphin-tool` backend — the knowledge worth owning
here is the defaults, not the disc I/O itself.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from bleck.backends import disc
from bleck.common import env
from bleck.common.fsio import guard_overwrite, require_dir

CATEGORY = "discs"


def cmd_extract(args: argparse.Namespace) -> int:
    image = Path(args.disc)
    dest = Path(args.dest) if args.dest else _default_dest(image)
    guard_overwrite(dest, args.force)
    disc.extract(image, dest, keep_iso=args.keep_iso)
    print(f"extracted {image.name} -> {dest}/")
    return 0


def _default_dest(image: Path) -> Path:
    return Path(env.text(env.EXTRACT_ROOT)) / image.stem


def cmd_build(args: argparse.Namespace) -> int:
    src = require_dir(Path(args.dir))
    out = Path(args.out)
    guard_overwrite(out, args.force)
    image_format = resolve_format(out, args.format)
    disc.build_image(src, out, image_format, keep_iso=args.keep_iso)
    print(f"built {out}  ({out.stat().st_size:,} bytes, {image_format.value})")
    return 0


def resolve_format(out: Path, requested: str) -> disc.ImageFormat:
    """Explicit --format wins; otherwise infer from the output extension."""
    if requested:
        return disc.ImageFormat(requested)
    return disc.ImageFormat.for_path(out)


def add_format_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--format",
        choices=[f.value for f in disc.ImageFormat],
        default="",
        help="output format; inferred from the output extension by default. "
        "wbfs (~424 MB) works on every Dolphin build; rvz (~249 MB) is smaller "
        "but needs Dolphin 5.0-12188 or newer",
    )
    parser.add_argument(
        "--keep-iso",
        action="store_true",
        help="keep the intermediate ISO when writing RVZ",
    )


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

    p = add("build", help="extracted filesystem -> disc image")
    p.add_argument("dir")
    p.add_argument("out")
    add_format_flags(p)
    p.set_defaults(func=cmd_build)
