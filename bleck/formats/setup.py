"""`setup/*.dat` — where the game's enemies and items are placed.

One file per map, named after it. After textures, this is the most obviously
moddable thing on the disc: it is what decides which enemies exist and where
they stand.

⚠️ **The game reads the standalone `files/setup/<map>.dat`** (D62). The copy
embedded in the map archive is ignored, so editing only that one does nothing.
`bleck mod build` warns about this, and writes both when it generates a file.

⛔ D53 concluded the opposite and is superseded. Its measurement was sound —
the embedded copy is the one that reaches MEM1 — but the inference from "in
fast RAM" to "in use" was wrong.

The layout is documented upstream in `spm-headers`
(`include/spm/setup_data.h`, MIT) and independently confirmed here by parsing
all 227 files on the disc:

    struct SetupFileV6 {
        u16 version;              // 1..6
        u16 padding;              // always 0 -- and read by nothing (D53)
        SetupEnemy enemies[100];  // ALWAYS 100; stride depends on version
        // v6 only, and only when the map places items:
        s32 itemCount;
        s32 itemVersion;          // always 20051201
        SetupItem items[itemCount];
    };

⚠️ **Only version 6 has a documented entry layout**, and it is 198 of the 227
files. Other versions are parsed as opaque entries of the correct stride, so
they still round-trip byte-exactly but expose no fields.

Everything not understood is preserved verbatim rather than rebuilt, so writing
a file back out is byte-identical unless a known field was changed. That is the
same standard the archive code holds itself to, and for the same reason: a mod
should change what the author asked for and nothing else.
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass, replace
from pathlib import Path

from bleck.common.errors import BleckError

#: Entry stride by version. `base size = 4 + 100 * stride` holds for every file
#: on the disc, which is what makes an arbitrary-looking size predictable.
STRIDE = {1: 28, 2: 96, 3: 100, 4: 104, 5: 108, 6: 112}

#: Fixed regardless of how many enemies a map uses; unused slots are zeroed.
#: This is why a nearly empty map still produces an 11 KB file.
ENEMY_SLOTS = 100

HEADER_SIZE = 4

#: The only version whose fields are documented.
DOCUMENTED_VERSION = 6

#: `SetupItem` is 16 bytes: u16 flags, u16 type, Vec3 pos.
ITEM_SIZE = 16

#: `itemVersion`, called SETUPOBJ_FORMAT_VERSION upstream. Every file with items
#: carries this exact value, confirmed on all 14 of them.
ITEM_VERSION = 20051201

# --- v6 enemy field offsets, from spm-headers' SetupEnemyV6 -----------------

_POS = 0x00
_TYPE = 0x0C
_INSTANCE_ID = 0x10
_GRAVITY_ROTATION = 0x6C


#: Template and tribe names, dumped from the game by `scripts/dump_npcs.py`.
#: Committed rather than recomputed: the names live behind pointers in the
#: game's own tables and exist only at runtime.
NPC_CATALOG = Path(__file__).with_name("npccatalog.json")


class SetupError(BleckError):
    """A setup file is malformed, or asked to do something it cannot."""


@dataclass(frozen=True)
class Species:
    """What a template actually spawns."""

    template: int
    tribe: int
    english: str = ""
    """From `npcdrv.h`'s `NPC_*` constants, which are keyed by *tribe*."""

    model: str = ""
    """The game's internal model name, e.g. `e_kuribo`."""

    def describe(self) -> str:
        if self.english and self.model:
            return f"{self.english} ({self.model})"
        return self.english or self.model or f"template {self.template}"


class NpcNames:
    """Template id -> what it spawns. Empty if the catalog is missing."""

    def __init__(self, templates=None, tribes=None) -> None:
        self._templates = templates or []
        self._tribes = tribes or []

    def __bool__(self) -> bool:
        return bool(self._templates)

    def lookup(self, template: int) -> Species | None:
        if not 0 <= template < len(self._templates):
            return None
        entry = self._templates[template]
        tribe = entry.get("tribe", -1)
        row = self._tribes[tribe] if 0 <= tribe < len(self._tribes) else {}
        return Species(
            template=template,
            tribe=tribe,
            english=row.get("english", ""),
            model=row.get("name", ""),
        )


def load_names(path: Path | None = None) -> NpcNames:
    """Read the committed NPC catalog. Absent is not an error -- names are a
    convenience, and every other operation works without them."""
    source = path or NPC_CATALOG
    if not source.is_file():
        return NpcNames()
    body = json.loads(source.read_text(encoding="utf-8"))
    return NpcNames(body.get("templates"), body.get("tribes"))


@dataclass(frozen=True)
class Enemy:
    """One placement slot.

    `raw` holds the whole entry. Named fields are views onto it, and `replace_*`
    returns a new entry with `raw` patched, so the ~70 undocumented bytes travel
    untouched.
    """

    slot: int
    raw: bytes
    version: int

    @property
    def documented(self) -> bool:
        return self.version == DOCUMENTED_VERSION

    @property
    def is_empty(self) -> bool:
        """Whether this slot places nothing.

        🔶 Judged by `type == 0`. Template 0 appears to be a sentinel: 5,110 of
        the 6,438 non-zero slots on the disc have it, and they carry no position
        either. A whole-entry zero test does *not* work -- unused slots are not
        blank, they hold a default in an undocumented field.
        """
        if not self.documented:
            return not any(self.raw)
        return self.template == 0

    @property
    def template(self) -> int:
        """Index into the game's `npcEnemyTemplates`, which decides what spawns.

        ⚠️ Not an `NPC_*` value from `npcdrv.h` -- those are *tribe* ids, and
        there are 535 of them against 435 templates. A template names its tribe
        separately.
        """
        return self._int(_TYPE)

    @property
    def instance_id(self) -> int:
        return self._int(_INSTANCE_ID)

    @property
    def position(self) -> Position:
        x, y, z = struct.unpack_from(">3f", self.raw, _POS)
        return Position(x, y, z)

    @property
    def gravity_rotation(self) -> float:
        """Degrees anti-clockwise about the z-axis."""
        return struct.unpack_from(">f", self.raw, _GRAVITY_ROTATION)[0]

    def _int(self, offset: int) -> int:
        if not self.documented:
            raise SetupError(
                f"version {self.version} entry fields are undocumented; "
                f"only version {DOCUMENTED_VERSION} exposes them"
            )
        return struct.unpack_from(">i", self.raw, offset)[0]

    def with_template(self, template: int) -> Enemy:
        return self._patched(_TYPE, struct.pack(">i", template))

    def with_position(self, position: Position) -> Enemy:
        return self._patched(_POS, struct.pack(">3f", *position.as_tuple()))

    def cleared(self) -> Enemy:
        """An empty slot, keeping the entry's size."""
        return replace(self, raw=bytes(len(self.raw)))

    def _patched(self, offset: int, data: bytes) -> Enemy:
        if not self.documented:
            raise SetupError(
                f"cannot edit a version {self.version} entry: its layout is "
                f"undocumented, and guessing would corrupt the file"
            )
        raw = bytearray(self.raw)
        raw[offset : offset + len(data)] = data
        return replace(self, raw=bytes(raw))

    def describe(self) -> str:
        if not self.documented:
            return f"[{self.slot:>3}] (version {self.version}, fields unknown)"
        if self.is_empty:
            return f"[{self.slot:>3}] empty"
        rotation = self.gravity_rotation
        spin = f"  gravity {rotation:g}deg" if rotation else ""
        return (
            f"[{self.slot:>3}] template {self.template:<4} "
            f"at {self.position.describe()}{spin}"
        )


@dataclass(frozen=True)
class Position:
    """A placement, in the game's world units."""

    x: float
    y: float
    z: float

    def as_tuple(self) -> tuple[float, float, float]:  # pylint: disable=container-return
        return (self.x, self.y, self.z)

    def describe(self) -> str:
        return f"({self.x:g}, {self.y:g}, {self.z:g})"


@dataclass(frozen=True)
class Item:
    """A placed item. Upstream notes only type 0 -- a coin -- is supported."""

    flags: int
    type: int
    position: Position

    #: Upstream: "0x10 and 0x1 required to spawn, others unused".
    SPAWNS = 0x11

    @property
    def spawns(self) -> bool:
        return self.flags & self.SPAWNS == self.SPAWNS

    def describe(self) -> str:
        kind = "coin" if self.type == 0 else f"type {self.type}"
        state = "" if self.spawns else "  (will not spawn)"
        return f"{kind} at {self.position.describe()}  flags 0x{self.flags:02x}{state}"

    def to_bytes(self) -> bytes:
        return struct.pack(">HH3f", self.flags, self.type, *self.position.as_tuple())


@dataclass(frozen=True)
class SetupFile:
    """One map's placements."""

    version: int
    enemies: list[Enemy]
    items: list[Item]
    item_version: int = ITEM_VERSION
    has_item_section: bool = False

    @property
    def stride(self) -> int:
        return STRIDE[self.version]

    @property
    def used(self) -> list[Enemy]:
        return [enemy for enemy in self.enemies if not enemy.is_empty]

    def summary(self) -> str:
        parts = [f"version {self.version}", f"{len(self.used)}/{ENEMY_SLOTS} enemies"]
        if self.has_item_section:
            parts.append(f"{len(self.items)} item(s)")
        return ", ".join(parts)

    def to_bytes(self) -> bytes:
        out = bytearray(struct.pack(">HH", self.version, 0))
        for enemy in self.enemies:
            if len(enemy.raw) != self.stride:
                raise SetupError(
                    f"slot {enemy.slot} is {len(enemy.raw)} bytes, "
                    f"expected {self.stride} for version {self.version}"
                )
            out += enemy.raw
        if self.has_item_section:
            out += struct.pack(">ii", len(self.items), self.item_version)
            for item in self.items:
                out += item.to_bytes()
        return bytes(out)


def parse(data: bytes, origin: str = "setup file") -> SetupFile:
    """Read a setup file. Raises `SetupError` on anything unexpected."""
    if len(data) < HEADER_SIZE:
        raise SetupError(f"{origin}: too short to be a setup file")

    version, padding = struct.unpack_from(">HH", data, 0)
    if version not in STRIDE:
        known = ", ".join(str(v) for v in sorted(STRIDE))
        raise SetupError(f"{origin}: unknown setup version {version} (known: {known})")
    # Not an error: the field is padding and read by nothing, which is exactly
    # why D53 could use it as a marker. Worth noticing all the same.
    del padding

    stride = STRIDE[version]
    base = HEADER_SIZE + ENEMY_SLOTS * stride
    if len(data) < base:
        raise SetupError(
            f"{origin}: {len(data)} bytes, but version {version} needs at "
            f"least {base} for {ENEMY_SLOTS} slots"
        )

    enemies = [
        Enemy(
            slot=index,
            raw=data[HEADER_SIZE + index * stride : HEADER_SIZE + (index + 1) * stride],
            version=version,
        )
        for index in range(ENEMY_SLOTS)
    ]

    section = _parse_items(data, base, origin)
    return SetupFile(
        version=version,
        enemies=enemies,
        items=section.items,
        item_version=section.version,
        has_item_section=section.present,
    )


@dataclass(frozen=True)
class ItemSection:
    """The optional trailer holding placed items."""

    present: bool
    items: list[Item]
    version: int = ITEM_VERSION


def _parse_items(data: bytes, base: int, origin: str) -> ItemSection:
    """Read the item trailer, if the file has one.

    Only 14 files on the disc do, all version 6. Upstream notes that reading it
    from a file without one returns zeros "because of disc alignment" -- so
    absence is detected by length rather than by trusting a zero count.
    """
    if len(data) < base + 8:
        return ItemSection(present=False, items=[])

    count, version = struct.unpack_from(">ii", data, base)
    expected = base + 8 + count * ITEM_SIZE
    if count < 0 or len(data) < expected:
        raise SetupError(
            f"{origin}: item section claims {count} items, which needs "
            f"{expected} bytes but the file is {len(data)}"
        )

    items = []
    for index in range(count):
        flags, kind, x, y, z = struct.unpack_from(
            ">HH3f", data, base + 8 + index * ITEM_SIZE
        )
        items.append(Item(flags=flags, type=kind, position=Position(x, y, z)))
    return ItemSection(present=True, items=items, version=version)


def read(path: Path) -> SetupFile:
    if not path.exists():
        raise SetupError(f"no setup file at {path}")
    return parse(path.read_bytes(), origin=path.name)
