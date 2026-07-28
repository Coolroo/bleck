"""Reading `main.dol`: which address lives at which file offset, and the word
there.

A DOL is 18 sections -- 7 text, 11 data -- each with a file offset, a load
address and a size, all in a fixed 0x100-byte header. That is enough to answer
"what instruction does the game actually have at 0x801adef0", which is what a
derived hook guard needs (D95).

⚠️ Only the DOL is mapped, and its span is wider than it looks: eu0's loads
`80004000..805B7720` across two text and eight data sections. An address above
that -- where the loader puts a REL -- is not in this file at all, and
`section_for` says so rather than guessing.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path

from bleck.common.errors import BleckError

#: 7 text then 11 data, each of the three tables in that order.
TEXT_SECTIONS = 7
DATA_SECTIONS = 11
SECTION_COUNT = TEXT_SECTIONS + DATA_SECTIONS

_OFFSETS_AT = 0x00
_ADDRESSES_AT = 0x48
_SIZES_AT = 0x90
_HEADER_SIZE = 0x100


class DolError(BleckError):
    """A DOL is missing, truncated, or does not parse."""


@dataclass(frozen=True)
class DolSection:
    """One loadable chunk of the DOL, and where it lands in memory."""

    index: int
    offset: int
    """Where the bytes start in the file."""

    address: int
    """Where the loader puts them."""

    size: int

    @property
    def is_text(self) -> bool:
        return self.index < TEXT_SECTIONS

    @property
    def name(self) -> str:
        return f"text{self.index}" if self.is_text else f"data{self.index}"

    @property
    def end(self) -> int:
        return self.address + self.size

    def holds(self, address: int) -> bool:
        return self.address <= address < self.end

    def file_offset(self, address: int) -> int:
        return self.offset + (address - self.address)

    def describe(self) -> str:
        return (
            f"{self.name}  {self.address:08X}..{self.end:08X}  "
            f"file +{self.offset:06X}  {self.size} bytes"
        )


@dataclass(frozen=True)
class Dol:
    """A parsed `main.dol`, with its bytes, so words can be read out of it."""

    path: Path
    sections: list[DolSection]
    data: bytes = field(repr=False, default=b"")

    bss_address: int = 0
    bss_size: int = 0
    entry_point: int = 0

    @property
    def loaded(self) -> list[DolSection]:
        """Sections with anything in them. An empty slot is padding, not code."""
        return [section for section in self.sections if section.size]

    def section_for(self, address: int) -> DolSection | None:
        """Which section holds `address`, or None when the DOL does not."""
        for section in self.loaded:
            if section.holds(address):
                return section
        return None

    def word_at(self, address: int) -> int | None:
        """The big-endian word the game has at `address`, or None if unmapped."""
        section = self.section_for(address)
        if section is None or address % 4:
            return None
        at = section.file_offset(address)
        if at + 4 > len(self.data):
            return None
        return int(struct.unpack_from(">I", self.data, at)[0])

    @property
    def address_range(self) -> str:
        """The loaded span, for an error that has to say what *is* covered."""
        low = min(section.address for section in self.loaded)
        high = max(section.end for section in self.loaded)
        return f"{low:08X}..{high:08X}"


def parse(data: bytes, path: Path) -> Dol:
    """Read a DOL's section table. The bytes are kept so words can be read."""
    if len(data) < _HEADER_SIZE:
        raise DolError(f"{path} is {len(data)} bytes, too short to be a DOL")

    offsets = struct.unpack_from(f">{SECTION_COUNT}I", data, _OFFSETS_AT)
    addresses = struct.unpack_from(f">{SECTION_COUNT}I", data, _ADDRESSES_AT)
    sizes = struct.unpack_from(f">{SECTION_COUNT}I", data, _SIZES_AT)
    bss_address, bss_size, entry_point = struct.unpack_from(">3I", data, 0xD8)

    sections = [
        DolSection(index=i, offset=offsets[i], address=addresses[i], size=sizes[i])
        for i in range(SECTION_COUNT)
    ]
    if not any(section.size for section in sections):
        raise DolError(f"{path} has no loadable sections; it is not a DOL")

    return Dol(
        path=path,
        sections=sections,
        data=data,
        bss_address=bss_address,
        bss_size=bss_size,
        entry_point=entry_point,
    )


def read(path: Path) -> Dol:
    if not path.is_file():
        raise DolError(f"no DOL at {path}")
    return parse(path.read_bytes(), path)
