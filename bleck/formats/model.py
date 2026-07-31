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
| 🔶 offset table | located, targets partly identified |
| ⛔ vertices, indices, weights, joints | **not decoded** |
| ⛔ animations | not decoded |

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

from bleck.common.errors import BleckError

#: A model's own name and its build stamp sit at fixed offsets in the opening
#: record, each in a 32-byte field.
NAME_AT = 0x44
STAMP_AT = 0x84
FIELD = 32

#: Maya writes every shape's name with this suffix, which is what makes them
#: findable without decoding the node table first.
SHAPE_SUFFIX = b"Shape"

#: Source-art paths, kept verbatim by the exporter.
TEXTURE_RE = re.compile(rb"[A-Za-z0-9_./]+\.tga")

_NAME_RE = re.compile(rb"[A-Za-z0-9_]{2,31}Shape\x00")


class ModelError(BleckError):
    """A character model could not be read."""


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

    @property
    def has_geometry(self) -> bool:
        """⛔ Always False. Vertices are not decoded, and a caller asking this
        is better served by a plain no than by an empty list it might render."""
        return False

    def describe(self) -> str:
        return (
            f"{self.name}: {len(self.shapes)} shape(s), "
            f"{len(self.textures)} texture(s), bounds {self.bounds.describe()}"
        )


def _text(raw: bytes) -> str:
    return raw.split(b"\x00")[0].decode("ascii", "replace").strip()


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
    return bool(_text(data[NAME_AT : NAME_AT + FIELD]))


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


def read(data: bytes) -> Model:
    """Everything this reader can establish about a character model."""
    if not is_model(data):
        raise ModelError(
            "not a character model: expected a leading offset into the file "
            "and a name at 0x44"
        )
    shapes = [_text(m.group()) for m in _NAME_RE.finditer(data)]
    textures = [m.group().decode("ascii", "replace") for m in TEXTURE_RE.finditer(data)]
    return Model(
        name=_text(data[NAME_AT : NAME_AT + FIELD]),
        stamp=_text(data[STAMP_AT : STAMP_AT + FIELD]),
        bounds=_bounds(data),
        shapes=shapes,
        # ⚠️ Order preserved and duplicates kept: the count is compared
        # against the bank's image count, and deduplicating would hide a
        # model that legitimately reuses one.
        textures=textures,
    )


def bank_for(path: Path) -> Path:
    """The TPL bank beside a model: the same name with a trailing `-`."""
    return path.with_name(path.name + "-")
