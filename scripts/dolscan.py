"""Read the game's DOL: disassemble, find strings, and cross-reference them.

`eu0`'s public symbol list names a few thousand functions out of a game with
far more, so most research here starts from something that is *not* a symbol.
The technique that keeps working (D128, D130, D133, D136):

1. Find a string — an assert `__FILE__`, a `printf` format, a map name.
2. Cross-reference it to the code that materialises its address.
3. Disassemble around that, and read.

⚠️ **The game builds addresses as a base register plus an offset**, not one
`lis`/`addi` pair, so a naive two-instruction search finds nothing. `xref`
tracks register values across `lis`/`addis`/`addi`, which is why it finds them.

Every subcommand reads the extracted base's `sys/main.dol`, so `bleck extract`
must have been run. Addresses are `eu0` virtual addresses.

    uv run python scripts/dolscan.py dis 0x80029730 40
    uv run python scripts/dolscan.py strings setup_data
    uv run python scripts/dolscan.py xref 0x80323BB0 --window 0x40
    uv run python scripts/dolscan.py calls 0x40 0x800d8b88

⚠️ Needs `powerpc-eabi-objdump` for `dis` only; the rest is pure Python. It is
found the same way the toolchain is, so a devkitPPC install is enough.
"""

from __future__ import annotations

import argparse
import os
import re
import struct
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# pylint: disable=wrong-import-position
from bleck.backends import dol as dolfile
from bleck.backends import toolchain
from bleck.mods import registry

#: DOL sections 0..6 are text; the rest are data. Scans that look for
#: instructions must skip data or they report noise as code.
TEXT_SECTIONS = 6

_PRINTABLE = re.compile(rb"[ -~]{4,}")


@dataclass(frozen=True)
class Image:
    """A parsed DOL and the bytes it came from."""

    raw: bytes
    parsed: object
    path: Path

    def at(self, address: int, size: int) -> bytes | None:
        """`size` bytes at a virtual address, or None if unmapped."""
        for section in self.parsed.sections:
            if not section.size:
                continue
            if section.address <= address < section.address + section.size:
                start = section.offset + (address - section.address)
                return self.raw[start : start + size]
        return None

    def text(self):  # pylint: disable=container-return
        for section in self.parsed.sections:
            if section.size and section.index <= TEXT_SECTIONS:
                yield section


def load() -> Image:
    path = registry.base_root() / "sys" / "main.dol"
    if not path.is_file():
        raise SystemExit(f"no DOL at {path} -- run `bleck extract` first")
    raw = path.read_bytes()
    return Image(raw=raw, parsed=dolfile.parse(raw, path), path=path)


def _words(image: Image, section):
    blob = image.raw[section.offset : section.offset + section.size]
    count = len(blob) // 4
    return struct.unpack(f">{count}I", blob[: count * 4])


def _s16(value: int) -> int:
    return value - 0x10000 if value & 0x8000 else value


def cmd_dis(args: argparse.Namespace) -> int:
    """Disassemble `count` instructions at a virtual address."""
    image = load()
    blob = image.at(args.address, args.count * 4)
    if blob is None:
        print(f"0x{args.address:08X} is not in any section")
        return 1

    objdump = toolchain.find_objdump() if hasattr(toolchain, "find_objdump") else None
    if objdump is None:
        objdump = _find_objdump()
    if objdump is None:
        print("no powerpc objdump found; install devkitPPC or set BLECK_GCC")
        return 1

    with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as handle:
        handle.write(blob)
        temp = handle.name
    try:
        done = subprocess.run(
            [
                str(objdump), "-D", "-b", "binary", "-m", "powerpc", "-EB",
                f"--adjust-vma=0x{args.address:X}", temp,
            ],
            capture_output=True, text=True, check=False,
        )
    finally:
        os.unlink(temp)
    print(done.stdout or done.stderr)
    return 0


def _find_objdump() -> Path | None:
    """`objdump` beside whichever PowerPC `gcc` the toolchain located."""
    for name in ("powerpc-eabi-objdump", "powerpc-linux-gnu-objdump"):
        for suffix in ("", ".exe"):
            for root in (
                Path("C:/devkitPro/devkitPPC/bin"),
                Path("/opt/devkitpro/devkitPPC/bin"),
                Path("/usr/bin"),
            ):
                found = root / f"{name}{suffix}"
                if found.is_file():
                    return found
    return None


def cmd_strings(args: argparse.Namespace) -> int:
    """Every printable string containing `needle`, with its address."""
    image = load()
    needle = args.needle.encode()
    for section in image.parsed.sections:
        if not section.size:
            continue
        blob = image.raw[section.offset : section.offset + section.size]
        for match in _PRINTABLE.finditer(blob):
            if needle in match.group():
                where = section.address + match.start()
                print(f"0x{where:08X}  {match.group().decode()}")
    return 0


def cmd_xref(args: argparse.Namespace) -> int:
    """Find code that materialises a target address.

    ⚠️ Tracks register values across `lis`/`addis`/`addi`, because the game
    builds most addresses as a base plus an offset. `--window` reports
    near-misses too, so a base register that lands N bytes below the target is
    still found -- which is how the string tables in D128 were located.
    """
    image = load()
    for section in image.text():
        words = _words(image, section)
        reg: dict[int, int] = {}
        for index, word in enumerate(words):
            op, rd, ra, imm = word >> 26, (word >> 21) & 31, (word >> 16) & 31, word & 0xFFFF
            if op == 15:  # lis / addis
                reg[rd] = (_s16(imm) << 16) + (reg.get(ra, 0) if ra else 0)
            elif op == 14:  # addi
                if ra == 0:
                    reg[rd] = _s16(imm)
                elif ra in reg:
                    reg[rd] = (reg[ra] + _s16(imm)) & 0xFFFFFFFF
                else:
                    reg.pop(rd, None)
            else:
                reg.pop(rd, None)
                continue
            got = reg.get(rd)
            if got is not None and 0 <= (args.address - got) <= args.window:
                note = "" if got == args.address else f"  (base, +0x{args.address - got:X})"
                print(f"0x{section.address + index * 4:08X}  r{rd} = 0x{got:08X}{note}")
    return 0


def cmd_callers(args: argparse.Namespace) -> int:
    """Every `bl` that targets an address.

    ⚠️ **`xref` cannot answer this.** That command tracks `lis`/`addi` pairs
    building a *data* address; a function is reached by a `bl` with a relative
    displacement and no literal address appears anywhere. Asking `xref` who
    calls `GXSetVtxAttrFmt` returns nothing, which reads as "nobody" (D206).
    """
    image = load()
    target = int(args.address, 0)
    found = 0
    for section in image.text():
        words = _words(image, section)
        for index, word in enumerate(words):
            if word >> 26 != 18 or (word & 3) != 1:
                continue
            disp = word & 0x03FFFFFC
            if disp & 0x02000000:
                disp -= 0x04000000
            at = section.address + index * 4
            if ((at + disp) & 0xFFFFFFFF) == target:
                print(f"0x{at:08X}  bl 0x{target:08X}")
                found += 1
                if args.limit and found >= args.limit:
                    return 0
    if not found:
        print(f"no bl to 0x{target:08X}")
    return 0


def cmd_calls(args: argparse.Namespace) -> int:
    """Find `lwz rX, OFF(rY)` followed by a `bl` to one of `targets`.

    The shape of "reads a struct field, then does something with it" -- how
    D136 established that a door reads `interactScript` live rather than
    caching it at map load.
    """
    image = load()
    targets = {int(value, 0) for value in args.targets}
    for section in image.text():
        words = _words(image, section)
        for index, word in enumerate(words):
            if word >> 26 != 32 or (word & 0xFFFF) != args.offset:
                continue
            rd = (word >> 21) & 31
            for ahead in range(index + 1, min(index + 1 + args.window, len(words))):
                call = words[ahead]
                if call >> 26 != 18 or (call & 3) != 1:
                    continue
                disp = call & 0x03FFFFFC
                if disp & 0x02000000:
                    disp -= 0x04000000
                dest = (section.address + ahead * 4 + disp) & 0xFFFFFFFF
                if dest in targets:
                    print(
                        f"0x{section.address + index * 4:08X}  "
                        f"lwz r{rd},0x{args.offset:X}(..)  ->  bl 0x{dest:08X}"
                    )
                    # One line per load, not per call: several calls to the
                    # same target often sit inside one window, and repeating
                    # the load address reads as three findings rather than one.
                    break
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    dis = sub.add_parser("dis", help="disassemble at a virtual address")
    dis.add_argument("address", type=lambda v: int(v, 0))
    dis.add_argument("count", nargs="?", type=int, default=40)
    dis.set_defaults(func=cmd_dis)

    strings = sub.add_parser("strings", help="printable strings containing a needle")
    strings.add_argument("needle")
    strings.set_defaults(func=cmd_strings)

    xref = sub.add_parser("xref", help="code that materialises an address")
    xref.add_argument("address", type=lambda v: int(v, 0))
    xref.add_argument(
        "--window", type=lambda v: int(v, 0), default=0,
        help="also report bases up to N bytes below the target (try 0x40)",
    )
    xref.set_defaults(func=cmd_xref)

    callers = sub.add_parser("callers", help="every bl targeting an address")
    callers.add_argument("address", help="e.g. 0x8028EA78")
    callers.add_argument("--limit", type=int, default=40)
    callers.set_defaults(func=cmd_callers)

    calls = sub.add_parser("calls", help="a field load followed by a call")
    calls.add_argument("offset", type=lambda v: int(v, 0), help="e.g. 0x40")
    calls.add_argument("targets", nargs="+", help="one or more call destinations")
    calls.add_argument("--window", type=int, default=16)
    calls.set_defaults(func=cmd_calls)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
