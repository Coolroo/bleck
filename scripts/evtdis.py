#!/usr/bin/env python3
"""Disassemble one of the game's own `evt` scripts.

`bleck` compiles *to* evt and has never read it back, so every question about
what a vanilla script does has been answered by reading raw hex. This closes
that: point it at an address and get named instructions.

    uv run python scripts/evtdis.py 0x8046AA58          # Count Bleck's onSpawn
    uv run python scripts/evtdis.py 0x8046AA58 --raw    # keep the hex alongside

Script addresses come from the template table -- `onSpawnScript` at
`NPCEnemyTemplate+0x30`, `moveScript` at +0x38, and so on. `--template 196`
lists them for one template instead of taking an address.

⚠️ **Only DOL scripts.** A pointer into a REL cannot be followed without knowing
where that REL was loaded, and the game's boss scripts are split across both.
An address outside the DOL is reported as such rather than decoded as garbage.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bleck.backends import dol as dolmod  # noqa: E402
from bleck.script import evt  # noqa: E402

NUL = bytes([0])
SYMBOLS = "work/upstream/spm-headers/linker/spm.eu0.lst"
TEMPLATE_BASE = 0x80449888
TEMPLATE_STRIDE = 0x68
MAX_INSTRUCTIONS = 4000

#: An operand's numeric range encodes its storage class -- see `bleck/script/evt.py`.
LOCAL_WORK = -30000000
FLOAT_BASE = -240000000

TEMPLATE_SCRIPTS = (
    (0x30, "onSpawnScript"),
    (0x34, "initScript"),
    (0x38, "moveScript"),
    (0x3C, "onHitScript"),
    (0x40, "pickupScript"),
    (0x44, "throwScript"),
    (0x48, "deathScript"),
    (0x4C, "atkScript"),
    (0x50, "miscScript"),
    (0x54, "kouraKickScript"),
)


@dataclass(frozen=True)
class Instruction:
    """One decoded instruction: where it is, what it is, what it takes."""

    address: int
    opcode: int
    name: str
    arguments: list[int]  # pylint: disable=container-return


@dataclass(frozen=True)
class Image:
    """The DOL plus its bytes, so an address can be read as a word or a string."""

    dol: dolmod.Dol
    raw: bytes
    symbols: dict[int, str]

    def holds(self, address: int) -> bool:
        return self.dol.section_for(address) is not None

    def word(self, address: int) -> int | None:
        section = self.dol.section_for(address)
        if section is None:
            return None
        at = section.file_offset(address)
        return int.from_bytes(self.raw[at : at + 4], "big")

    def text(self, address: int, limit: int = 48) -> str | None:
        section = self.dol.section_for(address)
        if section is None:
            return None
        at = section.file_offset(address)
        blob = self.raw[at : at + limit].split(NUL)[0]
        if not blob or any(c < 32 or c >= 127 for c in blob):
            return None
        return blob.decode("ascii")


def load_symbols(path: Path) -> dict[int, str]:
    """Address to name, for putting a name on every USER_FUNC target."""
    found: dict[int, str] = {}
    if not path.exists():
        return found
    for line in path.read_text(errors="replace").splitlines():
        line = line.strip()
        if ":" not in line or line.startswith("//"):
            continue
        head, _, name = line.partition(":")
        try:
            found[int(head, 16)] = name.strip()
        except ValueError:
            continue
    return found


def describe(image: Image, value: int) -> str:
    """Render one operand, decoding its storage class and any string it points at."""
    signed = value - 0x100000000 if value & 0x80000000 else value

    if LOCAL_WORK <= signed < LOCAL_WORK + 1000:
        return f"LW({signed - LOCAL_WORK})"
    if FLOAT_BASE <= signed < FLOAT_BASE + 100000000:
        return f"{(signed - FLOAT_BASE) / evt.FLOAT_SCALE:g}f"
    if 0x80000000 <= value < 0x81800000:
        name = image.symbols.get(value)
        if name:
            return f"&{name}"
        as_text = image.text(value)
        if as_text:
            return f'"{as_text}"'
        return f"0x{value:08X}"
    return str(signed)


def disassemble(image: Image, start: int) -> list[Instruction]:
    """Walk instructions until the script ends, or something stops making sense."""
    out: list[Instruction] = []
    address = start
    depth = 0
    for _ in range(MAX_INSTRUCTIONS):
        header = image.word(address)
        if header is None:
            break
        opcode = header & 0xFFFF
        declared = header >> 16

        try:
            which = evt.Opcode(opcode)
        except ValueError:
            out.append(Instruction(address, opcode, f"?? 0x{opcode:04X}", []))
            break

        if which is evt.Opcode.USER_FUNC:
            count = declared
        else:
            count = evt.ARGUMENT_COUNTS.get(which, declared)
        arguments = []
        for i in range(count):
            value = image.word(address + 4 * (1 + i))
            arguments.append(0 if value is None else value)
        out.append(Instruction(address, opcode, which.name, arguments))

        if which in (evt.Opcode.DO, evt.Opcode.SWITCH, evt.Opcode.SWITCHI):
            depth += 1
        elif which in (evt.Opcode.WHILE, evt.Opcode.END_SWITCH):
            depth = max(0, depth - 1)
        elif which is evt.Opcode.END_SCRIPT and depth == 0:
            break

        address += 4 * (1 + count)
    return out


def render(image: Image, code: list[Instruction], show_raw: bool) -> None:
    indent = 0
    opens = {"DO", "SWITCH", "SWITCHI", "IF_", "ELSE", "CASE_", "INLINE_EVT", "BROTHER_EVT"}
    for step in code:
        name = step.name
        closing = name in ("WHILE", "END_IF", "END_SWITCH", "CASE_END", "ELSE",
                           "END_INLINE", "END_BROTHER")
        if closing:
            indent = max(0, indent - 1)

        parts = []
        for i, value in enumerate(step.arguments):
            # A USER_FUNC's first word is the function, not an argument.
            if name == "USER_FUNC" and i == 0:
                parts.append(image.symbols.get(value) or f"0x{value:08X}")
            else:
                parts.append(describe(image, value))
        head = f"  0x{step.address:08X}  "
        if show_raw:
            words = [image.word(step.address + 4 * i) or 0 for i in range(1 + len(step.arguments))]
            head += " ".join(f"{w:08X}" for w in words[:5]).ljust(45) + "  "
        body = "    " * indent + name
        if parts:
            body += ("(" + ", ".join(parts[1:]) + ")") if name == "USER_FUNC" else (
                " " + ", ".join(parts))
            if name == "USER_FUNC":
                body = "    " * indent + parts[0] + "(" + ", ".join(parts[1:]) + ")"
        print(head + body)

        if any(name.startswith(p) or name == p for p in opens) and not closing:
            indent += 1


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("address", nargs="?", help="script address, e.g. 0x8046AA58")
    parser.add_argument("--template", type=int, help="list one template's scripts instead")
    parser.add_argument("--dol", default="work/extracted/eu0/sys/main.dol")
    parser.add_argument("--symbols", default=SYMBOLS)
    parser.add_argument("--raw", action="store_true", help="show the hex alongside")
    args = parser.parse_args(argv)

    path = Path(args.dol)
    if not path.exists():
        print(f"no DOL at {path} -- extract a disc first", file=sys.stderr)
        return 1
    image = Image(dolmod.read(path), path.read_bytes(), load_symbols(Path(args.symbols)))

    if args.template is not None:
        at = TEMPLATE_BASE + args.template * TEMPLATE_STRIDE
        print(f"template {args.template} at 0x{at:08X}")
        for offset, name in TEMPLATE_SCRIPTS:
            value = image.word(at + offset)
            if value is None:
                continue
            where = "DOL" if image.holds(value) else "REL or null"
            print(f"   +0x{offset:02X} {name:<16} 0x{value:08X}  ({where})")
        return 0

    if not args.address:
        parser.error("give an address, or --template N")
    start = int(args.address, 0)
    if not image.holds(start):
        print(f"0x{start:08X} is not in the DOL -- it is a REL address, "
              f"and this cannot follow those", file=sys.stderr)
        return 1

    code = disassemble(image, start)
    print(f"script at 0x{start:08X}  ({len(code)} instructions)")
    render(image, code, args.raw)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
