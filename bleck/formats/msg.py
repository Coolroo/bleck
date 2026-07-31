"""The game's own message files, read from the user's disc.

⛔ **This exists so `bleck` ships no game text.** The item and NPC catalogs used
to carry an `english` field for every row — 961 strings of Nintendo's localised
display text, bundled into the PyInstaller binary (D194). The internal names
beside them (`e_kuribo`, `ITEM_ID_NULL`) are identifiers and stay; the prose
does not.

So a catalog now ships the **message key**, and the text behind it is looked up
here against `files/msg/<lang>/` on whatever disc the user extracted. No disc,
no English names — and the CLI falls back to the internal name, which is what a
modder addresses things by anyway.

## The format

A flat run of NUL-terminated strings, alternating key and value from byte 0,
NUL-padded at the end. ⚠️ **Earlier files win**, so `global.txt` — first
alphabetically — is authoritative where two files define the same key.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

#: Where the message directories live, relative to an extracted disc root.
MSG_DIR = "files/msg"

#: Preferred order for an English table. `UK` and `US` are both English; UK
#: first only because it is the PAL build this project anchors to (eu0).
ENGLISH = ("UK", "US")


@dataclass(frozen=True)
class Messages:
    """One language's key-to-text table, and where it came from."""

    language: str
    source: Path
    text: dict = field(default_factory=dict)  # pylint: disable=container-return

    def get(self, key: str) -> str:
        return self.text.get(key, "")

    def __len__(self) -> int:
        return len(self.text)


def read_directory(directory: Path) -> dict:  # pylint: disable=container-return
    """Every key in one `files/msg/<lang>/` directory."""
    table: dict[str, str] = {}
    for path in sorted(directory.glob("*.txt")):
        parts = path.read_bytes().split(b"\0")
        while parts and not parts[-1]:
            parts.pop()
        for key, value in zip(parts[0::2], parts[1::2], strict=False):
            name = key.decode("utf-8", "replace")
            if name not in table:
                table[name] = value.decode("utf-8", "replace")
    return table


def english(base: Path | None) -> Messages | None:
    """The English message table from an extracted disc, or None without one.

    ⚠️ Returns None rather than raising. Every caller is decorating a name it
    already has, so a missing disc costs prettiness and nothing else — and
    `bleck` has to stay fully usable on a machine with no game data at all.
    """
    if base is None or not base.is_dir():
        return None
    for language in ENGLISH:
        directory = base / MSG_DIR / language
        if directory.is_dir():
            found = read_directory(directory)
            if found:
                return Messages(language, directory, found)
    return None
