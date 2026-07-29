"""`setup/*.dat` — where the game's enemies and items are placed, one per map.

⚠️ The game reads the standalone `files/setup/<map>.dat` (D62); the copy inside
the map archive is ignored. `bleck mod build` warns, and writes both.
⛔ D53 said the reverse and is superseded — check which way round before copying.

Layout (spm-headers `include/spm/setup_data.h`, MIT; confirmed against all 227
files on the disc):

    struct SetupFileV6 {
        u16 version;              // 1..6
        u16 padding;              // always 0, and read by nothing
        SetupEnemy enemies[100];  // ALWAYS 100; stride depends on version
        // v6 only, and only when the map places items:
        s32 itemCount;
        s32 itemVersion;          // always 20051201
        SetupItem items[itemCount];
    };

⚠️ Only version 6 has a documented entry layout (198 of the 227 files). Other
versions parse as opaque entries of the correct stride: they round-trip
byte-exactly but expose no fields. Unrecognised bytes are always preserved
verbatim rather than rebuilt.
"""

from __future__ import annotations

import difflib
import json
import struct
from dataclasses import dataclass, field, replace
from functools import lru_cache
from pathlib import Path

from bleck.common.errors import BleckError
from bleck.formats.items import normalize

#: Entry stride by version. `base size = 4 + 100 * stride` holds disc-wide.
STRIDE = {1: 28, 2: 96, 3: 100, 4: 104, 5: 108, 6: 112}

#: Fixed regardless of how many enemies a map uses; unused slots are zeroed.
ENEMY_SLOTS = 100

HEADER_SIZE = 4

#: The only version whose fields are documented.
DOCUMENTED_VERSION = 6

#: `SetupItem` is 16 bytes: u16 flags, u16 type, Vec3 pos.
ITEM_SIZE = 16

#: How many items the game can load from one map, read out of the DOL (D128).
#:
#: ⚠️ **A hard ceiling, not a convention.** The loader allocates 8192 bytes --
#: `512 * ITEM_SIZE` -- then takes the count straight from the file and memcpys
#: `count * 16` bytes into it. A file claiming more overruns the allocation with
#: no check of any kind:
#:
#:     8017a9d4  li   r4, 8192      ; the allocation
#:     8017aa0c  bl   setupReadItemInfo
#:     8017aa54  slwi r5, r0, 4     ; count * 16, count from the FILE
#:     8017aa58  bl   memcpy
MAX_ITEMS = 512

#: `itemVersion`, SETUPOBJ_FORMAT_VERSION upstream. All 14 files with items
#: carry this exact value.
ITEM_VERSION = 20051201

# --- v6 enemy field offsets, from spm-headers' SetupEnemyV6 -----------------

_POS = 0x00
_TYPE = 0x0C
_INSTANCE_ID = 0x10
_GRAVITY_ROTATION = 0x6C


#: Template and tribe names, dumped from the game by `scripts/dump_npcs.py`.
#: Committed rather than recomputed: they exist only at runtime.
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


@dataclass(frozen=True)
class SpeciesMatch:
    """What a written enemy name resolved to, and enough to explain a failure.

    The item answer to the same question (`items.ItemMatch`), and three outcomes
    for the same reason: one template (`species`), several (`ambiguous`), or none
    (`near` holds the closest spellings).

    ⚠️ **Ambiguity is the common case here, not the exception.** 386 distinct
    English names cover the 423 named templates and only 382 are unique --
    `Goomba` alone names 35. Picking one would be a coin toss, so it is reported.
    """

    query: str
    species: Species | None = None
    ambiguous: list[Species] = field(default_factory=list)
    near: list[str] = field(default_factory=list)

    @property
    def found(self) -> bool:
        return self.species is not None

    @property
    def candidates(self) -> str:
        """The ambiguous templates as a list of numbers, for an error message."""
        return ", ".join(str(species.template) for species in self.ambiguous)


class NpcNames:
    """Template id -> what it spawns, and back again.

    `resolve` runs the other way -- a written name to a template id -- in tiers,
    most specific first, exactly as `items.ItemNames` does:

    1. the tribe's English name, e.g. `Squiglet`
    2. the tribe's model name, e.g. `e_kuribo`

    A tier that matches decides the answer even when it matches several
    templates: falling through to the model name would answer a different
    question than the one asked.

    Empty if the catalog is missing, in which case every name fails to resolve
    and every template id still works.
    """

    def __init__(self, templates=None, tribes=None) -> None:
        self._templates = templates or []
        self._tribes = tribes or []
        self._tiers = [
            self._index(lambda species: species.english),
            self._index(lambda species: species.model),
        ]

    def _index(self, alias):  # pylint: disable=container-return
        """Normalised name -> the template ids that answer to it."""
        table: dict[str, list[int]] = {}
        for template in range(len(self._templates)):
            species = self.lookup(template)
            if species is None:
                continue
            key = normalize(alias(species))
            if not key:
                continue
            found = table.setdefault(key, [])
            if template not in found:
                found.append(template)
        return table

    def __bool__(self) -> bool:
        return bool(self._templates)

    def resolve(self, text: str) -> SpeciesMatch:
        """Find the template a written name means.

        Never raises: the caller knows which file and line to blame, and there
        are three different failures to phrase.
        """
        key = normalize(text)
        if not key:
            return SpeciesMatch(query=text)
        for tier in self._tiers:
            found = tier.get(key)
            if not found:
                continue
            if len(found) == 1:
                return SpeciesMatch(query=text, species=self.lookup(found[0]))
            return SpeciesMatch(
                query=text,
                ambiguous=[self.lookup(template) for template in found],
            )
        return SpeciesMatch(query=text, near=self.suggest(text))

    def suggest(self, text: str, limit: int = 3) -> list[str]:
        """The closest names to something that resolved to nothing."""
        every = sorted({alias for tier in self._tiers for alias in tier})
        return difflib.get_close_matches(normalize(text), every, n=limit, cutoff=0.6)

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
    """Read the committed NPC catalog. Absent is not an error: names are a
    convenience, and every other operation works without them."""
    source = path or NPC_CATALOG
    if not source.is_file():
        return NpcNames()
    body = json.loads(source.read_text(encoding="utf-8"))
    return NpcNames(body.get("templates"), body.get("tribes"))


@lru_cache(maxsize=1)
def catalog() -> NpcNames:
    """The catalog, read and indexed once. A table naming an enemy per row
    would otherwise re-read a 100 KB file and rebuild both tiers per row.

    Tests that swap `NPC_CATALOG` must call `catalog.cache_clear()`.
    """
    return load_names()


@dataclass(frozen=True)
class Enemy:
    """One placement slot.

    `raw` holds the whole entry; named fields are views onto it, so the ~70
    undocumented bytes travel untouched through a `with_*` edit.
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

        🔶 Judged by `type == 0`, which appears to be a sentinel. A whole-entry
        zero test does *not* work: unused slots hold a default in an
        undocumented field rather than being blank.
        """
        if not self.documented:
            return not any(self.raw)
        return self.template == 0

    @property
    def template(self) -> int:
        """Index into the game's `npcEnemyTemplates`, which decides what spawns.

        ⚠️ Not an `NPC_*` value from `npcdrv.h` -- those are *tribe* ids (535
        of them against 435 templates). A template names its tribe separately.
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

    def copied_from(self, other: Enemy) -> Enemy:
        """This slot holding `other`'s whole entry, keeping its own index.

        ✅ **The undocumented bytes come across, and that is the point** (D123).
        A slot built from zeros carries `0` where every shipped enemy carries
        `0xDC` at +0x14, `0x12C` at +0x18 and `2` at +0x68, and those reach the
        live `NPCEntry`. Copying an existing entry is how an author gets them
        without anyone having to name fields nobody has identified -- the same
        principle `raw` already uses to survive a `with_*` edit.
        """
        if other.version != self.version or len(other.raw) != len(self.raw):
            raise SetupError(
                f"cannot copy slot {other.slot} (version {other.version}, "
                f"{len(other.raw)} bytes) onto slot {self.slot} (version "
                f"{self.version}, {len(self.raw)} bytes): the entries differ in shape"
            )
        return replace(self, raw=other.raw)

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

    #: The only type the game can place. `setupItemTemplates` holds exactly one
    #: entry, id 0, so any other value indexes past the end of it. Every one of
    #: the 1,299 items across the 14 maps that place any is this.
    #:
    #: ✅ Read out of the DOL: `setupItemTemplates[0] = {id: 0,
    #: itemTemplateId: 1}`, and item 1 is `ITEM_ID_WORLD_COIN` (D128).
    COIN = 0

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
    # Not an error: the field is padding and read by nothing.
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

    Only 14 files on the disc do, all version 6. Absence is detected by length:
    upstream notes a file without one reads back zeros "because of disc
    alignment", so a zero count cannot be trusted.
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
