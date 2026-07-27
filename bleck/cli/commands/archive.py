"""Archive-level commands: unpack, pack, ls.

Operates on the LZ77+U8 containers that hold SPM's maps and assets.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ...common import manifest
from ...common.errors import UserError
from ...common.fsio import guard_overwrite, read_bytes, require_dir
from ...formats import lz77, u8

CATEGORY = "archives"


def unwrap(data: bytes) -> tuple[bytes, bool]:
    """Return (u8_bytes, was_lz77_wrapped)."""
    if lz77.is_lz77(data):
        return lz77.decompress(data), True
    return data, False


def require_archive(data: bytes) -> bytes:
    raw, _ = unwrap(data)
    if not u8.is_u8(raw):
        raise UserError("not a U8 archive")
    return raw


def _encode(data: bytes, store: bool) -> bytes:
    return lz77.compress_literals(data) if store else lz77.compress(data)


def cmd_ls(args: argparse.Namespace) -> int:
    for entry in u8.read(require_archive(read_bytes(Path(args.archive)))):
        kind = "dir " if entry.is_dir else "file"
        size = "" if entry.is_dir else f"{entry.size:>10,}"
        print(f"{kind} {size:>10}  {entry.path}")
    return 0


def cmd_unpack(args: argparse.Namespace) -> int:
    src = Path(args.archive)
    dest = Path(args.dest) if args.dest else src.with_suffix("")
    data, compressed = unwrap(read_bytes(src))
    if not u8.is_u8(data):
        raise UserError("not a U8 archive")
    guard_overwrite(dest, args.force)

    entries = u8.read(data)
    for entry in entries:
        target = dest / entry.path
        if entry.is_dir:
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(u8.extract(data, entry))

    manifest.write(
        dest,
        manifest.Manifest(
            order=[e.path for e in entries],
            dirs=[e.path for e in entries if e.is_dir],
            compressed=compressed,
            source=src.name,
        ),
    )
    files = sum(1 for e in entries if not e.is_dir)
    print(f"unpacked {files} files to {dest}/  (manifest written)")
    return 0


def cmd_pack(args: argparse.Namespace) -> int:
    src = require_dir(Path(args.dir))
    out = Path(args.archive) if args.archive else src.with_suffix(".bin")
    guard_overwrite(out, args.force)

    found = manifest.read(src)
    if found is None:
        print(
            f"warning: no {manifest.MANIFEST_NAME} in {src} — "
            "packing in depth-first order; byte-exact output is not guaranteed",
            file=sys.stderr,
        )
        order, dirs = _walk(src)
        was_compressed = True
    else:
        order, dirs = found.order, set(found.dirs)
        was_compressed = found.compressed

    # --raw and --store answer different questions: whether to compress at all,
    # and which encoder to use. Either overrides what the source did.
    if args.raw:
        compressed = False
    elif args.store:
        compressed = True
    else:
        compressed = was_compressed

    entries: list[tuple[str, bytes | None]] = []
    for path in order:
        if path in dirs:
            entries.append((path, None))
            continue
        blob = src / path
        if not blob.exists():
            raise UserError(f"{path} listed in manifest but missing from {src}")
        entries.append((path, blob.read_bytes()))

    packed = u8.write(entries)
    if compressed:
        packed = _encode(packed, args.store)

    out.write_bytes(packed)
    note = " (stored)" if args.store and compressed else ""
    print(f"packed {len(entries)} entries -> {out}  {len(packed):,} bytes{note}")
    return 0


def _walk(root: Path) -> tuple[list[str], set[str]]:
    order: list[str] = []
    dirs: set[str] = set()
    for path in sorted(root.rglob("*")):
        if path.name == manifest.MANIFEST_NAME:
            continue
        rel = path.relative_to(root).as_posix()
        order.append(rel)
        if path.is_dir():
            dirs.add(rel)
    return order, dirs


def register(add) -> None:
    p = add("ls", help="list an archive's contents")
    p.add_argument("archive")
    p.set_defaults(func=cmd_ls)

    p = add("unpack", help="archive -> files on disk")
    p.add_argument("archive")
    p.add_argument("dest", nargs="?")
    p.set_defaults(func=cmd_unpack)

    p = add("pack", help="files on disk -> archive")
    p.add_argument("dir")
    p.add_argument("archive", nargs="?")
    p.add_argument(
        "--store",
        action="store_true",
        help="compress with the instant all-literals encoder (~1.125x, no search)",
    )
    p.add_argument("--raw", action="store_true", help="write uncompressed U8")
    p.set_defaults(func=cmd_pack)
