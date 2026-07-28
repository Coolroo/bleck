"""Symbol tables: turning a game function's name into its address.

Two sources, deliberately kept separate.

**`spm.<version>.lst`** (spm-headers, MIT) is what `elf2rel` consumes. It is
curated and small — **976 entries for eu0** — and carries only `address:name`.

**`spm-decomp/config/<VERSION>/symbols.txt`** is far larger and typed:
**4,584 human-named symbols for EU0, 3,960 of them functions**, each with a
section, a size and a kind. That is ~4.7x the lst, and the types are what allow
"you called `pouchCoin`, which is data, not a function" at compile time instead
of a REL that jumps into a table.

⚠️ **`spm-decomp` states no licence** (D54), so nothing from it is vendored.
Point `BLECK_DECOMP` at your own clone; absent, everything here degrades to the
lst and nothing breaks.

⚠️ Two figures worth not repeating: D39 recorded "~9,566 human-named", which is
not what the file contains — see above, measured. And `relF/symbols.txt` looks
tempting at 30,162 lines but holds only **216** human names, at **REL-relative**
addresses that cannot be linked the way absolute DOL symbols are.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from bleck.common.errors import BleckError

#: `mapDataPtr = .text:0x800294E0; // type:function size:0xC8 scope:global`
#: The `@`-prefixed exception-table entries (`@etb_*`) deliberately do not match:
#: they are compiler bookkeeping, ~9,600 of them, and useless to a mod.
_DECOMP = re.compile(
    r"^(?P<name>\w+)\s*=\s*\.?(?P<section>\w+):0x(?P<addr>[0-9A-Fa-f]+);"
    r"(?:\s*//\s*(?P<rest>.*))?$"
)

#: `800294e0:mapDataPtr`
_LST = re.compile(r"^(?P<addr>[0-9A-Fa-f]{8}):(?P<name>\S+)\s*$")

#: Names the decomp generates for undecompiled code. Valid symbols, but nobody
#: is going to call `func_8012ab34` by name, so they are noise in a listing.
_GENERATED = re.compile(r"^(?:lbl|func|jumptable|__vt|_ctors|_dtors)_[0-9A-Fa-f]+$")

FUNCTION = "function"


class SymbolError(BleckError):
    """A symbol table is missing or unreadable."""


@dataclass(frozen=True)
class Symbol:
    """One named address in the game."""

    name: str
    address: int
    section: str = ""
    kind: str = ""
    size: int = 0
    scope: str = ""

    @property
    def is_function(self) -> bool:
        return self.kind == FUNCTION

    @property
    def is_generated(self) -> bool:
        """A placeholder name, not something a person would write."""
        return bool(_GENERATED.match(self.name))

    def describe(self) -> str:
        kind = self.kind or "?"
        size = f"  {self.size} bytes" if self.size else ""
        return f"{self.address:08X}  {self.name:<40} {kind}{size}"

    def to_lst(self) -> str:
        return f"{self.address:08x}:{self.name}"


@dataclass(frozen=True)
class Disagreement:
    """The same name at two different addresses."""

    name: str
    lst_address: int
    decomp_address: int

    def describe(self) -> str:
        return (
            f"{self.name}: lst says {self.lst_address:08X}, "
            f"decomp says {self.decomp_address:08X}"
        )


@dataclass(frozen=True)
class SymbolTable:
    """Everything one source knows."""

    symbols: list[Symbol]
    source: Path

    def find(self, name: str) -> Symbol | None:
        for symbol in self.symbols:
            if symbol.name == name:
                return symbol
        return None

    def search(self, text: str) -> list[Symbol]:
        needle = text.lower()
        return [s for s in self.symbols if needle in s.name.lower()]

    @property
    def named(self) -> list[Symbol]:
        """Symbols a person could plausibly type."""
        return [s for s in self.symbols if not s.is_generated]

    @property
    def functions(self) -> list[Symbol]:
        return [s for s in self.named if s.is_function]

    def summary(self) -> str:
        typed = " ".join(
            f"{kind}={sum(1 for s in self.named if s.kind == kind)}"
            for kind in sorted({s.kind for s in self.named if s.kind})
        )
        return f"{len(self.symbols)} symbols, {len(self.named)} named" + (
            f"  ({typed})" if typed else ""
        )


def parse_decomp(text: str, source: Path) -> SymbolTable:
    """Read `spm-decomp`'s `symbols.txt`."""
    found = []
    for line in text.splitlines():
        match = _DECOMP.match(line.strip())
        if not match:
            continue
        rest = match["rest"] or ""
        found.append(
            Symbol(
                name=match["name"],
                address=int(match["addr"], 16),
                section=match["section"],
                kind=_tag(rest, "type"),
                size=int(_tag(rest, "size") or "0", 0),
                scope=_tag(rest, "scope"),
            )
        )
    return SymbolTable(symbols=found, source=source)


def parse_lst(text: str, source: Path) -> SymbolTable:
    """Read a `spm.<version>.lst`, the format `elf2rel` consumes."""
    found = [
        Symbol(name=match["name"], address=int(match["addr"], 16))
        for match in (_LST.match(line.strip()) for line in text.splitlines())
        if match
    ]
    return SymbolTable(symbols=found, source=source)


def read(path: Path) -> SymbolTable:
    """Read either format, chosen by what the file looks like."""
    if not path.is_file():
        raise SymbolError(f"no symbol table at {path}")
    text = path.read_text(encoding="utf-8", errors="replace")
    parser = parse_decomp if path.suffix == ".txt" else parse_lst
    return parser(text, path)


def compare(lst: SymbolTable, decomp: SymbolTable) -> list[Disagreement]:
    """Names both tables know, at addresses they disagree about.

    Worth checking before trusting a merge: the two are maintained separately,
    and a disagreement means one of them would send a call to the wrong place.
    """
    by_name = {symbol.name: symbol for symbol in decomp.symbols}
    return [
        Disagreement(s.name, s.address, by_name[s.name].address)
        for s in lst.symbols
        if s.name in by_name and by_name[s.name].address != s.address
    ]


def merge(lst: SymbolTable, decomp: SymbolTable) -> SymbolTable:
    """Both tables as one. **The decomp wins any disagreement.**

    The instinct is the other way -- the lst is what has been building working
    mods. But every disagreement found so far shows the lst pointing at the
    *neighbouring* function, which the decomp also names:

    | name | lst address | what the decomp calls that address |
    |---|---|---|
    | `strlen` | `80267018` | `TRK_strlen` — the debugger's copy |
    | `evt_fairy_flag_onoff` | `800E8214` | `evt_fairy_flag_onoff_all` |

    In both cases the decomp holds *both* symbols and the lst picked the wrong
    one, so preferring the lst would keep a known-wrong address. It also keeps
    the type and size, which the lst format cannot carry at all.

    ⚠️ Nothing is silent: `compare` lists every disagreement, and callers are
    expected to show it. Two cases is not a large enough sample to make this a
    law -- see D60.
    """
    merged = {symbol.name: symbol for symbol in lst.symbols}
    merged.update({symbol.name: symbol for symbol in decomp.named})
    return SymbolTable(
        symbols=sorted(merged.values(), key=lambda s: (s.address, s.name)),
        source=decomp.source,
    )


def write_lst(table: SymbolTable, path: Path, note: str = "") -> int:
    """Write a table in the format `elf2rel` reads. Returns the count written."""
    lines = [
        "/* Generated by `bleck symbols export`. Do not edit by hand. */",
        f"/* {note} */" if note else "",
        "",
    ]
    lines += [symbol.to_lst() for symbol in table.symbols]
    # newline="" so the file is byte-identical on every platform.
    path.write_text(
        "\n".join(line for line in lines if line is not None) + "\n",
        encoding="utf-8",
        newline="",
    )
    return len(table.symbols)


#: Inside a spm-decomp clone. Region directories are upper case there.
DECOMP_SYMBOLS = "config/{version}/symbols.txt"


def decomp_path(version: str, root: Path | None) -> Path | None:
    """Where a spm-decomp clone keeps this version's table, if configured."""
    if root is None:
        return None
    path = root / DECOMP_SYMBOLS.format(version=version.upper())
    return path if path.is_file() else None


def best_available(lst_path: Path, decomp_root: Path | None, version: str) -> SymbolTable:
    """The richest table that can be assembled, degrading to the lst alone.

    Used wherever a name has to be resolved, so configuring `BLECK_DECOMP` makes
    ~94 more of the game's documented builtins linkable without changing
    anything else.
    """
    lst = read(lst_path)
    found = decomp_path(version, decomp_root)
    return merge(lst, read(found)) if found else lst


def _tag(text: str, key: str) -> str:
    match = re.search(rf"\b{key}:(\S+)", text)
    return match[1] if match else ""
