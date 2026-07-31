"""Character models: the `/a/<name>` half of each pair in `files/a/`.

⚠️ **Partially decoded.** What this reads is real and checked; the geometry is
not here yet. Saying so precisely matters more than usual, because a model
reader that quietly returns nothing for the vertices would look like a working
model reader.

| | |
|---|---|
| ✅ name, build stamp | read |
| ✅ bounding box | read, and sane — Mario is 58.7 units tall |
| ✅ shape names | read, in file order |
| ✅ texture references | read, and **counted against the TPL bank** |
| ✅ joint names | 176 for Mario |
| ✅ animation clip names | 94 for Mario -- `mario_N_1`, `mario_W_1` |
| ✅ section table | 26 entries, found by structure |
| ⛔ vertices, indices, weights | **not decoded** |
| ⛔ animation keyframes | not decoded -- only the clip names |

## Where the reader lives

This module is the **container**: what a file says about itself, and where its
blocks are. The two decoders that came later sit beside it and are re-exported
here, so `model.Mesh` and `model.curves` still resolve:

| | |
|---|---|
| `bleck.formats.modelmesh` | the shape record at `0x150` and its vertex arrays |
| `bleck.formats.modelanim` | the clip table, its curves and its morph poses |
| `bleck.formats.modelbase` | `ModelError` and the name field, shared by all three |

The seam is the file's own structure: the container locates blocks, and each
decoder reads one kind of block. Dependencies run one way -- this module
imports the other three and none of them imports it back.

## What the file looks like

`files/a/` holds 1,687 files in pairs: `name` (this) and `name-` (a TPL bank,
D-verified). The model half opens with a `u32` pointing at a second header near
the end, then its own name and a build stamp — `p_wii_mario` is a Maya export
from **Mon Jan 29 2007**.

⛔ **It is not `map.dat`'s format.** Rooms announce their sections in a string
table (`mesh`, `material_name_table`, `animation_table`, D167); none of those
markers appears in a character file. Two containers, decoded separately.

## 🟢 The texture link, which is exact

A model names its textures by their **original TGA source paths** —
`ara/playar/mario/w_tex/R_arem.1.tga`. `p_wii_mario` carries **126** of them and
`p_wii_mario-` holds **126** images.

Across all 787 pairs on the disc:

| | |
|---|---|
| references == bank images | 773 |
| references < bank images | 14 |
| **references > bank images** | **0** |

⛔ **That zero is the invariant**, and it is what makes the pairing a reading
rather than a coincidence: a bank may carry images nothing references, but a
model never names an image its bank does not have. ⚠️ Checked, not assumed —
the first version deduplicated the paths, which would have hidden a model that
reuses one, and the counts were re-measured without it.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field
from pathlib import Path

from bleck.formats.modelanim import (
    CLIP_KEY_STRIDE,
    CLIP_POINTER_AT,
    CLIP_SECTIONS,
    CLIP_SECTIONS_AT,
    CLIP_STRIDE,
    CLIP_TRACK_STRIDE,
    COUNTED_SECTIONS,
    KEY_SCALE,
    KEY_SECTION,
    RECORD_COUNTS_AT,
    RECORD_SECTIONS,
    RECORD_SECTIONS_AT,
    RECORD_SIZE_AT,
    TRACK_SECTION,
    Clip,
    Curve,
    Morph,
    Span,
    clips,
    curves,
    morphs,
)
from bleck.formats.modelbase import FIELD, ModelError, text
from bleck.formats.modelmesh import (
    AREA_EPSILON,
    FACE_SLOT,
    FACE_STRIDE,
    FULL_SECTIONS,
    GROUP_STRIDE,
    GROUP_TABLE_AT,
    NORMAL_INDEX_SLOT,
    NORMAL_SLOT,
    POSITION_INDEX_SLOT,
    POSITION_SLOT,
    SHAPE_RECORD_STRIDE,
    SHAPE_SECTIONS,
    SHAPE_SECTIONS_AT,
    TEXCOORD_INDEX_SLOT,
    TEXCOORD_SLOT,
    TRIPLE,
    UNIT_TOLERANCE,
    UV_PAIR,
    Corner,
    Face,
    Mesh,
    Shape,
    Slice,
    mesh,
)

__all__ = [
    "ANIMS_FROM_END",
    "AREA_EPSILON",
    "BOUNDS_AT",
    "CLIP_KEY_STRIDE",
    "CLIP_POINTER_AT",
    "CLIP_SECTIONS",
    "CLIP_SECTIONS_AT",
    "CLIP_STRIDE",
    "CLIP_TRACK_STRIDE",
    "COUNTED_SECTIONS",
    "FACE_SLOT",
    "FACE_STRIDE",
    "FIELD",
    "FULL_SECTIONS",
    "GROUP_STRIDE",
    "GROUP_TABLE_AT",
    "JOINTS_FROM_END",
    "KEY_SCALE",
    "KEY_SECTION",
    "NAME_AT",
    "NORMAL_INDEX_SLOT",
    "NORMAL_SLOT",
    "POSITION_INDEX_SLOT",
    "POSITION_SLOT",
    "RECORD_COUNTS_AT",
    "RECORD_SECTIONS",
    "RECORD_SECTIONS_AT",
    "RECORD_SIZE_AT",
    "SHAPE_RECORD_STRIDE",
    "SHAPE_SECTIONS",
    "SHAPE_SECTIONS_AT",
    "SHAPE_SUFFIX",
    "STAMP_AT",
    "TABLE_LEAST",
    "TABLE_SEARCH",
    "TEXCOORD_INDEX_SLOT",
    "TEXCOORD_SLOT",
    "TEXTURE_RE",
    "TRACK_SECTION",
    "TRIPLE",
    "UNIT_TOLERANCE",
    "UV_PAIR",
    "Bounds",
    "Clip",
    "Corner",
    "Curve",
    "Face",
    "Mesh",
    "Model",
    "ModelError",
    "Morph",
    "Shape",
    "Slice",
    "Span",
    "bank_for",
    "curves",
    "is_model",
    "mesh",
    "morphs",
    "read",
    "section_table",
]

#: The section table is a run of ascending in-file offsets near the start.
#: ⚠️ Located by *structure*, not a fixed offset -- `scripts/modelscan.py
#: offsets` is what found it, and every one of the 870 models has 26 entries.
#: The last two sections are the joint names and the animation clip names.
TABLE_SEARCH = 0x400
TABLE_LEAST = 6
JOINTS_FROM_END = 2
ANIMS_FROM_END = 1

#: A model's own name and its build stamp sit at fixed offsets in the opening
#: record, each in a 32-byte field.
NAME_AT = 0x44
STAMP_AT = 0x84

#: Maya writes every shape's name with this suffix, which is what makes them
#: findable without decoding the node table first.
SHAPE_SUFFIX = b"Shape"

#: Source-art paths, kept verbatim by the exporter.
TEXTURE_RE = re.compile(rb"[A-Za-z0-9_./]+\.tga")

_NAME_RE = re.compile(rb"[A-Za-z0-9_]{2,31}Shape\x00")


@dataclass(frozen=True)
class Bounds:
    """The model's axis-aligned bounding box, in game units."""

    min_x: float
    min_y: float
    min_z: float
    max_x: float
    max_y: float
    max_z: float

    @property
    def height(self) -> float:
        return self.max_y - self.min_y

    def describe(self) -> str:
        return (
            f"({self.min_x:.1f}, {self.min_y:.1f}, {self.min_z:.1f}) .. "
            f"({self.max_x:.1f}, {self.max_y:.1f}, {self.max_z:.1f})"
        )


@dataclass(frozen=True)
class Model:
    """What a character file says about itself, short of its geometry."""

    name: str
    stamp: str
    """The Maya export date, e.g. `Mon Jan 29 10:30:46 2007`."""

    bounds: Bounds
    shapes: list[str] = field(default_factory=list)
    """Mesh names in file order -- `zentaiShape`, `R_Arm_skinShape`."""

    textures: list[str] = field(default_factory=list)
    """Original TGA source paths. ⚠️ These name the images in the `-` bank
    beside this file, and the counts match."""

    joints: list[str] = field(default_factory=list)
    """Skeleton node names -- `R_Arm_skin`, `zentai`, `mario_arm`.

    ⚠️ **Approximate.** Unlike the clip table these records are *not* a fixed
    stride -- the first two are 0x58 apart and the next is 0x59 -- so these are
    scanned rather than indexed, and a name may be missed or carry a stray
    leading byte. Do not count them and conclude anything."""

    animations: list[Clip] = field(default_factory=list)
    """Clips, each with a name and a pointer to its own data. ⚠️ The pointer is
    real and checked; **what it points at is not decoded**, so nothing here can
    play one."""

    @property
    def has_geometry(self) -> bool:
        """⛔ Always False. Vertices are not decoded, and a caller asking this
        is better served by a plain no than by an empty list it might render."""
        return False

    @property
    def can_animate(self) -> bool:
        """⛔ Also always False. `animations` holds names; a name is not a
        curve, and a viewer offered one would have nothing to play."""
        return False

    def describe(self) -> str:
        return (
            f"{self.name}: {len(self.shapes)} shape(s), "
            f"{len(self.textures)} texture(s), {len(self.joints)} joint(s), "
            f"{len(self.animations)} clip(s), bounds {self.bounds.describe()}"
        )


def is_model(data: bytes) -> bool:
    """Whether this looks like the model half of an `files/a/` pair.

    ⚠️ Checked by structure, not by a magic number -- the format has none. The
    leading word must point inside the file, and a name must follow it.
    """
    if len(data) < NAME_AT + FIELD:
        return False
    head = struct.unpack_from(">I", data, 0)[0]
    if not 0 < head < len(data):
        return False
    return bool(text(data[NAME_AT : NAME_AT + FIELD]))


#: In the record the file's leading word points at. The model's own box lives
#: there, not in the opening record.
BOUNDS_AT = 0x44


def _bounds(data: bytes) -> Bounds:
    """The whole model's bounding box.

    ⛔ **Not the opening record's.** A first version scanned that record for six
    plausible floats and found a box — a *sub-object's*, giving Mario a height
    of 17.9 where the model is 58.7. Six numbers that are all individually
    reasonable is exactly what a wrong offset produces here, which is why the
    test asserts a height known independently rather than merely a positive one.

    The real box is at +0x44 of the record the file's leading word points at.
    """
    head = struct.unpack_from(">I", data, 0)[0]
    at = head + BOUNDS_AT
    if at + 24 > len(data):
        raise ModelError(f"the record at {head:#x} runs past the end of the file")
    values = struct.unpack_from(">6f", data, at)
    if any(values[i] > values[i + 3] for i in range(3)):
        raise ModelError(
            f"the six floats at {at:#x} are not a bounding box: "
            f"{values[:3]} is not below {values[3:]}"
        )
    return Bounds(*values)


_ANY_NAME = re.compile(rb"[A-Za-z][A-Za-z0-9_.]{1,31}\x00")


def section_table(data: bytes) -> tuple:  # pylint: disable=container-return
    """Where the section table starts and how many entries it has.

    ⚠️ Found as the longest run of ascending in-file offsets near the start,
    because no fixed offset works: the run begins at 0x148 in `p_wii_mario` and
    a naive look at 0x170 finds only its tail. `scripts/modelscan.py offsets`
    is the tool that showed the fuller table.
    """
    runs: list[tuple[int, int]] = []
    words = min(len(data) // 4, TABLE_SEARCH // 4)
    start = None
    previous = -1
    for index in range(words):
        value = struct.unpack_from(">I", data, index * 4)[0]
        if 0 < value < len(data) and value >= previous:
            if start is None:
                start = index
            previous = value
            continue
        if start is not None and index - start >= TABLE_LEAST:
            runs.append((start * 4, index - start))
        start = None
        previous = -1
    if start is not None and words - start >= TABLE_LEAST:
        runs.append((start * 4, words - start))
    if not runs:
        raise ModelError("no section table found in the first 1 KB")
    return max(runs, key=lambda run: run[1])


def _names_between(data: bytes, start: int, end: int) -> list[str]:
    """Null-terminated names in a padded block.

    ⚠️ Each must be **preceded by a null or the block edge**. Without that the
    tail of the previous entry gets picked up whenever its last byte happens to
    be printable, and `mario_S_3` reads as `Tmario_S_3` -- wrong in a way that
    looks like a real name.
    """
    # pylint: disable=container-return
    if not 0 <= start < end <= len(data):
        return []
    block = data[start:end]
    found = []
    for match in _ANY_NAME.finditer(block):
        if match.start() and block[match.start() - 1] != 0:
            continue
        found.append(match.group()[:-1].decode("ascii", "replace"))
    return found


def read(data: bytes) -> Model:
    """Everything this reader can establish about a character model."""
    if not is_model(data):
        raise ModelError(
            "not a character model: expected a leading offset into the file "
            "and a name at 0x44"
        )
    shapes = [text(m.group()) for m in _NAME_RE.finditer(data)]
    textures = [m.group().decode("ascii", "replace") for m in TEXTURE_RE.finditer(data)]

    joints: list[str] = []
    animations: list[str] = []
    try:
        at, count = section_table(data)
        ends = struct.unpack_from(f">{count}I", data, at)
        head = struct.unpack_from(">I", data, 0)[0]
        joints = _names_between(data, ends[-JOINTS_FROM_END], ends[-ANIMS_FROM_END])
        animations = clips(data, ends[-ANIMS_FROM_END], head)
    except (ModelError, struct.error):
        # ⚠️ Absent, not fatal: 11 of 870 models do not yield both lists, and a
        # model with no clips is still worth reading for everything else.
        pass

    return Model(
        name=text(data[NAME_AT : NAME_AT + FIELD]),
        stamp=text(data[STAMP_AT : STAMP_AT + FIELD]),
        bounds=_bounds(data),
        shapes=shapes,
        # ⚠️ Order preserved and duplicates kept: the count is compared
        # against the bank's image count, and deduplicating would hide a
        # model that legitimately reuses one.
        textures=textures,
        joints=joints,
        animations=animations,
    )


def bank_for(path: Path) -> Path:
    """The TPL bank beside a model: the same name with a trailing `-`."""
    return path.with_name(path.name + "-")
