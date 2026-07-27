"""Inspection commands: info, verify. Neither writes anything."""

from __future__ import annotations

import argparse
from pathlib import Path

from ...backends import disc
from ...common.errors import UserError
from ...common.fsio import read_bytes
from ...formats import detect, u8
from .archive import unwrap

CATEGORY = "inspection"

DISC_SUFFIXES = {".iso", ".wbfs", ".rvz"}


def cmd_info(args: argparse.Namespace) -> int:
    path = Path(args.file)
    data = read_bytes(path)
    print(f"{path.name}  {len(data):,} bytes")

    if path.suffix.lower() in DISC_SUFFIXES:
        fields = disc.identify(path)
        if fields:
            for key, value in fields.items():
                print(f"  {key}: {value}")
            return 0

    for line in detect.render(detect.identify(data, path.name), indent=1):
        print(line)
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    target = Path(args.path)
    files = sorted(target.glob("*.bin")) if target.is_dir() else [target]
    if not files:
        raise UserError(f"no .bin files under {target}")

    ok = bad = skipped = 0
    for path in files:
        raw, _ = unwrap(read_bytes(path))
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


def register(add) -> None:
    p = add("info", help="identify a file and its nested formats")
    p.add_argument("file")
    p.set_defaults(func=cmd_info)

    p = add("verify", help="round-trip check; writes nothing")
    p.add_argument("path")
    p.set_defaults(func=cmd_verify)
