#!/usr/bin/env python3
"""List every effect the game can spawn, read straight out of the DOL.

An effect is a fourth kind of entity, alongside NPCs, map objects and items, and
nothing enumerated it before -- which is why the Pure Hearts went unfound
through four exhaustive searches (D171). They are not on the disc as named
assets: an effect's name is a string in the DOL that its entry function stores
into `EffEntry+0x14`.

So this finds them the only way that works. Every effect entry function calls
`effEntry` at 0x800616dc; each call site is one effect kind. From there the
function stores a name pointer at +0x14, and that pointer is built the way the
game builds all its addresses -- `lis` then `addi` -- so the registers have to be
tracked rather than pattern-matched (the same reason `dolscan xref` exists).

    uv run python scripts/dump_effects.py
    uv run python scripts/dump_effects.py --grep beam

⚠️ This reads the extracted DOL, so it needs `work/extracted/eu0/` to exist. It
touches nothing and takes about a second; there is no reason to cache its output.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bleck.backends import dol as dolmod  # noqa: E402

EFF_ENTRY = 0x800616DC
NAME_OFFSET = 20
SCAN_INSTRUCTIONS = 40
NUL = bytes([0])

OP_BL = 18
OP_ADDI = 14
OP_ADDIS = 15
OP_ORI = 24
OP_STW = 36


@dataclass(frozen=True)
class Effect:
    """One effect kind: where it is spawned from, and what it is called."""

    entry: int
    call_site: int
    name: str
    name_address: int

    def describe(self) -> str:
        return f"{self.name:<28} entry 0x{self.entry:08X}  name 0x{self.name_address:08X}"


@dataclass(frozen=True)
class Image:
    """The DOL, plus the bytes, so an address can be read as a word or string."""

    dol: dolmod.Dol
    raw: bytes

    def word(self, address: int) -> int | None:
        section = self.dol.section_for(address)
        if section is None:
            return None
        at = section.file_offset(address)
        return int.from_bytes(self.raw[at : at + 4], "big")

    def text(self, address: int, limit: int = 64) -> str | None:
        section = self.dol.section_for(address)
        if section is None:
            return None
        at = section.file_offset(address)
        blob = self.raw[at : at + limit].split(NUL)[0]
        if not blob or any(c < 32 or c >= 127 for c in blob):
            return None
        return blob.decode("ascii")


def _signed16(value: int) -> int:
    return value - 0x10000 if value & 0x8000 else value


def call_sites(image: Image) -> list[int]:
    """Every `bl effEntry`, which is one per effect kind."""
    found = []
    for section in image.dol.loaded:
        if not section.is_text:
            continue
        for address in range(section.address, section.end, 4):
            word = image.word(address)
            if word is None or (word >> 26) != OP_BL:
                continue
            displacement = word & 0x03FFFFFC
            if displacement & 0x02000000:
                displacement -= 0x04000000
            target = displacement if word & 2 else address + displacement
            if target & 0xFFFFFFFF == EFF_ENTRY:
                found.append(address)
    return found  # pylint: disable=container-return


def name_after(image: Image, call_site: int) -> Effect | None:
    """Track registers forward from the call until the name is stored at +0x14.

    ⚠️ A two-instruction search finds nothing here. The game builds an address as
    `lis` plus `addi`, often with other work interleaved, so the register file
    has to be followed.
    """
    registers: dict[int, int] = {}
    for step in range(SCAN_INSTRUCTIONS):
        address = call_site + 4 * step
        word = image.word(address)
        if word is None:
            return None
        opcode = word >> 26
        rd = (word >> 21) & 0x1F
        ra = (word >> 16) & 0x1F
        immediate = word & 0xFFFF

        if opcode == OP_ADDIS:
            base = registers.get(ra, 0) if ra else 0
            registers[rd] = (base + (immediate << 16)) & 0xFFFFFFFF
        elif opcode == OP_ADDI:
            base = registers.get(ra, 0) if ra else 0
            registers[rd] = (base + _signed16(immediate)) & 0xFFFFFFFF
        elif opcode == OP_ORI:
            registers[ra] = (registers.get(rd, 0) | immediate) & 0xFFFFFFFF
        elif opcode == OP_STW and _signed16(immediate) == NAME_OFFSET:
            pointer = registers.get(rd)
            if pointer is None:
                continue
            text = image.text(pointer)
            if text:
                return Effect(_function_start(image, call_site), call_site, text, pointer)
    return None


def _function_start(image: Image, inside: int) -> int:
    """Walk back to the `stwu r1, -n(r1)` that opens the function."""
    for step in range(1, 400):
        address = inside - 4 * step
        word = image.word(address)
        if word is None:
            break
        if (word >> 16) == 0x9421:
            return address
    return inside


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dol", default="work/extracted/eu0/sys/main.dol")
    parser.add_argument("--grep", help="only show effects whose name contains this")
    args = parser.parse_args(argv)

    path = Path(args.dol)
    if not path.exists():
        print(f"no DOL at {path} -- extract a disc first", file=sys.stderr)
        return 1

    image = Image(dolmod.read(path), path.read_bytes())
    sites = call_sites(image)
    effects = [e for e in (name_after(image, s) for s in sites) if e is not None]
    effects.sort(key=lambda e: e.name)

    shown = [e for e in effects if not args.grep or args.grep.lower() in e.name.lower()]
    for effect in shown:
        print(f"  {effect.describe()}")
    print(f"\n{len(shown)} of {len(effects)} named effects, from {len(sites)} call sites")
    if len(effects) < len(sites):
        print(f"warning: {len(sites) - len(effects)} call site(s) had no readable name")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
