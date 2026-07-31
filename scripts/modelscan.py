#!/usr/bin/env python3
"""Read an undecoded binary the way this project actually reads one.

`dolscan.py` is this for the DOL: find a string, find who builds its address,
read the code. **There is no equivalent for a data file**, and the character
models in `files/a/` were mapped with a dozen throwaway `python -c` snippets
that answered a question and then vanished. Every one of them was a technique
worth keeping.

⚠️ **The point is reproducibility, not convenience.** A finding recorded in
`decision-log.md` says *what* was concluded; this says how to see it again, and
lets the next person disagree with it. `docs/plan-dimentio.md` lists model
geometry as the blocker for the 3D stages -- whoever picks that up should not
have to reinvent the survey.

    uv run python scripts/modelscan.py survey  files/a/p_wii_mario
    uv run python scripts/modelscan.py header  files/a/p_wii_mario
    uv run python scripts/modelscan.py offsets files/a/p_wii_mario
    uv run python scripts/modelscan.py at      files/a/p_wii_mario 0x15f5c
    uv run python scripts/modelscan.py strings files/a/p_wii_mario --min 6

Paths are relative to the extracted disc, so `files/a/x` works from anywhere.

## The techniques, and what each one settled

- **survey** -- classify 4 KB windows as floats, strings or packed data. This is
  what showed `p_wii_mario` is tables and matrices up to 0x15F5C and then 200 KB
  of dense packed data, which is where geometry has to be (D202).
- **header** -- read the two nested records. ⚠️ The model's bounding box is in
  the record the *leading word points at*, not the opening one; reading the
  opening one gives a sub-object's box and made Mario 17.9 units tall instead of
  73.4.
- **offsets** -- find runs of ascending plausible file offsets. That is how the
  table at 0x170 was found, and following it landed on materials, matrices,
  indices and the texture path list.
- **at** -- dump one place three ways at once. A region that looks like noise as
  hex is often obvious as floats, and vice versa.
"""

from __future__ import annotations

import argparse
import re
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bleck.common import env  # noqa: E402

WINDOW = 4096

#: Anything outside this reads as a float by accident rather than by design.
FLOAT_LOW = 1e-3
FLOAT_HIGH = 1e5


def resolve(where: str) -> Path:
    """A path as given, or relative to the extracted disc."""
    direct = Path(where)
    if direct.is_file():
        return direct
    base = Path(env.text(env.BASE_DIR))
    candidate = base / where
    if candidate.is_file():
        return candidate
    raise SystemExit(f"no file at {where} or {candidate}")


def looks_float(value: float) -> bool:
    return value == 0.0 or FLOAT_LOW < abs(value) < FLOAT_HIGH


@dataclass(frozen=True)
class Window:
    """One slice of a file, and what it appears to hold."""

    offset: int
    floats: int
    zeros: int
    ascii_: int

    @property
    def guess(self) -> str:
        """⚠️ A guess, and named one. Two of these were wrong before the
        offsets confirmed them."""
        if self.ascii_ > 40:
            return "strings"
        if self.floats > 85 and self.zeros < 60:
            return "floats"
        if self.floats > 85:
            return "floats (sparse)"
        if self.zeros < 45:
            return "packed"
        return ""


def survey(data: bytes, size: int = WINDOW) -> list[Window]:
    # pylint: disable=container-return
    """Classify each window by what fraction reads as floats, zeros and text."""
    out: list[Window] = []
    for start in range(0, len(data), size):
        chunk = data[start : start + size]
        count = len(chunk) // 4
        floats = sum(
            1
            for i in range(count)
            if looks_float(struct.unpack_from(">f", chunk, i * 4)[0])
        )
        out.append(
            Window(
                offset=start,
                floats=floats * 100 // max(count, 1),
                zeros=chunk.count(0) * 100 // max(len(chunk), 1),
                ascii_=sum(1 for c in chunk if 32 <= c < 127)
                * 100
                // max(len(chunk), 1),
            )
        )
    return out


def offset_runs(data: bytes, least: int = 4) -> list[tuple]:
    # pylint: disable=container-return
    """Runs of consecutive words that ascend and point inside the file.

    ⚠️ Equal neighbours are allowed. A table with repeats is the normal way a
    format says "this section is empty", and rejecting them hides the table.
    """
    words = len(data) // 4
    runs = []
    start = None
    previous = -1
    for index in range(words):
        value = struct.unpack_from(">I", data, index * 4)[0]
        ok = 0 < value < len(data) and value >= previous
        if ok and start is None:
            start = index
        elif not ok:
            if start is not None and index - start >= least:
                runs.append((start * 4, index - start))
            start = None
            previous = -1
            continue
        previous = value
    if start is not None and words - start >= least:
        runs.append((start * 4, words - start))
    return runs


def show_at(data: bytes, offset: int, rows: int) -> None:
    """Hex, text and floats together, because one of the three usually says it."""
    for row in range(rows):
        at = offset + row * 16
        if at + 16 > len(data):
            break
        chunk = data[at : at + 16]
        text = "".join(chr(c) if 32 <= c < 127 else "." for c in chunk)
        values = struct.unpack_from(">4f", data, at)
        shown = "  ".join(
            f"{v:>11.4f}" if looks_float(v) else " " * 11 for v in values
        )
        print(f"  {at:#08x}  {chunk.hex(' ')}  |{text}|")
        if any(looks_float(v) and v != 0 for v in values):
            print(f"            {shown}")


def cmd_survey(args: argparse.Namespace) -> int:
    data = resolve(args.file).read_bytes()
    print(f"{len(data):,} bytes, {args.window}-byte windows")
    print(f"{'offset':>10} {'float':>6} {'zero':>5} {'text':>5}  reads as")
    for window in survey(data, args.window):
        if args.only and window.guess != args.only:
            continue
        print(
            f"{window.offset:>10,} {window.floats:>5}% {window.zeros:>4}% "
            f"{window.ascii_:>4}%  {window.guess}"
        )
    return 0


def cmd_header(args: argparse.Namespace) -> int:
    from bleck.formats import model  # pylint: disable=import-outside-toplevel

    path = resolve(args.file)
    data = path.read_bytes()
    if not model.is_model(data):
        print(f"{path.name} is not a character model")
        return 1
    found = model.read(data)
    head = struct.unpack_from(">I", data, 0)[0]
    print(f"{found.name}   built {found.stamp}")
    print(f"  scene record at {head:#x}  (file is {len(data):,} bytes)")
    print(f"  bounds {found.bounds.describe()}  height {found.bounds.height:.1f}")
    print(f"  {len(found.shapes)} shape(s), {len(found.textures)} texture(s)")
    bank = model.bank_for(path)
    if bank.is_file():
        from bleck.formats import tpl  # pylint: disable=import-outside-toplevel

        images = len(tpl.read(bank.read_bytes()))
        mark = "==" if images == len(found.textures) else "<" if images else "?"
        print(f"  bank {bank.name}: {images} image(s)  {mark} texture references")
    for name in found.shapes[: args.limit]:
        print(f"    shape  {name}")
    return 0


def cmd_offsets(args: argparse.Namespace) -> int:
    data = resolve(args.file).read_bytes()
    runs = offset_runs(data, args.least)
    print(f"{len(runs)} run(s) of ascending in-file offsets")
    for at, count in runs[: args.limit]:
        values = struct.unpack_from(f">{min(count, 12)}I", data, at)
        shown = " ".join(f"{v:#x}" for v in values)
        print(f"  {at:#08x}  {count:>4} entries  {shown}")
    return 0


def cmd_at(args: argparse.Namespace) -> int:
    data = resolve(args.file).read_bytes()
    show_at(data, int(args.offset, 0), args.rows)
    return 0


def cmd_strings(args: argparse.Namespace) -> int:
    data = resolve(args.file).read_bytes()
    pattern = rb"[ -~]{%d,}" % args.min
    for match in re.finditer(pattern, data):
        text = match.group().decode("ascii", "replace")
        if args.search and args.search not in text:
            continue
        print(f"  {match.start():#08x}  {text}")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    survey_p = sub.add_parser("survey", help="classify the file window by window")
    survey_p.add_argument("file")
    survey_p.add_argument("--window", type=int, default=WINDOW)
    survey_p.add_argument("--only", help="show only windows reading as this")
    survey_p.set_defaults(func=cmd_survey)

    header_p = sub.add_parser("header", help="what the model says about itself")
    header_p.add_argument("file")
    header_p.add_argument("--limit", type=int, default=8)
    header_p.set_defaults(func=cmd_header)

    offsets_p = sub.add_parser("offsets", help="runs of ascending in-file offsets")
    offsets_p.add_argument("file")
    offsets_p.add_argument("--least", type=int, default=4, help="shortest run to show")
    offsets_p.add_argument("--limit", type=int, default=20)
    offsets_p.set_defaults(func=cmd_offsets)

    at_p = sub.add_parser("at", help="dump one offset as hex, text and floats")
    at_p.add_argument("file")
    at_p.add_argument("offset", help="e.g. 0x15f5c")
    at_p.add_argument("--rows", type=int, default=8)
    at_p.set_defaults(func=cmd_at)

    strings_p = sub.add_parser("strings", help="printable runs, with offsets")
    strings_p.add_argument("file")
    strings_p.add_argument("--min", type=int, default=4)
    strings_p.add_argument("--search")
    strings_p.set_defaults(func=cmd_strings)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
